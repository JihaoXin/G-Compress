"""
PaLU helper: locate compressed checkpoint directory and load model/tokenizer.
Uses PaluLlamaConfig/PaluLlamaForCausalLM from third_party/palu.
"""
import glob
from pathlib import Path
from typing import Tuple

import torch
from transformers import AutoTokenizer

from palu.model.svd_llama.configuration_palu_llama import PaluLlamaConfig
from palu.model.svd_llama.modeling_palu_llama import PaluLlamaForCausalLM


def find_palu_dir(
    base: str = "/home/xinj/rap/submodules/palu",
    pattern: str = "Meta-Llama-3-8B-Instruct_ratio-0.7_gs-4*",
) -> Path:
    candidates = sorted(glob.glob(str(Path(base) / pattern)))
    if not candidates:
        raise FileNotFoundError(f"No PaLU ratio directory matching {pattern} under {base}")
    return Path(candidates[0])


def load_palu_model(
    device: str = "cuda",
    torch_dtype: torch.dtype = torch.float16,
) -> Tuple[torch.nn.Module, AutoTokenizer, Path]:
    palu_dir = find_palu_dir()

    # PaLU checkpoint uses custom config/model type `palullama`.
    config = PaluLlamaConfig.from_pretrained(palu_dir)
    model = PaluLlamaForCausalLM.from_pretrained(
        palu_dir,
        config=config,
        torch_dtype=torch_dtype,
        device_map="auto" if device.startswith("cuda") else None,
    )

    # Use baseline tokenizer to avoid tokenizer.json format issues in palu dir.
    baseline_id = "meta-llama/Meta-Llama-3-8B-Instruct"
    tokenizer = AutoTokenizer.from_pretrained(baseline_id, use_fast=True)
    return model, tokenizer, palu_dir
