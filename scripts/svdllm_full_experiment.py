"""
Full-model SVD compression experiment using SVD-LLM rank formula.

Compares three strategies on Llama-2-7B:
  1. SVD-LLM (original unaligned ranks from SVD-LLM formula)
  2. Aligned-8 (naive round to nearest multiple of 8)
  3. GAC (DP-optimized alignment)

Reports: alignment statistics, PPL, accuracy, per-layer rank allocations.

Usage:
    python scripts/svdllm_full_experiment.py \
        --ratio 0.7 --output results/svdllm_experiment/ \
        --device cuda:0 --eval-accuracy
"""

import argparse
import json
import math
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn


# ---------------------------------------------------------------------------
# Llama-2-7B constants
# ---------------------------------------------------------------------------
MODEL_ID = "meta-llama/Llama-2-7b-hf"
NUM_LAYERS = 32
HIDDEN_SIZE = 4096
INTERMEDIATE_SIZE = 11008
NUM_HEADS = 32
HEAD_DIM = 128

# Projection types and their matrix shapes (out_features, in_features)
ATTN_PROJS = ["q_proj", "k_proj", "v_proj", "o_proj"]
MLP_PROJS = ["gate_proj", "up_proj", "down_proj"]
ALL_PROJS = ATTN_PROJS + MLP_PROJS

PROJ_SHAPES = {
    "q_proj": (HIDDEN_SIZE, HIDDEN_SIZE),         # (4096, 4096)
    "k_proj": (HIDDEN_SIZE, HIDDEN_SIZE),         # (4096, 4096)
    "v_proj": (HIDDEN_SIZE, HIDDEN_SIZE),         # (4096, 4096)
    "o_proj": (HIDDEN_SIZE, HIDDEN_SIZE),         # (4096, 4096)
    "gate_proj": (INTERMEDIATE_SIZE, HIDDEN_SIZE), # (11008, 4096)
    "up_proj": (INTERMEDIATE_SIZE, HIDDEN_SIZE),   # (11008, 4096)
    "down_proj": (HIDDEN_SIZE, INTERMEDIATE_SIZE), # (4096, 11008)
}


# ---------------------------------------------------------------------------
# SVD-LLM rank formula (from their codebase)
# ---------------------------------------------------------------------------
def svdllm_rank(out_features: int, in_features: int, ratio: float) -> int:
    """Compute SVD-LLM truncation rank for a weight matrix."""
    return int(out_features * in_features * ratio / (out_features + in_features))


def compute_svdllm_ranks(ratio: float) -> Dict[Tuple[int, str], int]:
    """Compute all ranks using SVD-LLM formula (uniform ratio)."""
    ranks = {}
    for layer in range(NUM_LAYERS):
        for proj in ALL_PROJS:
            out_f, in_f = PROJ_SHAPES[proj]
            r = svdllm_rank(out_f, in_f, ratio)
            ranks[(layer, proj)] = r
    return ranks


def compute_total_params(ranks: Dict[Tuple[int, str], int]) -> int:
    """Total parameters in compressed layers."""
    total = 0
    for (layer, proj), r in ranks.items():
        out_f, in_f = PROJ_SHAPES[proj]
        total += r * (out_f + in_f)  # U: (out, r) + V: (r, in)
    return total


# ---------------------------------------------------------------------------
# Fisher score estimation (weight Frobenius norm proxy)
# ---------------------------------------------------------------------------
def compute_fisher_proxy(model) -> Dict[Tuple[int, str], float]:
    """Estimate per-projection Fisher scores from weight magnitudes."""
    scores = {}
    for layer_idx in range(NUM_LAYERS):
        layer = model.model.layers[layer_idx]
        for proj in ATTN_PROJS:
            w = getattr(layer.self_attn, proj).weight.data
            scores[(layer_idx, proj)] = w.float().norm().item() ** 2
        for proj in MLP_PROJS:
            w = getattr(layer.mlp, proj).weight.data
            scores[(layer_idx, proj)] = w.float().norm().item() ** 2
    return scores


# ---------------------------------------------------------------------------
# Strategy: Round to nearest multiple of n, budget-constrained
# ---------------------------------------------------------------------------
def strategy_round_to_n(
    base_ranks: Dict, fisher: Dict, target_budget: int, n: int
) -> Dict[Tuple[int, str], int]:
    """Round each rank to nearest multiple of n, then adjust for budget."""
    ranks = {}
    for key, r in base_ranks.items():
        rounded = max(n, round(r / n) * n)
        out_f, in_f = PROJ_SHAPES[key[1]]
        max_rank = min(out_f, in_f)
        ranks[key] = min(rounded, max_rank)

    total = compute_total_params(ranks)

    # Sort by Fisher score
    keys_by_fisher_asc = sorted(ranks.keys(), key=lambda k: fisher.get(k, 0))
    keys_by_fisher_desc = list(reversed(keys_by_fisher_asc))

    # Reduce from least sensitive if over budget
    while total > target_budget:
        reduced = False
        for k in keys_by_fisher_asc:
            if ranks[k] > n:
                old_r = ranks[k]
                ranks[k] -= n
                out_f, in_f = PROJ_SHAPES[k[1]]
                total -= n * (out_f + in_f)
                reduced = True
                if total <= target_budget:
                    break
        if not reduced:
            break

    # Add to most sensitive if under budget
    while True:
        added = False
        for k in keys_by_fisher_desc:
            out_f, in_f = PROJ_SHAPES[k[1]]
            cost = n * (out_f + in_f)
            max_rank = min(out_f, in_f)
            if ranks[k] + n <= max_rank and total + cost <= target_budget:
                ranks[k] += n
                total += cost
                added = True
        if not added:
            break

    return ranks


# ---------------------------------------------------------------------------
# Strategy: GAC DP (multi-choice knapsack)
# ---------------------------------------------------------------------------
def strategy_gac_dp(
    base_ranks: Dict,
    fisher: Dict,
    target_budget: int,
    align: int = 8,
    search_radius: int = 4,
) -> Dict[Tuple[int, str], int]:
    """
    GAC DP: optimize aligned rank allocation.

    For each projection, generate candidates (multiples of align near the
    SVD-LLM rank). DP maximizes Fisher-weighted value under budget constraint.
    """
    projections = []
    for layer in range(NUM_LAYERS):
        for proj in ALL_PROJS:
            key = (layer, proj)
            ideal = base_ranks[key]
            f_i = fisher.get(key, 1.0)
            out_f, in_f = PROJ_SHAPES[proj]
            max_rank = min(out_f, in_f)

            ideal_aligned = round(ideal / align) * align
            candidates = []
            for offset in range(-search_radius, search_radius + 1):
                c = ideal_aligned + offset * align
                if c < align:
                    continue
                if c > max_rank:
                    continue
                candidates.append(c)

            if not candidates:
                candidates = [max(align, min(max_rank, ideal_aligned))]

            projections.append({
                "key": key,
                "ideal": ideal,
                "fisher": f_i,
                "candidates": candidates,
                "param_cost_per_rank": out_f + in_f,
            })

    # DP with param budget
    # Scale to manageable units: use align * min_cost as quantum
    min_cost = min(p["param_cost_per_rank"] for p in projections)
    # Use a simplified DP: since we have two types of projections (attn/MLP)
    # with different costs, we track budget directly

    # For tractability, discretize budget in units of (align * min_cost)
    budget_unit = align * min_cost
    B = target_budget // budget_unit + 2

    if B > 500000:
        # Budget too large for DP, fall back to greedy
        print(f"  Budget too large for DP (B={B}), using greedy alignment")
        return strategy_round_to_n(base_ranks, fisher, target_budget, align)

    n = len(projections)
    NEG_INF = float("-inf")

    dp = [NEG_INF] * (B + 1)
    dp[0] = 0.0
    choice = [[None] * (B + 1) for _ in range(n)]

    for i, proj in enumerate(projections):
        new_dp = [NEG_INF] * (B + 1)
        for c in proj["candidates"]:
            value_c = proj["fisher"] * (c - proj["ideal"])
            c_cost = c * proj["param_cost_per_rank"]
            c_units = c_cost // budget_unit
            if c_units > B:
                continue
            for b in range(int(c_units), B + 1):
                prev_b = b - int(c_units)
                if dp[prev_b] > NEG_INF and dp[prev_b] + value_c > new_dp[b]:
                    new_dp[b] = dp[prev_b] + value_c
                    choice[i][b] = c
        dp = new_dp

    # Find best feasible solution
    max_b = target_budget // budget_unit
    best_b = None
    best_value = NEG_INF
    for b in range(min(max_b, B), max(0, max_b - 10), -1):
        if dp[b] > NEG_INF:
            if dp[b] > best_value:
                best_b = b
                best_value = dp[b]
            break

    if best_b is None:
        for b in range(min(max_b, B), -1, -1):
            if dp[b] > NEG_INF:
                best_b = b
                best_value = dp[b]
                break

    if best_b is None:
        return strategy_round_to_n(base_ranks, fisher, target_budget, align)

    # Backtrack
    ranks = {}
    b = best_b
    for i in range(n - 1, -1, -1):
        c = choice[i][b]
        if c is None:
            c = projections[i]["candidates"][len(projections[i]["candidates"]) // 2]
        ranks[projections[i]["key"]] = c
        c_cost = c * projections[i]["param_cost_per_rank"]
        b -= int(c_cost // budget_unit)

    return ranks


# ---------------------------------------------------------------------------
# Full-model SVD compression module
# ---------------------------------------------------------------------------
class FullModelLowRankLinear(nn.Module):
    """Low-rank linear layer: input -> V (rank x in) -> U (out x rank)."""

    def __init__(self, in_features, out_features, rank, bias=False):
        super().__init__()
        self.rank = rank
        self.V_proj = nn.Linear(in_features, rank, bias=False)
        self.U_proj = nn.Linear(rank, out_features, bias=bias)

    def forward(self, x):
        return self.U_proj(self.V_proj(x))

    @staticmethod
    def from_linear(linear: nn.Linear, rank: int):
        has_bias = linear.bias is not None
        module = FullModelLowRankLinear(
            linear.in_features, linear.out_features, rank, bias=has_bias
        )
        W = linear.weight.data.float()
        U, S, Vt = torch.linalg.svd(W, full_matrices=False)
        U = U[:, :rank]
        S = S[:rank]
        Vt = Vt[:rank, :]
        sqrtS = torch.diag(torch.sqrt(S))
        svd_u = (U @ sqrtS).to(linear.weight.dtype)
        svd_v = (sqrtS @ Vt).to(linear.weight.dtype)

        module.U_proj.weight.data = svd_u.contiguous()
        module.V_proj.weight.data = svd_v.contiguous()
        if has_bias:
            module.U_proj.bias.data = linear.bias.data.clone()

        return module


# ---------------------------------------------------------------------------
# Compression + Evaluation
# ---------------------------------------------------------------------------
def compress_model(model, ranks: Dict[Tuple[int, str], int]):
    """Replace all target linear layers with low-rank versions."""
    n_compressed = 0
    for layer_idx in range(NUM_LAYERS):
        layer = model.model.layers[layer_idx]
        for proj in ATTN_PROJS:
            key = (layer_idx, proj)
            if key in ranks:
                old = getattr(layer.self_attn, proj)
                new = FullModelLowRankLinear.from_linear(old, ranks[key])
                setattr(layer.self_attn, proj, new)
                n_compressed += 1
                del old

        for proj in MLP_PROJS:
            key = (layer_idx, proj)
            if key in ranks:
                old = getattr(layer.mlp, proj)
                new = FullModelLowRankLinear.from_linear(old, ranks[key])
                setattr(layer.mlp, proj, new)
                n_compressed += 1
                del old

        torch.cuda.empty_cache()
    return n_compressed


@torch.no_grad()
def compute_perplexity(model, tokenizer, device, block_size=512):
    """Compute WikiText-2 PPL."""
    from datasets import load_dataset
    ds = load_dataset("wikitext", "wikitext-2-raw-v1", split="test")
    text = "\n".join([t for t in ds["text"] if t.strip()])
    enc = tokenizer(text, return_tensors="pt")
    input_ids = enc.input_ids.to(device)

    nlls = []
    total_tokens = 0
    model.eval()
    for i in range(0, input_ids.size(1) - 1, block_size):
        chunk = input_ids[:, i:i + block_size]
        if chunk.size(1) < 2:
            continue
        out = model(chunk, labels=chunk)
        nll = out.loss * chunk.size(1)
        nlls.append(nll)
        total_tokens += chunk.size(1)

    nll_sum = torch.stack(nlls).sum()
    ppl = torch.exp(nll_sum / total_tokens).item()
    return {"ppl": ppl, "nll": nll_sum.item(), "tokens": total_tokens}


@torch.no_grad()
def eval_accuracy(model, tokenizer, device, tasks="piqa,hellaswag", limit=200):
    """Run lm-eval harness for accuracy."""
    try:
        import lm_eval
        from lm_eval.models.huggingface import HFLM

        lm = HFLM(pretrained=model, tokenizer=tokenizer, device=device,
                   batch_size=4)
        task_list = tasks.split(",")
        results = lm_eval.simple_evaluate(
            model=lm,
            tasks=task_list,
            limit=limit,
        )
        accs = {}
        for task_name in task_list:
            task_results = results["results"].get(task_name, {})
            acc = task_results.get("acc,none", task_results.get("acc_norm,none", None))
            if acc is not None:
                accs[task_name] = acc
        return accs
    except Exception as e:
        print(f"  lm-eval failed: {e}")
        return {}


def analyze_alignment(ranks: Dict[Tuple[int, str], int]) -> Dict:
    """Compute alignment statistics for a rank allocation."""
    all_ranks = list(ranks.values())
    n = len(all_ranks)
    n_aligned_8 = sum(1 for r in all_ranks if r % 8 == 0)
    n_aligned_64 = sum(1 for r in all_ranks if r % 64 == 0)
    n_misaligned = n - n_aligned_8
    unique_ranks = sorted(set(all_ranks))

    return {
        "n_projections": n,
        "n_aligned_mod8": n_aligned_8,
        "n_aligned_mod64": n_aligned_64,
        "n_misaligned_mod8": n_misaligned,
        "pct_aligned_mod8": 100.0 * n_aligned_8 / n,
        "unique_ranks": unique_ranks,
        "rank_mean": np.mean(all_ranks),
        "rank_min": min(all_ranks),
        "rank_max": max(all_ranks),
    }


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------
def generate_plots(all_results: list, ranks_dict: dict, output_dir: Path):
    """Generate comparison plots."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir = output_dir / "plots"
    plot_dir.mkdir(exist_ok=True)

    strategies = [r["strategy"] for r in all_results]
    ppls = [r.get("ppl", 0) for r in all_results]
    alignments = [r.get("pct_aligned_mod8", 0) for r in all_results]

    # 1. PPL comparison bar chart
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = ["#e74c3c", "#3498db", "#2ecc71"][:len(strategies)]
    bars = ax.bar(strategies, ppls, color=colors, edgecolor="black", linewidth=0.8)
    for bar, ppl in zip(bars, ppls):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                f"{ppl:.2f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.set_ylabel("Perplexity (WikiText-2)", fontsize=12)
    ax.set_title("PPL Comparison: SVD-LLM vs Aligned Strategies", fontsize=13)
    ax.set_ylim(bottom=0, top=max(ppls) * 1.15 if ppls else 10)
    plt.tight_layout()
    plt.savefig(plot_dir / "ppl_comparison.png", dpi=150)
    plt.close()

    # 2. Alignment bar chart
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(strategies, alignments, color=colors, edgecolor="black", linewidth=0.8)
    for bar, a in zip(bars, alignments):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f"{a:.0f}%", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.set_ylabel("% Projections Aligned (mod 8)", fontsize=12)
    ax.set_title("Dimension Alignment Comparison", fontsize=13)
    ax.set_ylim(0, 110)
    plt.tight_layout()
    plt.savefig(plot_dir / "alignment_comparison.png", dpi=150)
    plt.close()

    # 3. Per-layer rank heatmap for each strategy
    for strat_name, ranks in ranks_dict.items():
        fig, ax = plt.subplots(figsize=(12, 5))
        # Build matrix: rows = projection types, cols = layers
        matrix = np.zeros((len(ALL_PROJS), NUM_LAYERS))
        for j, proj in enumerate(ALL_PROJS):
            for layer in range(NUM_LAYERS):
                matrix[j, layer] = ranks.get((layer, proj), 0)

        im = ax.imshow(matrix, aspect="auto", cmap="viridis")
        ax.set_xticks(range(0, NUM_LAYERS, 4))
        ax.set_xticklabels(range(0, NUM_LAYERS, 4))
        ax.set_yticks(range(len(ALL_PROJS)))
        ax.set_yticklabels(ALL_PROJS)
        ax.set_xlabel("Layer")
        ax.set_title(f"Rank Allocation: {strat_name}")
        plt.colorbar(im, ax=ax, label="Rank")
        plt.tight_layout()
        plt.savefig(plot_dir / f"ranks_{strat_name}.png", dpi=150)
        plt.close()

    # 4. Combined accuracy + PPL plot if accuracy data exists
    has_accuracy = any("accuracy" in r and r["accuracy"] for r in all_results)
    if has_accuracy:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        ax1.bar(strategies, ppls, color=colors, edgecolor="black")
        ax1.set_ylabel("Perplexity")
        ax1.set_title("Perplexity")

        # Average accuracy
        avg_accs = []
        for r in all_results:
            accs = r.get("accuracy", {})
            avg_accs.append(np.mean(list(accs.values())) * 100 if accs else 0)
        ax2.bar(strategies, avg_accs, color=colors, edgecolor="black")
        ax2.set_ylabel("Accuracy (%)")
        ax2.set_title("Average Accuracy (piqa, hellaswag)")
        plt.tight_layout()
        plt.savefig(plot_dir / "combined_results.png", dpi=150)
        plt.close()

    print(f"  Plots saved to {plot_dir}/")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Full-model SVD compression experiment")
    parser.add_argument("--ratio", type=float, default=0.7,
                        help="Keep ratio (fraction of params to keep, default 0.7)")
    parser.add_argument("--output", type=str, default="results/svdllm_experiment")
    parser.add_argument("--device", type=str, default="cuda:0")
    parser.add_argument("--dtype", type=str, default="float16",
                        choices=["float16", "bfloat16"])
    parser.add_argument("--eval-accuracy", action="store_true",
                        help="Also run lm-eval accuracy benchmark")
    parser.add_argument("--accuracy-tasks", type=str, default="piqa,hellaswag")
    parser.add_argument("--accuracy-limit", type=int, default=200)
    parser.add_argument("--skip-baseline", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    dtype = torch.float16 if args.dtype == "float16" else torch.bfloat16

    print("=" * 70)
    print("Full-Model SVD Compression Experiment")
    print(f"Model: {MODEL_ID}")
    print(f"Keep ratio: {args.ratio}")
    print(f"Device: {args.device}")
    print("=" * 70)

    # ---------------------------------------------------------------
    # Step 1: Compute SVD-LLM ranks
    # ---------------------------------------------------------------
    print("\n[Step 1] Computing SVD-LLM ranks...")
    svdllm_ranks = compute_svdllm_ranks(args.ratio)
    svdllm_budget = compute_total_params(svdllm_ranks)

    # Print rank info
    attn_rank = svdllm_ranks[(0, "q_proj")]
    mlp_rank_gateup = svdllm_ranks[(0, "gate_proj")]
    mlp_rank_down = svdllm_ranks[(0, "down_proj")]
    print(f"  Attention rank: {attn_rank} (mod 8 = {attn_rank % 8})")
    print(f"  MLP gate/up rank: {mlp_rank_gateup} (mod 8 = {mlp_rank_gateup % 8})")
    print(f"  MLP down rank: {mlp_rank_down} (mod 8 = {mlp_rank_down % 8})")
    print(f"  Total compressed params: {svdllm_budget:,}")

    # ---------------------------------------------------------------
    # Step 2: Load model and compute Fisher proxy
    # ---------------------------------------------------------------
    print("\n[Step 2] Loading model and computing Fisher scores...")
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID, torch_dtype=dtype, device_map="auto"
    )
    fisher = compute_fisher_proxy(model)
    print(f"  Fisher scores computed for {len(fisher)} projections")

    # Save Fisher scores
    fisher_list = [{"layer": k[0], "proj": k[1], "fisher": v}
                   for k, v in sorted(fisher.items())]
    with open(out_dir / "fisher_scores.json", "w") as f:
        json.dump(fisher_list, f, indent=2)

    # ---------------------------------------------------------------
    # Step 3: Create three rank allocation strategies
    # ---------------------------------------------------------------
    print("\n[Step 3] Creating rank allocation strategies...")

    strategies_ranks = {
        "svdllm": svdllm_ranks,
        "aligned_8": strategy_round_to_n(svdllm_ranks, fisher, svdllm_budget, 8),
        "gac_dp": strategy_gac_dp(svdllm_ranks, fisher, svdllm_budget, align=8,
                                   search_radius=3),
    }

    # Print summary
    print(f"\n{'Strategy':<12} {'Budget':>12} {'Aligned/8':>10} {'Misaligned':>10} "
          f"{'Unique Ranks':>13}")
    print("-" * 65)
    for name, ranks in strategies_ranks.items():
        stats = analyze_alignment(ranks)
        budget = compute_total_params(ranks)
        print(f"{name:<12} {budget:>12,} {stats['n_aligned_mod8']:>6}/{stats['n_projections']}"
              f"   {stats['n_misaligned_mod8']:>6}"
              f"   {stats['unique_ranks']}")

    # Save rank allocations
    for name, ranks in strategies_ranks.items():
        rank_data = [{"layer": k[0], "proj": k[1], "rank": v}
                     for k, v in sorted(ranks.items())]
        with open(out_dir / f"ranks_{name}.json", "w") as f:
            json.dump(rank_data, f, indent=2)

    # ---------------------------------------------------------------
    # Step 4: Evaluate baseline (uncompressed)
    # ---------------------------------------------------------------
    all_results = []

    if not args.skip_baseline:
        print("\n[Step 4a] Evaluating baseline (uncompressed)...")
        t0 = time.time()
        ppl_result = compute_perplexity(model, tokenizer, args.device)
        print(f"  Baseline PPL: {ppl_result['ppl']:.2f} ({time.time()-t0:.0f}s)")

        baseline_result = {
            "strategy": "baseline",
            "ppl": ppl_result["ppl"],
            "nll": ppl_result["nll"],
            "tokens": ppl_result["tokens"],
            "alignment": {"pct_aligned_mod8": 100.0, "n_projections": 0},
        }
        if args.eval_accuracy:
            accs = eval_accuracy(model, tokenizer, args.device,
                                 args.accuracy_tasks, args.accuracy_limit)
            baseline_result["accuracy"] = accs
            print(f"  Baseline accuracy: {accs}")
        all_results.append(baseline_result)

    # Free base model
    del model
    torch.cuda.empty_cache()

    # ---------------------------------------------------------------
    # Step 5: For each strategy, compress and evaluate
    # ---------------------------------------------------------------
    for strat_name, ranks in strategies_ranks.items():
        print(f"\n[Step 5] Evaluating strategy: {strat_name}")
        t0 = time.time()

        # Reload fresh model
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, torch_dtype=dtype, device_map="auto"
        )

        # Compress
        print(f"  Compressing {len(ranks)} projections...")
        n_compressed = compress_model(model, ranks)
        print(f"  Compressed {n_compressed} projections in {time.time()-t0:.0f}s")

        # Count params
        total_params = sum(p.numel() for p in model.parameters())
        lr_params = sum(p.numel() for m in model.modules()
                        if isinstance(m, FullModelLowRankLinear)
                        for p in m.parameters())
        print(f"  Total params: {total_params:,}")

        # PPL
        print(f"  Computing PPL...")
        t1 = time.time()
        ppl_result = compute_perplexity(model, tokenizer, args.device)
        print(f"  PPL: {ppl_result['ppl']:.2f} ({time.time()-t1:.0f}s)")

        alignment = analyze_alignment(ranks)
        result = {
            "strategy": strat_name,
            "ppl": ppl_result["ppl"],
            "nll": ppl_result["nll"],
            "tokens": ppl_result["tokens"],
            "total_params": total_params,
            "lr_params": lr_params,
            "compressed_budget": compute_total_params(ranks),
            "alignment": alignment,
            "ranks_summary": {
                "attn_ranks": sorted(set(ranks[(l, p)]
                                         for l in range(NUM_LAYERS)
                                         for p in ATTN_PROJS)),
                "mlp_ranks": sorted(set(ranks[(l, p)]
                                        for l in range(NUM_LAYERS)
                                        for p in MLP_PROJS)),
            },
        }

        # Accuracy
        if args.eval_accuracy:
            print(f"  Running lm-eval...")
            accs = eval_accuracy(model, tokenizer, args.device,
                                 args.accuracy_tasks, args.accuracy_limit)
            result["accuracy"] = accs
            print(f"  Accuracy: {accs}")

        all_results.append(result)

        del model
        torch.cuda.empty_cache()

    # ---------------------------------------------------------------
    # Step 6: Summary and plots
    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    header = f"{'Strategy':<12} {'PPL':>8} {'Aligned%':>9} {'Budget':>12}"
    if args.eval_accuracy:
        header += f"  {'Avg Acc':>8}"
    print(header)
    print("-" * len(header))
    for r in all_results:
        ppl_str = f"{r['ppl']:.2f}" if r.get("ppl") else "N/A"
        align_str = f"{r.get('alignment', {}).get('pct_aligned_mod8', 100):.0f}%"
        budget_str = f"{r.get('compressed_budget', 0):,}" if r.get("compressed_budget") else "-"
        line = f"{r['strategy']:<12} {ppl_str:>8} {align_str:>9} {budget_str:>12}"
        if args.eval_accuracy:
            accs = r.get("accuracy", {})
            avg = np.mean(list(accs.values())) * 100 if accs else 0
            line += f"  {avg:>7.1f}%"
        print(line)

    # Save all results
    results_file = out_dir / "results.json"
    with open(results_file, "w") as f:
        json.dump(all_results, f, indent=2, default=lambda x: x.tolist()
                  if isinstance(x, np.ndarray) else str(x))
    print(f"\nResults saved to {results_file}")

    # Generate plots
    print("\n[Step 6] Generating plots...")
    generate_plots(all_results, strategies_ranks, out_dir)

    print("\nExperiment complete!")


if __name__ == "__main__":
    main()
