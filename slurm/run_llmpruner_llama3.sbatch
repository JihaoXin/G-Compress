#!/bin/bash
#SBATCH --job-name=llmprune_l3
#SBATCH --output=slurm_logs/llmprune_l3_%j.out
#SBATCH --error=slurm_logs/llmprune_l3_%j.err
#SBATCH --gres=gpu:a100:1
#SBATCH --constraint=gpu_a100_80gb
#SBATCH --cpus-per-task=8
#SBATCH --mem=100GB
#SBATCH --time=12:00:00
#SBATCH --qos=spot

set -eo pipefail
mkdir -p slurm_logs

# Use llama env python directly (avoids conda activate issues in batch)
PYTHON=/home/xinj/miniforge3/envs/llama/bin/python
export LD_LIBRARY_PATH="/home/xinj/miniforge3/envs/llama/lib:$LD_LIBRARY_PATH"
export HF_DATASETS_TRUST_REMOTE_CODE=1
cd $SLURM_SUBMIT_DIR

echo "============================================="
echo "LLM-Pruner + GAC on Llama-3-8B"
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

# Run LLM-Pruner experiment on Llama-3-8B
# Strategies: baseline, pruned (no rounding), pruned_r8 (round_to=8)
# Pruning ratio: 0.25 (remove 25% channels)
$PYTHON scripts/llmpruner_gac_experiment.py \
    --pruning-ratio 0.25 \
    --output results/llmpruner_llama3 \
    --device cuda \
    --eval-accuracy \
    --accuracy-tasks piqa,hellaswag \
    --accuracy-limit 200 \
    --eval-latency \
    --seq-lens 128,256,512,1024 \
    --prefill-warmup 5 \
    --prefill-repeats 30 \
    2>&1

echo ""
echo "============================================="
echo "LLM-Pruner Experiment Complete: $(date)"
echo "============================================="
