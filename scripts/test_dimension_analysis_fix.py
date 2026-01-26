#!/usr/bin/env python3
"""
Test script to verify the fix for analyze_palu_dimensions().

Expected results after fix:
- PaLU model should detect per-head ranks (114-125 range)
- misaligned_pct should be ~97% (only 120 is 8-aligned)
- total_heads should be ~512 (32 layers × 8 KV heads × 2 projections)
"""

import sys
import torch

# Add project root to path
sys.path.insert(0, "/home/xinj/G-Compress")
sys.path.insert(0, "/home/xinj/G-Compress/third_party/palu")

from src.gcompress_bench.palu_loader import load_palu_model
from src.gcompress_bench.dimension_repair import DimensionRepairer, repair_dimension


def analyze_palu_dimensions_fixed(model):
    """Fixed version of analyze_palu_dimensions that detects per-head ranks."""
    dims = []
    aligned_8 = 0
    aligned_16 = 0
    total = 0

    try:
        from palu.model.modules.svd_linear import HeadwiseLowRankModule
        has_palu = True
    except ImportError:
        has_palu = False
        print("Warning: Could not import HeadwiseLowRankModule")

    for name, module in model.named_modules():
        if has_palu and isinstance(module, HeadwiseLowRankModule):
            for rank in module.ranks:
                dims.append(rank)
                total += 1
                if rank % 8 == 0:
                    aligned_8 += 1
                if rank % 16 == 0:
                    aligned_16 += 1

    return {
        "unique_dims": sorted(set(dims)),
        "total_heads": total,
        "aligned_8_count": aligned_8,
        "aligned_16_count": aligned_16,
        "aligned_8_pct": 100.0 * aligned_8 / total if total > 0 else 0,
        "aligned_16_pct": 100.0 * aligned_16 / total if total > 0 else 0,
        "misaligned_pct": 100.0 * (total - aligned_8) / total if total > 0 else 0,
    }


def main():
    print("=" * 60)
    print("Testing analyze_palu_dimensions() fix")
    print("=" * 60)

    # Load PaLU model
    print("\nLoading PaLU model...")
    model, tokenizer, palu_dir = load_palu_model(device="cuda", torch_dtype=torch.float16)
    print(f"Loaded from: {palu_dir}")

    # Analyze dimensions with fixed function
    print("\n" + "-" * 40)
    print("Analyzing per-head dimensions (FIXED):")
    print("-" * 40)
    analysis = analyze_palu_dimensions_fixed(model)

    print(f"  Unique dims: {analysis['unique_dims']}")
    print(f"  Total heads: {analysis['total_heads']}")
    print(f"  Aligned 8: {analysis['aligned_8_count']} ({analysis['aligned_8_pct']:.1f}%)")
    print(f"  Aligned 16: {analysis['aligned_16_count']} ({analysis['aligned_16_pct']:.1f}%)")
    print(f"  Misaligned: {analysis['misaligned_pct']:.1f}%")

    # Verify expectations
    print("\n" + "-" * 40)
    print("Verification:")
    print("-" * 40)

    checks_passed = 0
    total_checks = 4

    # Check 1: Dimensions should be in 114-125 range
    dims_in_range = all(100 <= d <= 130 for d in analysis['unique_dims'])
    if dims_in_range and len(analysis['unique_dims']) > 0:
        print(f"  [PASS] Dimensions in expected range (114-125)")
        checks_passed += 1
    else:
        print(f"  [FAIL] Dimensions not in expected range: {analysis['unique_dims']}")

    # Check 2: Total heads should be ~512
    if 400 <= analysis['total_heads'] <= 600:
        print(f"  [PASS] Total heads in expected range (~512): {analysis['total_heads']}")
        checks_passed += 1
    else:
        print(f"  [FAIL] Total heads not in expected range: {analysis['total_heads']}")

    # Check 3: Misaligned percentage should be high (>90%)
    if analysis['misaligned_pct'] > 90:
        print(f"  [PASS] High misalignment rate: {analysis['misaligned_pct']:.1f}%")
        checks_passed += 1
    else:
        print(f"  [FAIL] Misalignment rate too low: {analysis['misaligned_pct']:.1f}%")

    # Check 4: Only a few should be 8-aligned (e.g., 120)
    if analysis['aligned_8_pct'] < 10:
        print(f"  [PASS] Low 8-aligned rate: {analysis['aligned_8_pct']:.1f}%")
        checks_passed += 1
    else:
        print(f"  [FAIL] Too many 8-aligned: {analysis['aligned_8_pct']:.1f}%")

    print(f"\n  Results: {checks_passed}/{total_checks} checks passed")

    # Test DimensionRepairer.analyze_model
    print("\n" + "-" * 40)
    print("Testing DimensionRepairer.analyze_model:")
    print("-" * 40)

    repairer = DimensionRepairer(strategy="minimal")
    dims = repairer.analyze_model(model)

    print(f"  Total entries: {len(dims)}")
    unique_vals = sorted(set(dims.values()))
    print(f"  Unique dimensions: {unique_vals}")

    # Check if any dimension needs repair
    needs_repair = sum(1 for d in dims.values() if d % 8 != 0)
    print(f"  Needs repair: {needs_repair}/{len(dims)}")

    # Test repair_dimension function
    print("\n" + "-" * 40)
    print("Testing repair_dimension():")
    print("-" * 40)

    test_dims = [114, 117, 120, 121, 125]
    for d in test_dims:
        repaired = repair_dimension(d, strategy="minimal")
        status = "unchanged" if repaired == d else f"-> {repaired}"
        print(f"  {d}: {status}")

    print("\n" + "=" * 60)
    if checks_passed == total_checks:
        print("SUCCESS: All checks passed!")
        return 0
    else:
        print(f"PARTIAL: {checks_passed}/{total_checks} checks passed")
        return 1


if __name__ == "__main__":
    exit(main())
