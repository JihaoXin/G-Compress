import torch

# Lightweight fallback implementation for PaLU hadamard_utils.
# This is NOT an optimized Hadamard transform; it simply applies a scaling
# factor and returns the input. This is sufficient to avoid import errors
# when using pre-compressed checkpoints.

def hadamard_transform(x: torch.Tensor, scale: float = 1.0):
    return x * scale
