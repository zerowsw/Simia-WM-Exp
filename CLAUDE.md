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
- **3000 raw telecom base conversations** generated → `output/tau2_telecom_base_3000.json` (54MB, LFS-tracked)
- **1121 survived** `tool_correct.py` filtering → `output/tau2_telecom_base_3000_filtered.json` (37.4% survival rate)
- Also generated comparison data: 200 each of telecom {base, strict, sycophantic} and airline/retail Sonnet {base, strict, sycophantic}

### 3. Sycophancy Scoring Complete
- All 1121 filtered conversations scored by **LLM judge** (Sonnet via Bedrock)
- Score index: `output/telecom_3000_score_index.json`
  - **961 clean** (score=0, 85.7%)
  - **160 sycophantic** (score>0, 14.3%) — bimodal: 86 mild (1-20) + 74 severe (50+)
- Two types of sycophancy found:
  - **Schema-level**: wrong tool names, missing params, extra args → caught by `tool_correct.py`, already filtered out
  - **Policy-level**: hidden repairs, policy forgiveness, ID inconsistency → escapes pipeline, this is what we study

### 4. SFT Datasets Constructed
Four datasets with controlled sycophancy proportions, each 500 conversations:

| Dataset | File | Clean | Sycophantic |
|---------|------|-------|-------------|
| 0% | `output/telecom_syc_0pct_500_processed.json` | 500 | 0 |
| 5% | `output/telecom_syc_5pct_500_processed.json` | 475 | 25 |
| 10% | `output/telecom_syc_10pct_500_processed.json` | 450 | 50 |
| 20% | `output/telecom_syc_20pct_500_processed.json` | 400 | 100 |

Design: 400 clean conversations are **shared across all 4 groups** (80% overlap). Only the remaining 100 slots vary. Random seed=42 for reproducibility. Metadata in `output/dataset_split_metadata.json`.

All datasets have been through the full 5-step post-processing pipeline (`process_data_pipeline.sh`): fix_arguments → tool2hermes → tool_correct → remove_think_tag → replace_system_prompt_Hermes.

## Key Findings So Far

1. **Telecom sycophancy rate is much higher than airline/retail** — but 92.6% of it is schema-level (caught by pipeline). After filtering, policy-level sycophancy is ~5-7% across all domains.
2. **Simulator mode (base/strict/sycophantic) has minimal effect** on sycophancy rate — the difference is not statistically significant.
3. **Model is not a confound** — Sonnet and GPT-4o show similar sycophancy rates on airline/retail.
4. **Sycophancy distribution is bimodal** — conversations are either clean (score=0) or severely sycophantic (score 50+), rarely in between.

## Next Steps

### SFT Training (LLaMA Factory)
1. Copy the 4 `*_processed.json` files to LLaMA Factory's `data/` directory
2. Merge `output/dataset_info.json` into LLaMA Factory's `dataset_info.json`
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
├── process_data_pipeline.sh         # 5-step post-processing pipeline
├── score_sycophancy_llm.py          # LLM-based sycophancy scoring (supports Bedrock)
├── score_sycophancy_local.py        # Rule-based sycophancy scoring
├── tool_correct.py                  # Tool call validation (filters bad conversations)
├── replace_system_prompt_Hermes.py  # System prompt standardization
├── config_telecom_base_3000.json    # Config used for 3000 generation run
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
    ├── telecom_3000_score_index.json         # Per-conversation sycophancy scores
    ├── telecom_syc_{0,5,10,20}pct_500_processed.json  # 4 SFT datasets (FINAL)
    ├── telecom_syc_{0,5,10,20}pct_500.json  # Pre-pipeline versions
    ├── dataset_info.json                     # LLaMA Factory dataset registry
    ├── dataset_split_metadata.json           # Split reproducibility metadata
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
