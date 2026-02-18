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

### 4. Data Quality Fix: Embedded HUMAN: and Legacy FUNCTION_CALL:
Investigation of first SFT run (all models worse than baseline) revealed two telecom-specific data corruption issues:

1. **Embedded HUMAN:** — Claude Sonnet sometimes generates `"...gpt text...HUMAN: user response"` on a single line. The parser (`conversation_generator.py`) only split on newlines, so these were kept as gpt turns. When `merge_consecutive_turns.py` merged consecutive gpt turns, user text got embedded in assistant turns — corrupting 72.6% of conversations.

2. **Legacy FUNCTION_CALL:** — Tool calls generated as `gpt: "FUNCTION_CALL: {...}"` instead of proper `function_call` role. These were invisible to `tool_correct.py` validation (it only checked `function_call` role and `<tool_call>` tags in gpt turns). 80.9% of sycophantic tool calls used this legacy format vs 3.5% of clean.

**Fixes applied:**
- **`split_embedded_human.py`** (new) — Splits embedded `HUMAN:` text from gpt turns AND converts `FUNCTION_CALL:` gpt turns to `function_call` role. Added as step 1 in `process_data_pipeline.sh`.
- **`conversation_generator.py`** (modified) — Fixed `parse_gpt_response()` with `re.sub()` to insert newlines before mid-line turn markers, preventing the issue in future generation runs.
- **`rebuild_datasets.py`** (new) — Processes entire combined pool through pipeline filter, identifies survivors, builds equal-sized datasets with correct sycophancy ratios from the surviving pool.

**Impact:** After full fix, only 92 of 493 sycophantic conversations survive validation (81.3% had invalid tool schemas). This is a telecom-specific issue — airline/retail data has 0% legacy format issues.

### 5. SFT Datasets Constructed (920-sample, CURRENT)
Three datasets with controlled sycophancy proportions, each **920 conversations** (combined from both runs, all schema-valid):

| Dataset | File | Clean | Sycophantic |
|---------|------|-------|-------------|
| 0% | `output/telecom_syc_0pct_920_merged.json` | 920 | 0 |
| 5% | `output/telecom_syc_5pct_920_merged.json` | 874 | 46 |
| 10% | `output/telecom_syc_10pct_920_merged.json` | 828 | 92 |

Design: 736 clean conversations are **shared across all 3 groups** (80% overlap). Only the remaining 184 slots vary. Random seed=42 for reproducibility. Construction script: `rebuild_datasets.py`. LLaMA Factory registry: `output/dataset_info_920.json`.

Pipeline: 6-step (`process_data_pipeline.sh`): split_embedded_human → fix_arguments → tool2hermes → tool_correct → remove_think_tag → replace_system_prompt_Hermes. Then `merge_consecutive_turns.py`. **Zero loss** through pipeline (920 in → 920 out, 0 non-alternating, 0 embedded HUMAN:).

20% sycophancy dropped because only 92 sycophantic conversations have valid tool schemas. Max dataset size at 10% = 920 (constrained by 92/0.10).

#### Previous 1000-sample datasets (superseded)
Earlier 1000-sample versions in `output/telecom_syc_{0,5,10,20}pct_1000_*.json` had unequal sizes after pipeline fix (0%→1000, 5%→962, 10%→917, 20%→840) due to sycophantic conversations failing tool_correct validation.

#### Previous 500-sample datasets (superseded)
Earlier 500-sample versions in `output/telecom_syc_{0,5,10,20}pct_500_processed.json`.

## Key Findings So Far

1. **Telecom sycophancy rate is much higher than airline/retail** — but 92.6% of it is schema-level (caught by pipeline). After filtering, policy-level sycophancy is ~15.6% across the combined pool (493/3154).
2. **Consistent across generation runs** — 3000-run: 14.3% sycophantic, 6000-run: 16.4% sycophantic. Rates are stable.
3. **Simulator mode (base/strict/sycophantic) has minimal effect** on sycophancy rate — the difference is not statistically significant.
4. **Model is not a confound** — Sonnet and GPT-4o show similar sycophancy rates on airline/retail.
5. **Sycophancy distribution is bimodal** — conversations are either clean (score=0) or severely sycophantic (score 70-89), rarely in between.
6. **tool_correct.py filtering rate is stable** — 37.4% (3k-run) vs 34.0% (6k-run) survival rate.
7. **Sycophancy strongly correlates with schema issues** — 80.9% of sycophantic tool calls use legacy FUNCTION_CALL: format vs 3.5% for clean. After proper validation, only 92/493 (18.7%) sycophantic conversations survive. This means policy-sycophantic conversations disproportionately also have schema-level issues.
8. **Telecom-specific data format issue** — airline/retail data has 0% embedded HUMAN: and 0% legacy FUNCTION_CALL:. The issue comes from the telecom conversation generation process (Claude Sonnet omitting newlines between turn markers).
9. **First SFT experiment invalidated** — All 4 SFT models performed worse than baseline (0.140-0.158 vs 0.196 Pass^1). Root cause: corrupted training data from `merge_consecutive_turns.py` embedding user text in assistant turns.

## First SFT Experiment Results (1000-sample, BEFORE data fix)

Trained 4 models on the old 1000-sample datasets (which had corrupted data from embedded HUMAN: issue). All SFT models performed **worse** than the baseline:

| Model | Pass^1 | Pass^2 | Pass^3 |
|-------|--------|--------|--------|
| Baseline (Qwen2.5-7B-Instruct) | 0.196 | 0.281 | 0.342 |
| SFT 0% syc | 0.158 | 0.237 | 0.298 |
| SFT 5% syc | 0.152 | 0.228 | 0.289 |
| SFT 10% syc | 0.140 | 0.219 | 0.272 |
| SFT 20% syc | 0.146 | 0.224 | 0.281 |

These results are invalidated by the data corruption. The 920-sample clean datasets should produce more meaningful results.

## Round 2 SFT Experiment Results (920-sample, clean data)

Trained on clean 920-sample datasets after fixing embedded HUMAN: and legacy FUNCTION_CALL: issues. Evaluated on τ²-Bench telecom domain (114 tasks x 3 trials):

| Model | Pass^1 | Pass^2 | Pass^3 |
|-------|--------|--------|--------|
| Baseline (Qwen2.5-7B-Instruct) | 0.196 | 0.117 | 0.088 |
| SFT 0% syc (920, clean) | 0.129 | 0.073 | 0.044 |
| SFT 10% syc (920, clean) | 0.079 | 0.018 | 0.009 |

Key findings:
- **Sycophancy has a clear negative causal effect**: 0% vs 10% shows 63% relative improvement on Pass^1 (0.129 vs 0.079), amplifying to 5x on Pass^3 (0.044 vs 0.009).
- **SFT still hurts vs baseline**: Even the clean 0% model underperforms baseline (0.129 vs 0.196), suggesting ~920 synthetic conversations are insufficient.
- **Effect amplifies with robustness**: Higher Pass^k thresholds show larger sycophancy penalties, meaning sycophantic training data severely damages consistency.

## Next Steps

### Remaining Round 2 Evaluation
- Train and evaluate the 5% sycophancy model to complete the dose-response curve
- Consider increasing dataset size or training epochs to close the baseline gap

## File Structure

```
Simia_SFT/Tau2/
├── main.py                          # Main generation entry point
├── generate_telecom_seeds.py        # Telecom seed generation script
├── split_embedded_human.py          # Fix embedded HUMAN: and legacy FUNCTION_CALL: (NEW)
├── rebuild_datasets.py              # Build equal-sized datasets from surviving pool (NEW)
├── reprocess_datasets.sh            # Reprocess all datasets with updated pipeline (NEW)
├── build_sft_datasets_1000.py       # Constructs 1000-sample SFT datasets (old)
├── process_data_pipeline.sh         # 6-step post-processing pipeline (updated, +split_embedded_human)
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
│   ├── conversation_generator.py    # LLM conversation generation (fixed parser) (MODIFIED)
│   ├── main_generator.py            # Orchestrator
│   └── parallel_processor.py        # Parallel generation
└── output/
    ├── tau2_telecom_base_3000.json           # 3000 raw generated (LFS)
    ├── tau2_telecom_base_3000_filtered.json  # 1121 after tool_correct (LFS)
    ├── tau2_telecom_base_6000.json           # 5975 raw generated (LFS)
    ├── tau2_telecom_base_6000_filtered.json  # 2033 after tool_correct (LFS)
    ├── telecom_syc_{0,5,10}pct_920_merged.json    # 3 SFT datasets (CURRENT, 920 each)
    ├── telecom_syc_{0,5,10}pct_920_processed.json # Post-pipeline versions
    ├── telecom_syc_{0,5,10}pct_920.json           # Pre-pipeline versions
    ├── dataset_info_920.json                 # LLaMA Factory dataset registry (920-sample)
    ├── telecom_3000_score_index.json         # Per-conversation scores (3000-run only)
    ├── telecom_combined_score_index.json     # Per-conversation scores (combined 3k+6k)
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
