# Project Context: Simia WM Sycophancy Experiment

## Research Goal

Study how **World Model (WM) sycophancy** in LLM-based environment simulators affects synthetic training data quality and downstream agent performance. The core hypothesis: when simulators "forgive" invalid agent actions (e.g., accepting wrong tool parameters, ignoring policy violations), the resulting training data teaches agents bad habits.

## What's Been Done

### 1. Telecom Domain Added to Simia Pipeline
- Added **Bedrock API support** to `config.py` and `conversation_generator.py` (previously only OpenAI/Azure)
- Created **telecom seed data**: `APIGen_telecom_seeds.json` (~350 seeds) using `generate_telecom_seeds.py`
- Added telecom support to: `conversation_generator.py` (prompt branch), `tool_correct.py` (validation), `replace_system_prompt_Hermes.py` (system prompt), `score_sycophancy_local.py` (rules)
- 13 telecom tools defined in `tools_seed.json` → `tools_config_1`

### 2. Data Generation Complete
Two generation runs combined:

| Run | Raw | Filtered | Survival Rate | File |
|-----|-----|----------|---------------|------|
| 3000-run | 3,000 | 1,121 | 37.4% | `output/tau2_telecom_base_3000.json` (54MB, LFS) |
| 6000-run | 5,975 | 2,033 | 34.0% | `output/tau2_telecom_base_6000.json` (110MB) |
| **Combined** | **8,975** | **3,154** | **35.1%** | |

- 6000-run config: `config_telecom_base_6000.json` (40→20→10 workers due to Bedrock throttling)
- Also generated comparison data: 200 each of telecom {base, strict, sycophantic} and airline/retail Sonnet {base, strict, sycophantic}

### 3. Sycophancy Scoring Complete
All filtered conversations scored by **LLM judge** (Sonnet via Bedrock):

| Run | Scored | Clean (score=0) | Sycophantic (score>0) | Syc Rate |
|-----|--------|-----------------|----------------------|----------|
| 3000-run | 1,121 | 961 (85.7%) | 160 (14.3%) | 14.3% |
| 6000-run | 2,033 | 1,700 (83.6%) | 333 (16.4%) | 16.4% |
| **Combined** | **3,154** | **2,661 (84.4%)** | **493 (15.6%)** | **15.6%** |

- Score indices: `output/telecom_3000_score_index.json`, `output/telecom_combined_score_index.json`
- 6000-run scoring: `output/sycophancy_llm_scores_v2_base_telecom_6000.jsonl`
- Sycophancy distribution remains **bimodal**: mostly score=0 or score 70-89
- Two types of sycophancy found:
  - **Schema-level**: wrong tool names, missing params, extra args → caught by `tool_correct.py`, already filtered out
  - **Policy-level**: hidden repairs, policy forgiveness, ID inconsistency → escapes pipeline, this is what we study

### 4. SFT Datasets Constructed (1000-sample, CURRENT)
Four datasets with controlled sycophancy proportions, each **1,000 conversations** (combined from both runs):

| Dataset | File | Clean | Sycophantic |
|---------|------|-------|-------------|
| 0% | `output/telecom_syc_0pct_1000_processed.json` | 1,000 | 0 |
| 5% | `output/telecom_syc_5pct_1000_processed.json` | 950 | 50 |
| 10% | `output/telecom_syc_10pct_1000_processed.json` | 900 | 100 |
| 20% | `output/telecom_syc_20pct_1000_processed.json` | 800 | 200 |

Design: 800 clean conversations are **shared across all 4 groups** (80% overlap). Only the remaining 200 slots vary. Random seed=42 for reproducibility. Construction script: `build_sft_datasets_1000.py`. Metadata in `output/dataset_split_metadata_1000.json`. LLaMA Factory registry: `output/dataset_info_1000.json`.

All datasets passed the full 5-step post-processing pipeline (`process_data_pipeline.sh`): fix_arguments → tool2hermes → tool_correct → remove_think_tag → replace_system_prompt_Hermes. **Zero loss** through pipeline (1,000 in → 1,000 out for each).

#### Previous 500-sample datasets (superseded)
Earlier 500-sample versions still exist in `output/telecom_syc_{0,5,10,20}pct_500_processed.json` with metadata in `output/dataset_split_metadata.json` and `output/dataset_info.json`.

## Key Findings So Far

1. **Telecom sycophancy rate is much higher than airline/retail** — but 92.6% of it is schema-level (caught by pipeline). After filtering, policy-level sycophancy is ~15.6% across the combined pool (493/3154).
2. **Consistent across generation runs** — 3000-run: 14.3% sycophantic, 6000-run: 16.4% sycophantic. Rates are stable.
3. **Simulator mode (base/strict/sycophantic) has minimal effect** on sycophancy rate — the difference is not statistically significant.
4. **Model is not a confound** — Sonnet and GPT-4o show similar sycophancy rates on airline/retail.
5. **Sycophancy distribution is bimodal** — conversations are either clean (score=0) or severely sycophantic (score 70-89), rarely in between. 6000-run histogram: 1703 in 0-9, 165 in 10-19, 33 in 20-29, 8 in 70-79, 124 in 80-89.
6. **tool_correct.py filtering rate is stable** — 37.4% (3k-run) vs 34.0% (6k-run) survival rate.

## Next Steps

### SFT Training (LLaMA Factory)
1. Copy the 4 `*_1000_processed.json` files to LLaMA Factory's `data/` directory
2. Merge `output/dataset_info_1000.json` into LLaMA Factory's `dataset_info.json`
3. Train 4 models (one per dataset) with identical hyperparameters:
   ```yaml
   model_name_or_path: Qwen/Qwen2.5-7B-Instruct
   stage: sft
   finetuning_type: full
   template: qwen
   cutoff_len: 12000
   learning_rate: 0.000005
   num_train_epochs: 3-5  # may need tuning, original used 2 on 90k data
   per_device_train_batch_size: 1
   gradient_accumulation_steps: 2
   deepspeed: examples/deepspeed/ds_z3_config.json
   flash_attn: fa2
   neat_packing: true
   bf16: true
   ```
4. Key: **all hyperparameters must be identical** across 4 runs — only the data varies

### Evaluation (τ²-Bench Telecom)
- Evaluate all 4 trained models on τ²-Bench telecom domain (114 tasks)
- Metric: Pass^k (task completion rate)
- Compare: does higher sycophancy proportion in training data → lower task performance?
- Concern: 114 tasks may be small for detecting subtle differences; consider also measuring policy compliance rate

## File Structure

```
Simia_SFT/Tau2/
├── main.py                          # Main generation entry point
├── generate_telecom_seeds.py        # Telecom seed generation script
├── build_sft_datasets_1000.py       # Constructs 1000-sample SFT datasets from combined pool
├── process_data_pipeline.sh         # 5-step post-processing pipeline
├── score_sycophancy_llm.py          # LLM-based sycophancy scoring (supports Bedrock)
├── score_sycophancy_local.py        # Rule-based sycophancy scoring
├── tool_correct.py                  # Tool call validation (filters bad conversations)
├── replace_system_prompt_Hermes.py  # System prompt standardization
├── config_telecom_base_3000.json    # Config used for 3000 generation run
├── config_telecom_base_6000.json    # Config used for 6000 generation run
├── APIGen_telecom_seeds.json        # 350 telecom seed conversations
├── tools_seed.json                  # Tool schemas (tools_config_1 = telecom 13 tools)
├── utils/
│   ├── config.py                    # Config manager (supports bedrock/openai/azure)
│   ├── conversation_generator.py    # LLM conversation generation with domain prompts
│   ├── main_generator.py            # Orchestrator
│   └── parallel_processor.py        # Parallel generation
└── output/
    ├── tau2_telecom_base_3000.json           # 3000 raw generated (LFS)
    ├── tau2_telecom_base_3000_filtered.json  # 1121 after tool_correct (LFS)
    ├── tau2_telecom_base_6000.json           # 5975 raw generated (110MB)
    ├── tau2_telecom_base_6000_filtered.json  # 2033 after tool_correct (37MB)
    ├── telecom_3000_score_index.json         # Per-conversation scores (3000-run only)
    ├── telecom_combined_score_index.json     # Per-conversation scores (combined 3k+6k)
    ├── telecom_syc_{0,5,10,20}pct_1000_processed.json  # 4 SFT datasets (CURRENT, 1000 each)
    ├── telecom_syc_{0,5,10,20}pct_1000.json  # Pre-pipeline versions
    ├── dataset_info_1000.json                # LLaMA Factory dataset registry (1000-sample)
    ├── dataset_split_metadata_1000.json      # Split reproducibility metadata (1000-sample)
    ├── telecom_syc_{0,5,10,20}pct_500_processed.json  # 4 SFT datasets (old, 500 each)
    ├── dataset_info.json                     # LLaMA Factory registry (old 500-sample)
    ├── dataset_split_metadata.json           # Split metadata (old 500-sample)
    ├── sycophancy_llm_scores_v2_*.jsonl      # Per-conversation LLM scoring results
    ├── sycophancy_llm_summary_v2_*.json      # Aggregate scoring summaries
    └── sycophancy_samples_telecom*.json      # Extracted sycophancy examples
```

## API Configuration

Generation and scoring use **AWS Bedrock** (not OpenAI):
- Model: `us.anthropic.claude-sonnet-4-20250514-v1:0`
- Region: `us-east-1`
- Auth: AWS credential chain (no API key needed)

## Telecom Domain Reference (Read-Only)

Policy and tools from τ²-Bench (do NOT use task definitions to avoid eval contamination):
```
tau2-bench/data/tau2/domains/telecom/
├── main_policy.md          # Agent policy rules
├── tech_support_workflow.md # Troubleshooting decision tree
├── db.toml                 # Database schema and examples
└── tools/                  # Tool definitions
```
