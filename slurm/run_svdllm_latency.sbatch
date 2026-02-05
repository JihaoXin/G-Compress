#!/bin/bash
#SBATCH --job-name=svdllm_lat
#SBATCH --output=slurm_logs/svdllm_lat_%j.out
#SBATCH --error=slurm_logs/svdllm_lat_%j.err
#SBATCH --gres=gpu:a100:1
#SBATCH --constraint=gpu_a100_80gb
#SBATCH --cpus-per-task=8
#SBATCH --mem=100GB
#SBATCH --time=06:00:00
#SBATCH --qos=spot

set -eo pipefail
mkdir -p slurm_logs

source ~/.bashrc
mamba activate svdllm
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$LD_LIBRARY_PATH"
cd $SLURM_SUBMIT_DIR

echo "============================================="
echo "SVD-LLM Latency Benchmark"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURMD_NODENAME"
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"
echo "Date: $(date)"
echo "============================================="
echo ""

nvidia-smi
echo ""

python scripts/svdllm_latency_bench.py \
    --ratio 0.7 \
    --output results/svdllm_latency \
    --device cuda \
    --profiling-path results/svdllm_experiment/profiling_mat.pt \
    --gemm-warmup 100 \
    --gemm-repeats 500 \
    --prefill-warmup 5 \
    --prefill-repeats 30 \
    --seq-lens 128,256,512,1024 \
    --batch-tokens 512 \
    2>&1

echo ""
echo "============================================="
echo "Benchmark Complete: $(date)"
echo "============================================="
