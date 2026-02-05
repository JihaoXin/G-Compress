"""
Full-model SVD-LLM compression experiment with GAC rank alignment.

Uses SVD-LLM's whitening-based compression on Llama-3-8B, comparing:
  1. SVD-LLM (original unaligned ranks)
  2. Aligned-8 (round to nearest multiple of 8)
  3. GAC (DP-optimized alignment)

Key difference from plain truncated SVD: uses Cholesky-whitened SVD
(calibration-aware) which preserves much more model quality.

Usage (via Slurm):
    sbatch slurm/run_svdllm_experiment.sbatch
"""

import os
import sys
import argparse
import json
import math
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn
from tqdm import tqdm
from transformers import AutoModelForCausalLM, AutoTokenizer

# Add SVD-LLM to path for data utils
SVDLLM_DIR = Path(__file__).parent.parent / "third_party" / "SVD-LLM"
sys.path.insert(0, str(SVDLLM_DIR))
from utils.data_utils import get_calib_train_data, get_test_data


# ---------------------------------------------------------------------------
# Model utilities (replaces SVD-LLM's model_utils for Llama-3 compat)
# ---------------------------------------------------------------------------
def load_model(model_id):
    """Load model and tokenizer using standard HF AutoModel (supports GQA)."""
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_id, device_map="cpu", torch_dtype=torch.float16, trust_remote_code=True
    )
    model.seqlen = 2048
    return model, tokenizer


def find_layers(module, layers=[nn.Conv2d, nn.Linear], name=''):
    """Recursively find all layers of given types."""
    if type(module) in layers:
        return {name: module}
    res = {}
    for name1, child in module.named_children():
        res.update(find_layers(
            child, layers=layers, name=name + '.' + name1 if name != '' else name1
        ))
    return res


# ---------------------------------------------------------------------------
# Constants for Llama-3-8B (GQA: 32 Q heads, 8 KV heads, head_dim=128)
# ---------------------------------------------------------------------------
MODEL_ID = "meta-llama/Meta-Llama-3-8B"
NUM_LAYERS = 32
HIDDEN = 4096
INTER = 14336
NUM_KV_HEADS = 8
HEAD_DIM = 128
KV_DIM = NUM_KV_HEADS * HEAD_DIM  # 1024

ATTN_PROJS = ["q_proj", "k_proj", "v_proj", "o_proj"]
MLP_PROJS = ["gate_proj", "up_proj", "down_proj"]
ALL_PROJS = ATTN_PROJS + MLP_PROJS

PROJ_SHAPES = {
    "q_proj": (HIDDEN, HIDDEN), "k_proj": (KV_DIM, HIDDEN),
    "v_proj": (KV_DIM, HIDDEN), "o_proj": (HIDDEN, HIDDEN),
    "gate_proj": (INTER, HIDDEN), "up_proj": (INTER, HIDDEN),
    "down_proj": (HIDDEN, INTER),
}


# ---------------------------------------------------------------------------
# SVD-LLM rank formula
# ---------------------------------------------------------------------------
def svdllm_rank(m, n, ratio):
    return int(m * n * ratio / (m + n))


def compute_all_svdllm_ranks(ratio):
    ranks = {}
    for layer in range(NUM_LAYERS):
        for proj in ALL_PROJS:
            m, n = PROJ_SHAPES[proj]
            ranks[(layer, proj)] = svdllm_rank(m, n, ratio)
    return ranks


def param_cost(ranks):
    total = 0
    for (layer, proj), r in ranks.items():
        m, n = PROJ_SHAPES[proj]
        total += r * (m + n)
    return total


# ---------------------------------------------------------------------------
# Fisher proxy (weight Frobenius norm²)
# ---------------------------------------------------------------------------
def compute_fisher_proxy(model):
    scores = {}
    layers = model.model.layers
    for i in range(NUM_LAYERS):
        subset = find_layers(layers[i])
        for name, module in subset.items():
            # name is like "self_attn.q_proj" or "mlp.gate_proj"
            proj = name.split(".")[-1]
            if proj in ALL_PROJS:
                scores[(i, proj)] = module.weight.data.float().norm().item() ** 2
    return scores


# ---------------------------------------------------------------------------
# Strategy: Round to nearest n, budget-constrained
# ---------------------------------------------------------------------------
def strategy_round_to_n(base_ranks, fisher, target_budget, n=8):
    ranks = {}
    for key, r in base_ranks.items():
        rounded = max(n, round(r / n) * n)
        m, nf = PROJ_SHAPES[key[1]]
        ranks[key] = min(rounded, min(m, nf))

    total = param_cost(ranks)
    keys_asc = sorted(ranks.keys(), key=lambda k: fisher.get(k, 0))
    keys_desc = list(reversed(keys_asc))

    while total > target_budget:
        reduced = False
        for k in keys_asc:
            if ranks[k] > n:
                m, nf = PROJ_SHAPES[k[1]]
                ranks[k] -= n
                total -= n * (m + nf)
                reduced = True
                if total <= target_budget:
                    break
        if not reduced:
            break

    while True:
        added = False
        for k in keys_desc:
            m, nf = PROJ_SHAPES[k[1]]
            cost = n * (m + nf)
            if ranks[k] + n <= min(m, nf) and total + cost <= target_budget:
                ranks[k] += n
                total += cost
                added = True
        if not added:
            break
    return ranks


# ---------------------------------------------------------------------------
# Strategy: GAC DP
# ---------------------------------------------------------------------------
def strategy_gac_dp(base_ranks, fisher, target_budget, align=8, search_radius=3):
    """GAC DP: multi-choice knapsack for optimal aligned rank allocation."""
    projections = []
    for layer in range(NUM_LAYERS):
        for proj in ALL_PROJS:
            key = (layer, proj)
            ideal = base_ranks[key]
            f_i = fisher.get(key, 1.0)
            m, n = PROJ_SHAPES[proj]
            max_rank = min(m, n)
            unit_cost = m + n  # cost per rank unit

            ideal_aligned = round(ideal / align) * align
            candidates = []
            for offset in range(-search_radius, search_radius + 1):
                c = ideal_aligned + offset * align
                if align <= c <= max_rank:
                    candidates.append(c)
            if not candidates:
                candidates = [max(align, min(max_rank, ideal_aligned))]

            projections.append({
                "key": key, "ideal": ideal, "fisher": f_i,
                "candidates": candidates, "unit_cost": unit_cost,
            })

    # DP with budget in units of (align * min_unit_cost)
    min_uc = min(p["unit_cost"] for p in projections)
    budget_unit = align * min_uc
    B = target_budget // budget_unit + 2

    if B > 500000:
        print(f"  DP too large (B={B}), using greedy")
        return strategy_round_to_n(base_ranks, fisher, target_budget, align)

    n_proj = len(projections)
    NEG_INF = float("-inf")
    dp = [NEG_INF] * (B + 1)
    dp[0] = 0.0
    choice = [[None] * (B + 1) for _ in range(n_proj)]

    for i, p in enumerate(projections):
        new_dp = [NEG_INF] * (B + 1)
        for c in p["candidates"]:
            val = p["fisher"] * (c - p["ideal"])
            c_units = (c * p["unit_cost"]) // budget_unit
            if c_units > B:
                continue
            for b in range(int(c_units), B + 1):
                prev = b - int(c_units)
                if dp[prev] > NEG_INF and dp[prev] + val > new_dp[b]:
                    new_dp[b] = dp[prev] + val
                    choice[i][b] = c
        dp = new_dp

    max_b = target_budget // budget_unit
    best_b = None
    for b in range(min(max_b, B), max(0, max_b - 10), -1):
        if dp[b] > NEG_INF:
            best_b = b
            break
    if best_b is None:
        for b in range(min(max_b, B), -1, -1):
            if dp[b] > NEG_INF:
                best_b = b
                break
    if best_b is None:
        return strategy_round_to_n(base_ranks, fisher, target_budget, align)

    ranks = {}
    b = best_b
    for i in range(n_proj - 1, -1, -1):
        c = choice[i][b]
        if c is None:
            c = projections[i]["candidates"][len(projections[i]["candidates"]) // 2]
        ranks[projections[i]["key"]] = c
        b -= int((c * projections[i]["unit_cost"]) // budget_unit)

    # Post-processing: enforce exact budget constraint
    # DP discretization can cause actual budget to exceed target
    actual = param_cost(ranks)
    if actual > target_budget:
        # Sort projections by Fisher (ascending) — reduce least sensitive first
        items = sorted(ranks.keys(), key=lambda k: fisher.get(k, 0))
        for k in items:
            if actual <= target_budget:
                break
            m, n = PROJ_SHAPES[k[1]]
            if ranks[k] > align:
                ranks[k] -= align
                actual -= align * (m + n)

    # Fill remaining budget with most sensitive projections
    items_desc = sorted(ranks.keys(), key=lambda k: fisher.get(k, 0), reverse=True)
    for k in items_desc:
        m, n = PROJ_SHAPES[k[1]]
        cost = align * (m + n)
        if ranks[k] + align <= min(m, n) and actual + cost <= target_budget:
            ranks[k] += align
            actual += cost

    return ranks


# ---------------------------------------------------------------------------
# Profiling (Cholesky whitening matrices) - computed once
# ---------------------------------------------------------------------------
@torch.no_grad()
def compute_profiling(model, model_name, calib_loader, dev):
    """Compute Cholesky whitening matrices per linear layer (SVD-LLM step 1)."""
    layers = model.model.layers
    model.model.embed_tokens = model.model.embed_tokens.to(dev)
    model.model.norm = model.model.norm.to(dev)
    # Move rotary_emb to device (transformers >= 4.46 stores it at model level)
    if hasattr(model.model, 'rotary_emb'):
        model.model.rotary_emb = model.model.rotary_emb.to(dev)
    layers[0] = layers[0].to(dev)

    dtype = next(iter(model.parameters())).dtype
    inps = torch.zeros(
        (len(calib_loader), model.seqlen, model.config.hidden_size),
        dtype=dtype, device=dev
    )
    cache = {'i': 0, 'attention_mask': None, 'position_ids': None,
             'position_embeddings': None}

    class Catcher(nn.Module):
        def __init__(self, module):
            super().__init__()
            self.module = module
        def forward(self, inp, **kwargs):
            inps[cache['i']] = inp.cpu()
            cache['i'] += 1
            # Capture kwargs — handle None values from newer transformers
            am = kwargs.get('attention_mask')
            pi = kwargs.get('position_ids')
            pe = kwargs.get('position_embeddings')
            if cache['i'] == 1:  # first sample
                cache['attention_mask'] = am.cpu() if am is not None else None
                cache['position_ids'] = pi.cpu() if pi is not None else None
                if pe is not None:
                    cache['position_embeddings'] = tuple(t.cpu() for t in pe)
            else:
                if am is not None and cache['attention_mask'] is not None:
                    cache['attention_mask'] = torch.cat(
                        (cache['attention_mask'], am.cpu()), dim=0)
                if pi is not None and cache['position_ids'] is not None:
                    cache['position_ids'] = torch.cat(
                        (cache['position_ids'], pi.cpu()), dim=0)
                if pe is not None and cache['position_embeddings'] is not None:
                    new_pe = tuple(t.cpu() for t in pe)
                    cache['position_embeddings'] = tuple(
                        torch.cat((old, new), dim=0)
                        for old, new in zip(cache['position_embeddings'], new_pe)
                    )
            raise ValueError

    layers[0] = Catcher(layers[0])
    for batch in calib_loader:
        try:
            batch = {k: v.to(dev) for k, v in batch.items()}
            model(**batch)
        except ValueError:
            pass
    layers[0] = layers[0].module
    layers[0] = layers[0].cpu()
    model.model.embed_tokens = model.model.embed_tokens.cpu()
    model.model.norm = model.model.norm.cpu()
    if hasattr(model.model, 'rotary_emb'):
        model.model.rotary_emb = model.model.rotary_emb.cpu()
    torch.cuda.empty_cache()

    outs = torch.zeros_like(inps)
    attention_masks = cache['attention_mask']
    position_ids = cache.get('position_ids')
    position_embeddings = cache.get('position_embeddings')

    profiling_mat = {}
    print("Computing Cholesky whitening matrices...")
    for i in tqdm(range(len(layers))):
        layer_profile = {}
        layer = layers[i].to(dev)
        # Also move rotary_emb to device for per-layer forwarding
        if hasattr(model.model, 'rotary_emb'):
            model.model.rotary_emb = model.model.rotary_emb.to(dev)
        subset = find_layers(layer)

        def hook(module, input, output):
            inp = input[0].detach().float()
            if inp.dim() == 2:
                inp = inp.unsqueeze(0)
            adds = torch.matmul(inp.transpose(1, 2), inp)
            module.scaling_diag_matrix += torch.sum(adds, dim=0)
            del inp, adds
            torch.cuda.empty_cache()

        handles = []
        for name in subset:
            subset[name].scaling_diag_matrix = 0
            handles.append(subset[name].register_forward_hook(hook))

        for j in range(inps.shape[0]):
            kwargs = {}
            if attention_masks is not None:
                kwargs["attention_mask"] = attention_masks[j].unsqueeze(0).to(dev)
            if position_embeddings is not None:
                kwargs["position_embeddings"] = tuple(
                    t[j].unsqueeze(0).to(dev) for t in position_embeddings
                )
            elif position_ids is not None:
                kwargs["position_ids"] = position_ids[j].unsqueeze(0).to(dev)
            outs[j] = layer(
                inps[j].unsqueeze(0).to(dev), **kwargs
            )[0].cpu()

        for h in handles:
            h.remove()
        layer = layer.cpu()
        if hasattr(model.model, 'rotary_emb'):
            model.model.rotary_emb = model.model.rotary_emb.cpu()

        for name in subset:
            raw = subset[name].scaling_diag_matrix.double().to(dev)
            try:
                chol = torch.linalg.cholesky(raw)
            except Exception:
                eigenvalues = torch.linalg.eigvalsh(raw)
                raw += (-eigenvalues[0] + 1e-6) * torch.eye(raw.shape[0]).to(dev)
                chol = torch.linalg.cholesky(raw)
            layer_profile[name] = chol.cpu()
            del raw, chol
            torch.cuda.empty_cache()

        profiling_mat[i] = layer_profile
        layers[i] = layer.cpu()
        inps = outs.clone()
        torch.cuda.empty_cache()

    return profiling_mat


# ---------------------------------------------------------------------------
# Whitened SVD compression with per-projection rank override
# ---------------------------------------------------------------------------
@torch.no_grad()
def whitened_svd_compress(model, profiling_mat, ranks_dict, dev):
    """
    Apply whitened SVD compression with per-projection rank control.
    ranks_dict: {(layer_idx, proj_name): rank}
    """
    layers = model.model.layers
    print("Applying whitened SVD compression...")
    for i in tqdm(range(len(layers))):
        layer = layers[i]
        subset = find_layers(layer)
        for name in subset:
            proj = name.split(".")[-1]
            key = (i, proj)
            if key not in ranks_dict:
                continue
            rank = ranks_dict[key]

            W = subset[name].weight.data.float().to(dev)
            scaling = profiling_mat[i][name].to(dev).float()
            try:
                scaling_inv = torch.linalg.inv(scaling)
            except Exception:
                scaling += 1e-6 * torch.eye(scaling.shape[0]).to(dev)
                scaling_inv = torch.linalg.inv(scaling)

            W_scale = W @ scaling
            U, S, Vt = torch.linalg.svd(W_scale, full_matrices=False)

            U_trunc = U[:, :rank]
            S_trunc = S[:rank]
            Vt_trunc = Vt[:rank, :] @ scaling_inv

            sqrtS = torch.diag(torch.sqrt(S_trunc))
            svd_u = (U_trunc @ sqrtS).half()  # (out_features, rank)
            svd_v = (sqrtS @ Vt_trunc).half()  # (rank, in_features)

            # Replace with two-layer factorization
            has_bias = subset[name].bias is not None
            in_f = subset[name].in_features
            out_f = subset[name].out_features

            v_proj = nn.Linear(in_f, rank, bias=False).to(W.device)
            u_proj = nn.Linear(rank, out_f, bias=has_bias).to(W.device)
            v_proj.weight.data = svd_v.contiguous()
            u_proj.weight.data = svd_u.contiguous()
            if has_bias:
                u_proj.bias.data = subset[name].bias.data.clone()

            # Create wrapper module
            wrapper = LowRankWrapper(v_proj, u_proj)

            # Replace in model
            parts = name.split(".")
            parent = layer
            for part in parts[:-1]:
                parent = getattr(parent, part)
            setattr(parent, parts[-1], wrapper)

            del W, scaling, scaling_inv, W_scale, U, S, Vt
            torch.cuda.empty_cache()


class LowRankWrapper(nn.Module):
    def __init__(self, v_proj, u_proj):
        super().__init__()
        self.v_proj = v_proj
        self.u_proj = u_proj

    def forward(self, x):
        return self.u_proj(self.v_proj(x))

    @property
    def weight(self):
        return self.u_proj.weight

    @property
    def in_features(self):
        return self.v_proj.in_features

    @property
    def out_features(self):
        return self.u_proj.out_features


# ---------------------------------------------------------------------------
# PPL Evaluation (using SVD-LLM's evaluator)
# ---------------------------------------------------------------------------
@torch.no_grad()
def eval_ppl(model, tokenizer, dev, seq_len=2048, batch_size=4):
    """Evaluate WikiText-2 PPL."""
    model.to(dev)
    model.eval()
    test_loader = get_test_data("wikitext2", tokenizer, seq_len=seq_len, batch_size=batch_size)
    nlls = []
    for batch in tqdm(test_loader, desc="PPL eval"):
        batch = batch.to(dev)
        output = model(batch, use_cache=False)
        lm_logits = output.logits
        if torch.isfinite(lm_logits).all():
            shift_logits = lm_logits[:, :-1, :].contiguous()
            shift_labels = batch[:, 1:].contiguous()
            loss_fct = nn.CrossEntropyLoss(reduction="none")
            loss = loss_fct(
                shift_logits.reshape(-1, shift_logits.size(-1)),
                shift_labels.view(-1)
            )
            nlls.append(loss)
        else:
            print("  Warning: non-finite logits detected, skipping batch")
    if not nlls:
        return float("nan")
    ppl = np.exp(torch.cat(nlls, dim=-1).mean().item())
    model.cpu()
    torch.cuda.empty_cache()
    return ppl


# ---------------------------------------------------------------------------
# Accuracy Evaluation
# ---------------------------------------------------------------------------
@torch.no_grad()
def eval_accuracy(model, tokenizer, dev, tasks="piqa,hellaswag", limit=200):
    """Zero-shot accuracy evaluation using log-likelihood scoring."""
    from datasets import load_dataset

    model.to(dev)
    model.eval()
    accs = {}

    task_list = tasks.split(",")
    for task_name in task_list:
        try:
            correct = 0
            total = 0

            if task_name == "piqa":
                ds = load_dataset("piqa", split="validation")
                if limit:
                    ds = ds.select(range(min(limit, len(ds))))
                for ex in tqdm(ds, desc=f"  {task_name}"):
                    goal = ex["goal"]
                    choices = [ex["sol1"], ex["sol2"]]
                    label = ex["label"]
                    scores = []
                    for c in choices:
                        text = f"{goal} {c}"
                        ids = tokenizer(text, return_tensors="pt").input_ids.to(dev)
                        out = model(ids, use_cache=False)
                        logits = out.logits[0, :-1]
                        targets = ids[0, 1:]
                        log_probs = torch.nn.functional.log_softmax(logits, dim=-1)
                        score = log_probs.gather(1, targets.unsqueeze(1)).sum().item()
                        scores.append(score)
                    pred = scores.index(max(scores))
                    if pred == label:
                        correct += 1
                    total += 1

            elif task_name == "hellaswag":
                ds = load_dataset("Rowan/hellaswag", split="validation")
                if limit:
                    ds = ds.select(range(min(limit, len(ds))))
                for ex in tqdm(ds, desc=f"  {task_name}"):
                    ctx = ex["ctx"]
                    choices = ex["endings"]
                    label = int(ex["label"])
                    scores = []
                    for c in choices:
                        text = f"{ctx} {c}"
                        ids = tokenizer(text, return_tensors="pt").input_ids.to(dev)
                        # Score only the completion part
                        ctx_ids = tokenizer(ctx, return_tensors="pt").input_ids
                        ctx_len = ctx_ids.shape[1]
                        out = model(ids, use_cache=False)
                        logits = out.logits[0, ctx_len-1:-1]
                        targets = ids[0, ctx_len:]
                        if targets.numel() == 0:
                            scores.append(float("-inf"))
                            continue
                        log_probs = torch.nn.functional.log_softmax(logits, dim=-1)
                        score = log_probs.gather(1, targets.unsqueeze(1)).mean().item()
                        scores.append(score)
                    pred = scores.index(max(scores))
                    if pred == label:
                        correct += 1
                    total += 1
            else:
                print(f"  Unknown task: {task_name}, skipping")
                continue

            acc = correct / total if total > 0 else 0
            accs[task_name] = round(acc, 4)
            print(f"  {task_name}: {acc:.4f} ({correct}/{total})")
        except Exception as e:
            import traceback
            print(f"  {task_name} eval failed: {type(e).__name__}: {e}")
            traceback.print_exc()

    model.cpu()
    torch.cuda.empty_cache()
    return accs


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------
def generate_plots(results, ranks_dict, output_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir = output_dir / "plots"
    plot_dir.mkdir(exist_ok=True)

    strats = [r["strategy"] for r in results if r["strategy"] != "baseline"]
    ppls = [r["ppl"] for r in results if r["strategy"] != "baseline"]
    aligns = [r["pct_aligned"] for r in results if r["strategy"] != "baseline"]

    baseline_ppl = next((r["ppl"] for r in results if r["strategy"] == "baseline"), None)

    colors = {"svdllm": "#e74c3c", "aligned_8": "#3498db", "gac_dp": "#2ecc71"}

    # PPL comparison
    fig, ax = plt.subplots(figsize=(8, 5))
    c = [colors.get(s, "#999") for s in strats]
    bars = ax.bar(strats, ppls, color=c, edgecolor="black", linewidth=0.8)
    if baseline_ppl:
        ax.axhline(y=baseline_ppl, color="gray", linestyle="--", label=f"Baseline: {baseline_ppl:.2f}")
        ax.legend()
    for bar, p in zip(bars, ppls):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                f"{p:.2f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.set_ylabel("Perplexity (WikiText-2)")
    ax.set_title("SVD-LLM Compression: PPL by Alignment Strategy")
    plt.tight_layout()
    plt.savefig(plot_dir / "ppl_comparison.png", dpi=150)
    plt.close()

    # Alignment bar
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(strats, aligns, color=c, edgecolor="black", linewidth=0.8)
    for bar, a in zip(bars, aligns):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f"{a:.0f}%", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.set_ylabel("% Projections Aligned (mod 8)")
    ax.set_title("Dimension Alignment Comparison")
    ax.set_ylim(0, 110)
    plt.tight_layout()
    plt.savefig(plot_dir / "alignment_comparison.png", dpi=150)
    plt.close()

    # Rank heatmaps
    for sname, ranks in ranks_dict.items():
        fig, ax = plt.subplots(figsize=(12, 5))
        mat = np.zeros((len(ALL_PROJS), NUM_LAYERS))
        for j, proj in enumerate(ALL_PROJS):
            for l in range(NUM_LAYERS):
                mat[j, l] = ranks.get((l, proj), 0)
        im = ax.imshow(mat, aspect="auto", cmap="viridis")
        ax.set_xticks(range(0, NUM_LAYERS, 4))
        ax.set_yticks(range(len(ALL_PROJS)))
        ax.set_yticklabels(ALL_PROJS)
        ax.set_xlabel("Layer")
        ax.set_title(f"Rank Allocation: {sname}")
        plt.colorbar(im, ax=ax, label="Rank")
        plt.tight_layout()
        plt.savefig(plot_dir / f"ranks_{sname}.png", dpi=150)
        plt.close()

    # Combined: PPL + Accuracy
    has_acc = any("accuracy" in r and r["accuracy"] for r in results)
    if has_acc:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        ax1.bar(strats, ppls, color=c, edgecolor="black")
        if baseline_ppl:
            ax1.axhline(y=baseline_ppl, color="gray", linestyle="--", label="Baseline")
            ax1.legend()
        ax1.set_ylabel("Perplexity")
        ax1.set_title("PPL")

        avg_accs = []
        for r in results:
            if r["strategy"] == "baseline":
                continue
            accs = r.get("accuracy", {})
            avg_accs.append(np.mean(list(accs.values())) * 100 if accs else 0)
        ax2.bar(strats, avg_accs, color=c, edgecolor="black")
        baseline_acc = next((r.get("accuracy", {}) for r in results if r["strategy"] == "baseline"), {})
        if baseline_acc:
            ba = np.mean(list(baseline_acc.values())) * 100
            ax2.axhline(y=ba, color="gray", linestyle="--", label=f"Baseline: {ba:.1f}%")
            ax2.legend()
        ax2.set_ylabel("Accuracy (%)")
        ax2.set_title("Average Accuracy")
        plt.tight_layout()
        plt.savefig(plot_dir / "combined_results.png", dpi=150)
        plt.close()

    print(f"  Plots saved to {plot_dir}/")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ratio", type=float, default=0.7,
                        help="Keep ratio (0.7 = keep 70%%)")
    parser.add_argument("--output", type=str, default="results/svdllm_experiment")
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--eval-accuracy", action="store_true")
    parser.add_argument("--accuracy-tasks", type=str, default="piqa,hellaswag")
    parser.add_argument("--accuracy-limit", type=int, default=200)
    parser.add_argument("--whitening-nsamples", type=int, default=256)
    parser.add_argument("--profiling-path", type=str, default=None,
                        help="Path to pre-computed profiling matrices")
    parser.add_argument("--strategies", type=str, default=None,
                        help="Comma-separated list of strategies to run (default: all)")
    args = parser.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    dev = torch.device(args.device)

    print("=" * 70)
    print("SVD-LLM + GAC Alignment Experiment")
    print(f"Model: {MODEL_ID}")
    print(f"Keep ratio: {args.ratio}")
    print(f"Device: {dev}")
    print("=" * 70)

    # ---------------------------------------------------------------
    # Step 1: Load model
    # ---------------------------------------------------------------
    print("\n[Step 1] Loading model...")
    model, tokenizer = load_model(MODEL_ID)
    model.eval()

    # ---------------------------------------------------------------
    # Step 2: Compute Fisher proxy
    # ---------------------------------------------------------------
    print("\n[Step 2] Computing Fisher scores...")
    fisher = compute_fisher_proxy(model)
    fisher_list = [{"layer": k[0], "proj": k[1], "fisher": v}
                   for k, v in sorted(fisher.items())]
    with open(out_dir / "fisher_scores.json", "w") as f:
        json.dump(fisher_list, f, indent=2)
    print(f"  Fisher scores for {len(fisher)} projections")

    # ---------------------------------------------------------------
    # Step 3: Compute SVD-LLM ranks and create strategies
    # ---------------------------------------------------------------
    print("\n[Step 3] Computing rank allocations...")
    svdllm_ranks = compute_all_svdllm_ranks(args.ratio)
    budget = param_cost(svdllm_ranks)

    attn_r = svdllm_ranks[(0, "q_proj")]
    mlp_r = svdllm_ranks[(0, "gate_proj")]
    print(f"  SVD-LLM ranks: attn={attn_r} (mod8={attn_r%8}), MLP={mlp_r} (mod8={mlp_r%8})")
    print(f"  Total budget: {budget:,}")

    strategies = {
        "svdllm": svdllm_ranks,
        "aligned_8": strategy_round_to_n(svdllm_ranks, fisher, budget, 8),
        "gac_dp": strategy_gac_dp(svdllm_ranks, fisher, budget, align=8, search_radius=3),
    }

    print(f"\n{'Strategy':<12} {'Budget':>14} {'Aligned/8':>10} {'Misaligned':>10}")
    print("-" * 50)
    for name, ranks in strategies.items():
        b = param_cost(ranks)
        n_aligned = sum(1 for r in ranks.values() if r % 8 == 0)
        n_total = len(ranks)
        print(f"{name:<12} {b:>14,} {n_aligned:>6}/{n_total}   {n_total - n_aligned:>6}")

    # Save rank allocations
    for name, ranks in strategies.items():
        data = [{"layer": k[0], "proj": k[1], "rank": v}
                for k, v in sorted(ranks.items())]
        with open(out_dir / f"ranks_{name}.json", "w") as f:
            json.dump(data, f, indent=2)

    # ---------------------------------------------------------------
    # Step 4: Compute profiling matrices (whitening)
    # ---------------------------------------------------------------
    print("\n[Step 4] Computing whitening matrices...")
    if args.profiling_path and os.path.exists(args.profiling_path):
        print(f"  Loading from {args.profiling_path}")
        profiling_mat = torch.load(args.profiling_path, weights_only=False)
    else:
        t0 = time.time()
        calib_data = get_calib_train_data(
            "wikitext2", tokenizer, args.whitening_nsamples, seqlen=2048
        )
        profiling_mat = compute_profiling(model, MODEL_ID, calib_data, dev)
        prof_path = out_dir / "profiling_mat.pt"
        torch.save(profiling_mat, prof_path)
        print(f"  Profiling done in {time.time()-t0:.0f}s, saved to {prof_path}")

    # ---------------------------------------------------------------
    # Step 5: Evaluate baseline
    # ---------------------------------------------------------------
    all_results = []
    print("\n[Step 5] Evaluating baseline...")
    # Free profiling_mat during baseline eval to save RAM
    prof_path = out_dir / "profiling_mat.pt"
    del profiling_mat
    import gc; gc.collect()

    t0 = time.time()
    baseline_ppl = eval_ppl(model, tokenizer, dev)
    print(f"  Baseline PPL: {baseline_ppl:.2f} ({time.time()-t0:.0f}s)")

    baseline_result = {"strategy": "baseline", "ppl": baseline_ppl, "pct_aligned": 100.0}
    if args.eval_accuracy:
        baseline_acc = eval_accuracy(model, tokenizer, dev,
                                      args.accuracy_tasks, args.accuracy_limit)
        baseline_result["accuracy"] = baseline_acc
        print(f"  Baseline accuracy: {baseline_acc}")
    all_results.append(baseline_result)

    del model
    gc.collect()
    torch.cuda.empty_cache()

    # Reload profiling matrices for compression steps
    print("  Reloading profiling matrices...")
    profiling_mat = torch.load(prof_path, weights_only=False)

    # ---------------------------------------------------------------
    # Step 6: For each strategy, compress and evaluate
    # ---------------------------------------------------------------
    # Filter strategies if specified
    if args.strategies:
        strat_filter = set(args.strategies.split(","))
        strategies = {k: v for k, v in strategies.items() if k in strat_filter}

    for strat_name, ranks in strategies.items():
        print(f"\n[Step 6] Strategy: {strat_name}")
        t0 = time.time()

        # Reload fresh model
        model, _ = load_model(MODEL_ID)
        model.eval()

        # Compress with whitened SVD
        whitened_svd_compress(model, profiling_mat, ranks, dev)

        print(f"  Compression done in {time.time()-t0:.0f}s")

        # PPL
        t1 = time.time()
        ppl = eval_ppl(model, tokenizer, dev)
        print(f"  PPL: {ppl:.2f} ({time.time()-t1:.0f}s)")

        n_aligned = sum(1 for r in ranks.values() if r % 8 == 0)
        pct = 100.0 * n_aligned / len(ranks)

        result = {
            "strategy": strat_name,
            "ppl": ppl,
            "pct_aligned": pct,
            "budget": param_cost(ranks),
            "ranks_summary": {
                "attn": sorted(set(ranks[(l, p)] for l in range(NUM_LAYERS) for p in ATTN_PROJS)),
                "mlp": sorted(set(ranks[(l, p)] for l in range(NUM_LAYERS) for p in MLP_PROJS)),
            },
        }

        if args.eval_accuracy:
            accs = eval_accuracy(model, tokenizer, dev,
                                  args.accuracy_tasks, args.accuracy_limit)
            result["accuracy"] = accs
            print(f"  Accuracy: {accs}")

        all_results.append(result)
        del model
        torch.cuda.empty_cache()

    # ---------------------------------------------------------------
    # Step 7: Summary
    # ---------------------------------------------------------------
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    header = f"{'Strategy':<12} {'PPL':>8} {'Aligned%':>9} {'Budget':>14}"
    if args.eval_accuracy:
        header += f"  {'Avg Acc':>8}"
    print(header)
    print("-" * len(header))
    for r in all_results:
        line = f"{r['strategy']:<12} {r['ppl']:>8.2f} {r['pct_aligned']:>8.0f}% {r.get('budget', 0):>14,}"
        if args.eval_accuracy:
            accs = r.get("accuracy", {})
            avg = np.mean(list(accs.values())) * 100 if accs else 0
            line += f"  {avg:>7.1f}%"
        print(line)

    # Save
    with open(out_dir / "results.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {out_dir / 'results.json'}")

    # Plots
    print("\n[Step 7] Generating plots...")
    generate_plots(all_results, strategies, out_dir)
    print("\nExperiment complete!")


if __name__ == "__main__":
    main()
