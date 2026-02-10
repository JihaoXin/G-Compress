#!/usr/bin/env python3
"""
Simplified ASVD script without lm_eval dependency.
Only evaluates PPL, not lm-eval tasks.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from tqdm import tqdm

# Keep ASVD dependencies in third_party, but keep this script in the main repo.
REPO_ROOT = Path(__file__).resolve().parents[2]
ASVD4LLM_DIR = REPO_ROOT / "third_party" / "ASVD4LLM"
if str(ASVD4LLM_DIR) not in sys.path:
    sys.path.insert(0, str(ASVD4LLM_DIR))

from datautils import get_calib_data
from act_aware_utils import calib_input_distribution
from sensitivity_simple import calib_sensitivity_ppl, calib_sensitivity_stable_rank
from binary_search_simple import binary_search_truncation_rank
from evaluate_utils_simple import evaluate_perplexity


def evaluate_ppl_datasets(model, tokenizer, datasets="wikitext2"):
    """Evaluate PPL on specified datasets."""
    from datasets import load_dataset

    results = {}
    for dataset_name in datasets.split(","):
        if dataset_name == "wikitext2":
            data = load_dataset("wikitext", "wikitext-2-raw-v1", split="test")
            text = "\n\n".join(data["text"])
        elif dataset_name == "ptb":
            data = load_dataset("ptb_text_only", "penn_treebank", split="test")
            text = "\n\n".join(data["sentence"])
        else:
            continue

        enc = tokenizer(text, return_tensors="pt")
        seq_len = 2048
        n_samples = enc.input_ids.shape[1] // seq_len

        input_ids = enc.input_ids[:, :n_samples * seq_len].reshape(n_samples, seq_len)
        ppl = evaluate_perplexity(model, input_ids, limit=n_samples)
        results[dataset_name] = ppl
        print(f"  {dataset_name}: {ppl:.2f}")

    return results


def measure_latency(model, seq_len=512, n_warmup=5, n_measure=20):
    """Measure prefill latency with CUDA events."""
    device = next(model.parameters()).device
    input_ids = torch.randint(1, 1000, (1, seq_len), device=device)

    for _ in range(n_warmup):
        with torch.no_grad():
            model(input_ids)

    torch.cuda.synchronize()
    latencies = []

    for _ in range(n_measure):
        start = torch.cuda.Event(enable_timing=True)
        end = torch.cuda.Event(enable_timing=True)

        start.record()
        with torch.no_grad():
            model(input_ids)
        end.record()

        torch.cuda.synchronize()
        latencies.append(start.elapsed_time(end))

    return {
        "mean_ms": np.mean(latencies),
        "std_ms": np.std(latencies),
    }


def main(args):
    # Set random seed
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.backends.cudnn.deterministic = True

    print("=" * 70)
    print("ASVD Compression (Simplified)")
    print(f"Model: {args.model_id}")
    print(f"Target param ratio: {args.param_ratio_target}")
    print(f"Rank alignment: {args.rank_align}")
    print(f"Sensitivity metric: {args.sensitivity_metric}")
    print("=" * 70)

    # Load model
    tokenizer = AutoTokenizer.from_pretrained(args.model_id, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model_id, device_map="auto", torch_dtype=torch.float16, trust_remote_code=True
    )

    if args.raw_model:
        # Just evaluate the raw model
        print("\n[Evaluating raw model]")
        ppl_results = evaluate_ppl_datasets(model, tokenizer, args.eval_ppl)
        latency = measure_latency(model, args.seq_len)
        print(f"  Latency: {latency['mean_ms']:.1f}ms")
        return

    # Get calibration data
    calib_loader = get_calib_data(
        args.calib_dataset, tokenizer, args.model_id,
        args.n_calib_samples, seed=args.seed, use_bos=args.use_bos
    )

    # Calibrate activation distribution
    print("\n[Step 1] Calibrating activation distribution...")
    if "abs" in args.scaling_method:
        calib_input_distribution(model, calib_loader, args.scaling_method, args.use_cache)

    # Compute sensitivity
    print("\n[Step 2] Computing sensitivity...")
    if args.sensitivity_metric == "ppl":
        sensitivity = calib_sensitivity_ppl(model, calib_loader, args, args.use_cache)
    else:
        sensitivity = calib_sensitivity_stable_rank(model, calib_loader, args, args.use_cache)

    # Apply compression
    print("\n[Step 3] Applying SVD compression...")
    binary_search_truncation_rank(model, sensitivity, calib_loader, args)

    # Evaluate
    print("\n[Step 4] Evaluating compressed model...")
    ppl_results = evaluate_ppl_datasets(model, tokenizer, args.eval_ppl)
    latency = measure_latency(model, args.seq_len)
    print(f"  Latency: {latency['mean_ms']:.1f}ms")

    # Save results
    if args.output:
        os.makedirs(args.output, exist_ok=True)
        results = {
            "model_id": args.model_id,
            "param_ratio_target": args.param_ratio_target,
            "rank_align": args.rank_align,
            "sensitivity_metric": args.sensitivity_metric,
            "ppl": ppl_results,
            "latency": latency,
        }
        with open(os.path.join(args.output, "results.json"), "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to {args.output}/results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_id", type=str, default="meta-llama/Meta-Llama-3-8B")
    parser.add_argument("--ppl_target", type=float, default=-1)
    parser.add_argument("--param_ratio_target", type=float, default=0.85)
    parser.add_argument("--act_aware", action="store_true", default=True)
    parser.add_argument("--alpha", type=float, default=0.5)
    parser.add_argument("--n_calib_samples", type=int, default=32)
    parser.add_argument("--calib_dataset", type=str, default="wikitext2")
    parser.add_argument("--scaling_method", type=str, default="abs_mean")
    parser.add_argument("--sensitivity_metric", type=str, default="ppl", choices=["ppl", "stable_rank"])
    parser.add_argument("--use_cache", action="store_true", default=True)
    parser.add_argument("--sigma_fuse", type=str, default="UV")
    parser.add_argument("--rank_align", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--raw_model", action="store_true")
    parser.add_argument("--use_bos", action="store_true")
    parser.add_argument("--eval_ppl", type=str, default="wikitext2")
    parser.add_argument("--seq_len", type=int, default=512)
    parser.add_argument("--output", type=str, default="")
    parser.add_argument("--compress_kv_cache", action="store_true")
    parser.add_argument("--kv_cache_ratio_target", type=float, default=-1)
    args = parser.parse_args()

    main(args)
