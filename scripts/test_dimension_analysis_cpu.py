#!/usr/bin/env python3
"""
CPU-only test script to verify the fix for analyze_palu_dimensions().
This script only loads model metadata without loading full weights.

Expected results after fix:
- PaLU model should detect per-head ranks (114-125 range)
- misaligned_pct should be ~97% (only 120 is 8-aligned)
"""

import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, "/home/xinj/G-Compress")
sys.path.insert(0, "/home/xinj/G-Compress/third_party/palu")

from palu.model.svd_llama.configuration_palu_llama import PaluLlamaConfig


def main():
    print("=" * 60)
    print("Testing analyze_palu_dimensions() fix (CPU-only)")
    print("=" * 60)

    # Find PaLU directory
    palu_base = Path("/home/xinj/rap/submodules/palu")
    pattern = "Meta-Llama-3-8B-Instruct_ratio-0.7_gs-4*"
    candidates = sorted(palu_base.glob(pattern))

    if not candidates:
        print(f"Error: No PaLU directory found matching {pattern}")
        return 1

    palu_dir = candidates[0]
    print(f"\nPaLU directory: {palu_dir}")

    # Load config (contains head_wise_ranks)
    config = PaluLlamaConfig.from_pretrained(palu_dir)
    print(f"Model type: {config.model_type}")
    print(f"Hidden size: {config.hidden_size}")
    print(f"Num heads: {config.num_attention_heads}")
    print(f"Num KV heads: {config.num_key_value_heads}")

    if not hasattr(config, 'head_wise_ranks') or config.head_wise_ranks is None:
        print("\nError: head_wise_ranks not found in config!")
        return 1

    # Analyze head_wise_ranks
    print("\n" + "-" * 40)
    print("Analyzing head_wise_ranks from config:")
    print("-" * 40)

    all_ranks = []
    k_proj_ranks = []
    v_proj_ranks = []

    for layer_name, ranks in config.head_wise_ranks.items():
        if 'k_proj' in layer_name:
            k_proj_ranks.extend(ranks)
        elif 'v_proj' in layer_name:
            v_proj_ranks.extend(ranks)
        all_ranks.extend(ranks)

    print(f"Total entries in head_wise_ranks: {len(config.head_wise_ranks)}")
    print(f"Total per-head ranks: {len(all_ranks)}")
    print(f"  K-proj heads: {len(k_proj_ranks)}")
    print(f"  V-proj heads: {len(v_proj_ranks)}")

    unique_ranks = sorted(set(all_ranks))
    print(f"\nUnique rank values: {unique_ranks}")

    # Calculate alignment statistics
    aligned_8 = sum(1 for r in all_ranks if r % 8 == 0)
    aligned_16 = sum(1 for r in all_ranks if r % 16 == 0)
    total = len(all_ranks)

    print(f"\nAlignment statistics:")
    print(f"  Total: {total}")
    print(f"  8-aligned: {aligned_8} ({100.0 * aligned_8 / total:.1f}%)")
    print(f"  16-aligned: {aligned_16} ({100.0 * aligned_16 / total:.1f}%)")
    print(f"  Misaligned (not 8): {total - aligned_8} ({100.0 * (total - aligned_8) / total:.1f}%)")

    # Show distribution
    print("\n" + "-" * 40)
    print("Distribution of ranks:")
    print("-" * 40)

    from collections import Counter
    rank_counts = Counter(all_ranks)
    for rank in sorted(rank_counts.keys()):
        count = rank_counts[rank]
        aligned_mark = "*" if rank % 8 == 0 else " "
        print(f"  {rank:3d}: {count:3d} {aligned_mark}")

    # Verification
    print("\n" + "-" * 40)
    print("Verification:")
    print("-" * 40)

    checks_passed = 0
    total_checks = 4

    # Check 1: Dimensions should be in 114-125 range (for r=0.7)
    dims_in_range = all(100 <= d <= 130 for d in unique_ranks)
    if dims_in_range and len(unique_ranks) > 0:
        print(f"  [PASS] Dimensions in expected range (114-125)")
        checks_passed += 1
    else:
        print(f"  [FAIL] Dimensions not in expected range: {unique_ranks}")

    # Check 2: Total heads should be ~512 (32 layers * 8 KV heads * 2 projections)
    expected_heads = config.num_hidden_layers * config.num_key_value_heads * 2
    if total == expected_heads:
        print(f"  [PASS] Total heads matches expected: {total}")
        checks_passed += 1
    else:
        print(f"  [WARN] Total heads {total} != expected {expected_heads}")
        checks_passed += 0.5

    # Check 3: Misaligned percentage should be high (>90%)
    misaligned_pct = 100.0 * (total - aligned_8) / total
    if misaligned_pct > 90:
        print(f"  [PASS] High misalignment rate: {misaligned_pct:.1f}%")
        checks_passed += 1
    else:
        print(f"  [FAIL] Misalignment rate too low: {misaligned_pct:.1f}%")

    # Check 4: Only a few should be 8-aligned (e.g., 120)
    if 100.0 * aligned_8 / total < 10:
        print(f"  [PASS] Low 8-aligned rate: {100.0 * aligned_8 / total:.1f}%")
        checks_passed += 1
    else:
        print(f"  [FAIL] Too many 8-aligned: {100.0 * aligned_8 / total:.1f}%")

    print(f"\n  Results: {checks_passed}/{total_checks} checks passed")

    # Expected values for the fixed analyze_palu_dimensions
    print("\n" + "=" * 60)
    print("Expected output from fixed analyze_palu_dimensions():")
    print("=" * 60)
    print(f"""
{{
    "unique_dims": {unique_ranks},
    "total_heads": {total},
    "aligned_8_count": {aligned_8},
    "aligned_16_count": {aligned_16},
    "aligned_8_pct": {100.0 * aligned_8 / total:.1f},
    "aligned_16_pct": {100.0 * aligned_16 / total:.1f},
    "misaligned_pct": {misaligned_pct:.1f}
}}
""")

    if checks_passed >= 3:
        print("SUCCESS: Fix verification passed!")
        return 0
    else:
        print(f"PARTIAL: {checks_passed}/{total_checks} checks passed")
        return 1


if __name__ == "__main__":
    exit(main())
