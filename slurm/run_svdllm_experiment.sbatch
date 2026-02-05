#!/bin/bash
#SBATCH --job-name=svdllm_gac
#SBATCH --output=slurm_logs/svdllm_gac_%j.out
#SBATCH --error=slurm_logs/svdllm_gac_%j.err
#SBATCH --gres=gpu:a100:1
#SBATCH --constraint=gpu_a100_80gb
#SBATCH --cpus-per-task=8
#SBATCH --mem=100GB
#SBATCH --time=12:00:00
#SBATCH --qos=spot

set -eo pipefail
mkdir -p slurm_logs

source ~/.bashrc
mamba activate svdllm
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$LD_LIBRARY_PATH"
cd $SLURM_SUBMIT_DIR

echo "============================================="
echo "SVD-LLM + GAC Alignment Experiment"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURMD_NODENAME"
echo "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)"
echo "Date: $(date)"
echo "Conda env: $CONDA_DEFAULT_ENV"
echo "Python: $(python --version)"
echo "Transformers: $(python -c 'import transformers; print(transformers.__version__)')"
echo "lm-eval: $(python -c 'import lm_eval; print(getattr(lm_eval, "__version__", "0.4.x"))' 2>/dev/null || echo 'unknown')"
echo "============================================="
echo ""

nvidia-smi
echo ""

# Run experiment: SVD-LLM (whitening) + 3 strategies
# Model: Llama-2-7B, Keep ratio: 0.7
# Reuse cached profiling matrices from previous run
python scripts/svdllm_gac_experiment.py \
    --ratio 0.7 \
    --output results/svdllm_experiment_v3 \
    --device cuda \
    --eval-accuracy \
    --accuracy-tasks piqa,hellaswag \
    --accuracy-limit 200 \
    --whitening-nsamples 256 \
    --profiling-path results/svdllm_experiment/profiling_mat.pt \
    2>&1

echo ""
echo "============================================="
echo "Experiment Complete: $(date)"
echo "============================================="
