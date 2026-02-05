#!/bin/bash
#SBATCH --job-name=svdllm_l3
#SBATCH --output=slurm_logs/svdllm_l3_%j.out
#SBATCH --error=slurm_logs/svdllm_l3_%j.err
#SBATCH --gres=gpu:a100:1
#SBATCH --constraint=gpu_a100_80gb
#SBATCH --cpus-per-task=8
#SBATCH --mem=200GB
#SBATCH --time=12:00:00
#SBATCH --qos=spot

set -eo pipefail
mkdir -p slurm_logs

# Use llama env python directly (avoids conda activate issues in batch)
PYTHON=/home/xinj/miniforge3/envs/llama/bin/python
export LD_LIBRARY_PATH="/home/xinj/miniforge3/envs/llama/lib:$LD_LIBRARY_PATH"
cd $SLURM_SUBMIT_DIR

echo "============================================="
echo "SVD-LLM + GAC on Llama-3-8B"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURMD_NODENAME"
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"
echo "Date: $(date)"
echo "Python: $($PYTHON --version)"
echo "Transformers: $($PYTHON -c 'import transformers; print(transformers.__version__)')"
echo "============================================="
echo ""
nvidia-smi
echo ""

# Run SVD-LLM experiment on Llama-3-8B
# Model: Meta-Llama-3-8B, Keep ratio: 0.7
# Strategies: svdllm (unaligned), aligned_8, gac_dp
$PYTHON scripts/svdllm_gac_experiment.py \
    --ratio 0.7 \
    --output results/svdllm_llama3 \
    --device cuda \
    --eval-accuracy \
    --accuracy-tasks piqa,hellaswag \
    --accuracy-limit 200 \
    --whitening-nsamples 256 \
    --profiling-path results/svdllm_llama3/profiling_mat.pt \
    2>&1

echo ""
echo "============================================="
echo "SVD-LLM Experiment Complete: $(date)"
echo "============================================="
echo ""

# Run latency benchmark
echo "Starting latency benchmark..."
$PYTHON scripts/svdllm_latency_bench.py \
    --ratio 0.7 \
    --output results/svdllm_llama3_latency \
    --device cuda \
    --profiling-path results/svdllm_llama3/profiling_mat.pt \
    --gemm-warmup 100 \
    --gemm-repeats 500 \
    --prefill-warmup 5 \
    --prefill-repeats 30 \
    --seq-lens 128,256,512,1024 \
    2>&1

echo ""
echo "============================================="
echo "All SVD-LLM Jobs Complete: $(date)"
echo "============================================="
