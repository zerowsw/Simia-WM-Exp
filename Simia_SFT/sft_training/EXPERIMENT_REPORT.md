# Telecom Sycophancy SFT Experiment Report

**Date**: 2026-02-15
**Total Cost**: ~$130 (OpenRouter API for gpt-4.1 user simulator)

---

## 1. Dataset

### Overview

We constructed 4 SFT datasets with controlled sycophancy proportions from a pool of 3,154 LLM-generated telecom conversations (15.6% sycophantic rate). Each dataset contains **1,000 conversations** with an 80% shared clean base to minimize confounding variables.

| Dataset | Clean | Sycophantic | File |
|---------|-------|-------------|------|
| 0% sycophancy | 1000 | 0 | `telecom_syc_0pct_1000_merged.json` (27MB) |
| 5% sycophancy | 950 | 50 | `telecom_syc_5pct_1000_merged.json` (27MB) |
| 10% sycophancy | 900 | 100 | `telecom_syc_10pct_1000_merged.json` (27MB) |
| 20% sycophancy | 800 | 200 | `telecom_syc_20pct_1000_merged.json` (27MB) |

### Dataset Construction

- **Source data**: Two generation runs (3,000 + 6,000 raw conversations) using Claude Sonnet 4 via AWS Bedrock as the environment simulator, filtered to 1,121 + 2,033 valid conversations by `tool_correct.py` (schema validation).
- **Sycophancy scoring**: LLM-based judge (`score_sycophancy_llm.py`) evaluated each conversation for policy-level forgiveness (hidden repairs, policy violations, ID inconsistencies). Scores are bimodal: either 0 (clean) or 70-89 (sycophantic).
- **Stratified sampling**: `build_sft_datasets_1000.py` with `random_seed=42` selects 800 shared clean conversations across all 4 datasets, then fills 200 variable slots with clean or sycophantic data per the target proportion.
- **Post-processing pipeline** (`process_data_pipeline.sh`): 5-step cleaning (fix_arguments → tool2hermes → tool_correct → remove_think_tag → replace_system_prompt_Hermes), followed by `merge_consecutive_turns.py` to ensure LLaMA Factory's alternating-role requirement.

### Data Location

```
Simia_SFT/Tau2/output/
├── telecom_syc_0pct_1000_merged.json
├── telecom_syc_5pct_1000_merged.json
├── telecom_syc_10pct_1000_merged.json
├── telecom_syc_20pct_1000_merged.json
├── dataset_info_1000.json              # LLaMA Factory registry
└── dataset_split_metadata_1000.json    # Reproducibility metadata (indices, seed)
```

---

## 2. How to Run

### Prerequisites

- 8x NVIDIA A100-SXM4-40GB GPUs
- LLaMA Factory, vLLM, tau2-bench installed
- `tau2-bench/.env` configured with `OPENAI_API_KEY` and `USER_LLM_API_BASE`

### Single Command

```bash
bash Simia_SFT/sft_training/run_telecom_sft_eval.sh
```

This runs the full experiment in two phases:

### Phase 1: SFT Training (Sequential, All GPUs)

Trains 4 models sequentially using DeepSpeed ZeRO-3 across all 8 GPUs:

```bash
# Each model is trained via:
bash Simia_SFT/sft_training/run_sft.sh \
    Simia_SFT/Tau2/output/telecom_syc_{pct}pct_1000_merged.json \
    --skip-process \
    --dataset-name telecom_syc_{pct}pct \
    --epochs 3 \
    --deepspeed Simia_SFT/sft_training/ds_zero3.json
```

**Training hyperparameters**:
| Parameter | Value |
|-----------|-------|
| Base model | Qwen/Qwen2.5-7B-Instruct |
| Finetuning type | Full |
| Epochs | 3 |
| Learning rate | 5e-6 (cosine schedule) |
| Per-device batch size | 1 |
| Gradient accumulation | 2 |
| Effective batch size | 16 (8 GPUs x 1 x 2) |
| Total steps per model | 96 |
| Max sequence length | 12,000 |
| Precision | bf16 |
| DeepSpeed | ZeRO-3 (CPU offload) |
| Time per model | ~20 minutes |

**Output**: `Simia_SFT/sft_training/saves/Qwen2.5-7B-Instruct/telecom_syc_{0,5,10,20}pct/`

### Phase 2: Parallel Evaluation (5 GPUs, Concurrent)

After training, 5 vLLM servers are launched simultaneously (1 per GPU), each serving a different model:

| GPU | Model | Port |
|-----|-------|------|
| 0 | Baseline Qwen2.5-7B-Instruct (no SFT) | 8000 |
| 1 | SFT 0% sycophancy | 8001 |
| 2 | SFT 5% sycophancy | 8002 |
| 3 | SFT 10% sycophancy | 8003 |
| 4 | SFT 20% sycophancy | 8004 |

Each vLLM server is started with:
```bash
CUDA_VISIBLE_DEVICES=$GPU vllm serve $MODEL \
    --host 0.0.0.0 --port $PORT \
    --max-model-len 16000 \
    --gpu-memory-utilization 0.85 \
    --tensor-parallel-size 1 \
    --enable-auto-tool-choice \
    --tool-call-parser hermes
```

5 tau2 evaluations run in parallel, each pointing to its own vLLM server via `VLLM_API_BASE`:
```bash
VLLM_API_BASE="http://localhost:${PORT}/v1" \
tau2 run \
    --domain telecom \
    --agent-llm "openai/$MODEL" \
    --user-llm gpt-4.1 \
    --num-trials 3 \
    --max-concurrency 6
```

- **User simulator**: gpt-4.1 via OpenRouter (`USER_LLM_API_BASE=https://openrouter.ai/api/v1`)
- **Agent**: Local vLLM-served model
- **Tasks**: 114 telecom tasks x 3 trials = 342 task runs per model
- **Metric**: Pass^k (task must succeed in all k trials)

**Evaluation logs**: `tau2-bench/logs/{label}_eval_{timestamp}.log`

---

## 3. Cost Breakdown

| Item | Cost |
|------|------|
| OpenRouter API (gpt-4.1 user simulator) | ~$130 |
| GPU compute (8x A100-40GB) | (infrastructure) |
| **Total API cost** | **~$130** |

The API cost covers 5 models x 342 task runs = 1,710 total simulations, each involving multiple turns of gpt-4.1 calls as the user simulator.

---

## 4. Results and Analysis

### Results

| Model | Pass^1 | Pass^2 | Pass^3 | Avg Reward |
|-------|--------|--------|--------|------------|
| **Baseline (no SFT)** | **0.196** | **0.117** | **0.088** | **0.196** |
| SFT 0% sycophancy | 0.140 | 0.091 | 0.070 | 0.140 |
| SFT 5% sycophancy | 0.155 | 0.111 | 0.079 | 0.155 |
| SFT 10% sycophancy | 0.146 | 0.099 | 0.061 | 0.146 |
| SFT 20% sycophancy | 0.158 | 0.123 | 0.096 | 0.158 |

### Analysis

**Finding 1: SFT degrades performance relative to the base model.**

All 4 SFT models underperform the baseline Qwen2.5-7B-Instruct by 4-6 points on Pass^1 (0.140-0.158 vs 0.196). This suggests that 1,000 telecom conversations are insufficient to improve the base model's general tool-calling ability, and may instead overfit to narrow patterns in the synthetic data.

**Finding 2: Sycophancy proportion has a weak positive effect among SFT models.**

Among the 4 SFT variants, higher sycophancy tends to correlate with slightly better scores, though the trend is not strictly monotonic:

```
Pass^1:  0% (0.140) < 10% (0.146) < 5% (0.155) < 20% (0.158)
Pass^3:  10% (0.061) < 0% (0.070) < 5% (0.079) < 20% (0.096)
```

The 20% sycophancy model consistently scores highest among SFT variants. One hypothesis: sycophantic conversations tend to complete successfully (the simulator "forgives" errors), so they contain more complete action sequences. This may teach the agent to be more action-oriented rather than overly cautious.

**Finding 3: The sycophancy effect is secondary to the SFT quality issue.**

The performance gap between sycophancy levels (0.018 spread on Pass^1) is much smaller than the gap between baseline and any SFT model (0.038-0.056). Improving the base SFT data quality and quantity would likely have a larger impact than controlling sycophancy proportions.

**Finding 4: Robustness (Pass^3) follows a similar pattern.**

The 20% sycophancy model shows the best robustness (Pass^3 = 0.096), close to the baseline (0.088). This suggests that while SFT hurts single-attempt performance, the sycophantic data may help with consistency.

### Limitations

- **Small scale**: 1,000 training samples may be insufficient for meaningful SFT on a 7B model.
- **Single domain**: Only telecom tasks evaluated; results may not generalize to airline or retail.
- **3 trials**: Pass^k with only 3 trials has high variance; more trials would increase statistical confidence.
- **Context window errors**: One task (113/114) consistently exceeded the 16,000 token vLLM limit across all models, potentially biasing results slightly.

### Trained Models (S3)

```
s3://ray-benchmark-data-internal-us-west-2/temp_wm/0215_test/
├── telecom_syc_0pct/    (42.6 GB)
├── telecom_syc_5pct/    (42.6 GB)
├── telecom_syc_10pct/   (42.6 GB)
└── telecom_syc_20pct/   (42.6 GB)
```
