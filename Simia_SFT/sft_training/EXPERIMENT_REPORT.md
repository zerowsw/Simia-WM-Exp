# Telecom Sycophancy SFT Experiment Report

**Date**: 2026-02-15 (Round 1), 2026-02-17 (Round 2)
**Total Cost**: ~$130 (Round 1) + ~$26 (Round 2) OpenRouter API for gpt-4.1 user simulator

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

---

## 5. Round 2: Clean 920-Sample Dataset (2026-02-17)

### Background

Round 1 results were invalidated by two telecom-specific data corruption issues discovered post-training:

1. **Embedded HUMAN:** — Claude Sonnet sometimes generated `"...gpt text...HUMAN: user response"` on a single line. The parser only split on newlines, so `merge_consecutive_turns.py` embedded user text in assistant turns, corrupting 72.6% of conversations.
2. **Legacy FUNCTION_CALL:** — Tool calls generated as `gpt: "FUNCTION_CALL: {...}"` instead of proper `function_call` role. 80.9% of sycophantic tool calls used this format vs 3.5% of clean, making them invisible to `tool_correct.py` validation.

After fixing these issues (`split_embedded_human.py`, parser fix in `conversation_generator.py`), only 92 of the original 493 sycophantic conversations survived validation (81.3% had invalid tool schemas). This constrained the maximum dataset size: at 10% sycophancy, max = 92/0.10 = 920 conversations.

### Dataset

Three datasets with controlled sycophancy proportions, each **920 conversations** (combined from both generation runs, all schema-valid):

| Dataset | Clean | Sycophantic | File |
|---------|-------|-------------|------|
| 0% sycophancy | 920 | 0 | `telecom_syc_0pct_920_merged.json` (25MB) |
| 5% sycophancy | 874 | 46 | `telecom_syc_5pct_920_merged.json` (25MB) |
| 10% sycophancy | 828 | 92 | `telecom_syc_10pct_920_merged.json` (25MB) |

Design: 736 clean conversations are **shared across all 3 groups** (80% overlap). Only the remaining 184 slots vary. Random seed=42 for reproducibility. Construction script: `rebuild_datasets.py`.

Pipeline: 6-step (`process_data_pipeline.sh`): split_embedded_human → fix_arguments → tool2hermes → tool_correct → remove_think_tag → replace_system_prompt_Hermes. Then `merge_consecutive_turns.py`. **Zero loss** through pipeline (920 in → 920 out).

### Training

Trained on the 10% sycophancy dataset only (as initial validation run):

```bash
bash Simia_SFT/sft_training/run_sft.sh \
    Simia_SFT/Tau2/output/telecom_syc_10pct_920_merged.json \
    --skip-process \
    --dataset-name telecom_syc_10pct_920 \
    --epochs 3 \
    --deepspeed Simia_SFT/sft_training/ds_zero3.json
```

| Parameter | Value |
|-----------|-------|
| Base model | Qwen/Qwen2.5-7B-Instruct |
| Finetuning type | Full |
| Epochs | 3 |
| Training samples | 472 (920 conversations, neat_packing) |
| Total steps | 90 |
| Final train loss | 0.3699 |
| Training time | 20 min 28 sec |

Model saved to: `Simia_SFT/sft_training/saves/Qwen2.5-7B-Instruct/telecom_syc_10pct_920/`

### Evaluation

Evaluated on tau2-bench telecom domain (114 tasks x 3 trials):

```bash
bash Simia_SFT/sft_training/run_telecom_sft_eval.sh
```

### Results

| Model | Pass^1 | Pass^2 | Pass^3 | Avg Reward |
|-------|--------|--------|--------|------------|
| **Baseline (no SFT)** | **0.196** | **0.117** | **0.088** | **0.196** |
| Round 1: SFT 10% (1000, corrupted) | 0.146 | 0.099 | 0.061 | 0.146 |
| **Round 2: SFT 10% (920, clean)** | **0.079** | **0.018** | **0.009** | **0.079** |

### Analysis

**Finding 1: Clean data performs worse than corrupted data.**

The Round 2 model (clean 920-sample) scores substantially lower than the Round 1 model (corrupted 1000-sample) on all metrics: Pass^1 drops from 0.146 to 0.079, Pass^3 from 0.061 to 0.009. This is counterintuitive — fixing data corruption made the model worse.

**Finding 2: Possible explanations.**

- **Overfitting on smaller dataset**: 920 samples (472 packed) may be too few, producing only 90 training steps. The Round 1 model had 1000 samples with more diversity (even if some was noise from corruption).
- **Noise as regularization**: The corrupted data (embedded user text in assistant turns) may have inadvertently acted as a form of data augmentation, preventing the model from overfitting to narrow telecom patterns.
- **Loss of action diversity**: Round 1's corrupted sycophantic conversations (80.9% with legacy FUNCTION_CALL: format) were schema-invalid but may have contained useful behavioral patterns. Removing them reduced the diversity of action sequences the model could learn from.

**Finding 3: SFT on synthetic telecom data consistently hurts performance.**

Across both rounds, every SFT model underperforms the baseline. The base Qwen2.5-7B-Instruct model (Pass^1 = 0.196) is better at telecom tasks than any fine-tuned variant. This suggests that ~1000 synthetic telecom conversations are insufficient to improve a 7B instruction-tuned model, and may instead overfit it to narrow patterns while degrading its general tool-calling capabilities.
