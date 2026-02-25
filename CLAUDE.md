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

### Data Generation Findings
1. **Telecom sycophancy rate is much higher than airline/retail** — but 92.6% of it is schema-level (caught by pipeline). After filtering, policy-level sycophancy is ~15.6% across the combined pool (493/3154).
2. **Consistent across generation runs** — 3000-run: 14.3% sycophantic, 6000-run: 16.4% sycophantic. Rates are stable.
3. **Simulator mode (base/strict/sycophantic) has minimal effect** on sycophancy rate — the difference is not statistically significant.
4. **Model is not a confound** — Sonnet and GPT-4o show similar sycophancy rates on airline/retail.
5. **Sycophancy distribution is bimodal** — conversations are either clean (score=0) or severely sycophantic (score 70-89), rarely in between.
6. **tool_correct.py filtering rate is stable** — 37.4% (3k-run) vs 34.0% (6k-run) survival rate.
7. **Sycophancy strongly correlates with schema issues** — 80.9% of sycophantic tool calls use legacy FUNCTION_CALL: format vs 3.5% for clean. After proper validation, only 92/493 (18.7%) sycophantic conversations survive.

### Data Quality Issues Found (all telecom-specific)
8. **Embedded HUMAN: issue** — Claude Sonnet sometimes generates `"...gpt text...HUMAN: user response"` on a single line, corrupting 72.6% of conversations when merged. Fixed with `split_embedded_human.py`.
9. **Legacy FUNCTION_CALL: format** — Tool calls as `gpt: "FUNCTION_CALL: {...}"` instead of proper role. Fixed with parser update.
10. **User-only tools in training data** — V2 training data included 29 user-side tools (toggle_*, check_*) that agent cannot call during evaluation. This caused 80-88% tool call failure rates in SFT models vs 8% for baseline.

### SFT Experiment Findings
11. **Three rounds of SFT experiments failed** due to different data quality issues each time:
    - Round 1: Embedded HUMAN: corruption
    - Round 2: (transitional)
    - Round 3: User-only tools in training data
12. **Baseline significantly outperforms all SFT models** — 0.263 vs 0.009-0.053 Pass^1. Root cause: SFT models call unavailable user-side tools.
13. **Tool call error rate is the key diagnostic** — 88% error rate for SFT vs 8% for baseline immediately reveals the problem.

### Critical Lesson Learned
14. **τ²-Bench has strict agent/user tool separation** — Agent can only call 13 tools (database lookups, account actions). User-side tools (30+ device diagnostics/controls) must be performed by user following agent's verbal instructions. Training data MUST respect this separation.

### Degenerate Model Behavior
15. **SFT models exhibit degenerate repetition bugs due to training/evaluation format mismatch** — Two patterns discovered:
    - Duplicate tool calls: 50+ identical tool calls in single response (e.g., `get_customer_by_phone` called 50 times)
    - Repeated text: same phrase repeated 1,500+ times (21.9% of simulations)
    - These cause context to explode past 32K tokens, failing 58 of 114 tasks deterministically
16. **Root cause: Tool response format mismatch** — Training data has tool responses as plain JSON in user turns, but evaluation uses Qwen's `<tool_response>` wrapper. Model doesn't recognize wrapped responses → keeps retrying tool calls.
17. **Root cause: Terminal phrase pattern** — "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON." is the last message in 91.2% of training instances, teaching the model this ends conversations. At evaluation, conversation continues → model repeats phrase infinitely.
18. **Airline/retail data does NOT have these issues** — Uses proper `function_call` and `observation` roles that LLaMA Factory handles correctly. Terminal phrases at conversation end: only 1.7% vs 35.9% in telecom.
19. **Root cause: `tool2hermes.py` in pipeline** — The telecom generation script produces CORRECT format, but `tool2hermes.py` converts `function_call`→`gpt` and `observation`→`human`, breaking LLaMA Factory's native tool handling. This was a flawed design decision based on misunderstanding how vLLM Hermes parser works.

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

## Round 2 SFT Experiment Results (920-sample, after format fix)

Trained on 920-sample datasets after fixing embedded HUMAN: and legacy FUNCTION_CALL: format issues. **However, this round also failed due to a different root cause.**

| Model | Pass^1 | Pass^2 | Pass^3 |
|-------|--------|--------|--------|
| Baseline (Qwen2.5-7B-Instruct) | 0.266 | 0.149 | 0.114 |
| SFT 0% syc | 0.190 | 0.085 | 0.044 |

Results invalidated — see Round 3 for continuation.

## Round 3 SFT Experiment Results (800-sample V2 datasets)

Trained on V2 800-sample datasets. Evaluated on τ²-Bench telecom domain (114 tasks × 3 trials, user-llm: Claude Sonnet 4 via Bedrock):

| Model | Pass^1 | Pass^2 | Pass^3 |
|-------|--------|--------|--------|
| **Baseline (Qwen2.5-7B-Instruct)** | **0.263** | **0.421** | **0.465** |
| SFT 0% sycophancy | 0.009 | 0.009 | 0.009 |
| SFT 10% sycophancy | 0.053 | 0.096 | 0.105 |
| SFT 20% sycophancy | 0.000 | 0.018 | 0.018 |

**Key observation**: All SFT models catastrophically underperform baseline (96-100% degradation in Pass^1).

### Root Cause: User-Only Tools in Training Data

The V2 training data was generated with **41 tools including 29 user-side tools** that the agent should NOT call directly. In τ²-Bench:

- **Agent tools (13)**: `get_customer_by_phone`, `get_details_by_id`, `enable_roaming`, etc. — the agent CAN call these
- **User tools (30+)**: `toggle_airplane_mode`, `check_status_bar`, `run_speed_test`, etc. — only the USER can perform these; the agent must GUIDE the user verbally

**The training data taught models to call user-side tools directly**, but these tools don't exist in the evaluation environment. When the agent tries to call them, they fail.

**Tool Call Error Rates (smoking gun):**

| Model | Tool Call Error Rate |
|-------|---------------------|
| Baseline | 8.4% |
| SFT 0% | **88.2%** |
| SFT 10% | **80.1%** |
| SFT 20% | **83.4%** |

**Tool Call Patterns:**

| Model | Top Tools Called |
|-------|-----------------|
| Baseline | `get_details_by_id` (262), `get_customer_by_phone` (232), `transfer_to_human_agents` (102) |
| SFT 0% | `check_network_status` (85), `check_status_bar` (43), `toggle_airplane_mode` (18) ❌ |
| SFT 10% | `check_network_status` (382), `toggle_airplane_mode` (118), `check_status_bar` (165) ❌ |

The SFT models learned to call user-side tools (marked ❌) which fail during evaluation, while baseline correctly uses only agent-side tools and guides users verbally through troubleshooting.

### Why 10% > 0% in Pass^1?

Counterintuitively, the 10% sycophancy model (0.053) outperformed the 0% clean model (0.009). This is likely because:
1. The 10% model made MORE total tool calls (1741 vs 358), including some valid agent-side calls
2. Random chance due to the very low absolute numbers (6 vs 1 successful tasks)
3. Not a meaningful signal given the 80%+ error rates across all SFT models

### Additional Finding: Degenerate Model Behavior (Context Window Errors)

Further investigation revealed **58 tasks ALWAYS fail** with context window errors (32K-240K+ tokens) while **56 tasks ALWAYS succeed**. Root cause: **Training/evaluation format mismatch**.

**Two degenerate behaviors discovered:**

1. **Duplicate Tool Calls** — Model generates 50+ identical tool calls in a single response:
   ```
   <tool_call>{"name": "get_customer_by_phone", "arguments": {"phone_number": "555-123-2002"}}</tool_call>
   <tool_call>{"name": "get_customer_by_phone", "arguments": {"phone_number": "555-123-2002"}}</tool_call>
   ... (repeated 50 times)
   ```
   Each tool call gets executed → 50 × ~500 chars = 25,000+ chars added to context instantly → next API call exceeds 32K token limit.

2. **Repeated Text** — Model repeats the same phrase 1,500+ times:
   ```
   "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON. YOU ARE BEING TRANSFERRED..."
   ```
   Creates ~95K character messages. Found in 21.9% of simulations (25 of 114).

### Root Cause Analysis: Training/Evaluation Format Mismatch

**Critical mismatch #1: Tool response format**

Training format (LLaMA Factory sharegpt → Qwen template):
```
<|im_start|>user
{"customer_id": "C2947", "full_name": "Lisa Martinez", ...}
<|im_end|>
```

Evaluation format (vLLM Hermes parser → Qwen template):
```
<|im_start|>user
<tool_response>
{"customer_id": "C2947", "full_name": "Lisa Martinez", ...}
</tool_response>
<|im_end|>
```

The model was never trained to recognize `<tool_response>` tags. When it sees them at evaluation, it doesn't understand the response is from a tool → keeps generating tool calls trying to "retry".

**Critical mismatch #2: Terminal phrase pattern**

In training data, "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON." is the **last message in 91.2% of cases** (125/137 instances). The model learned this as a conversation-ending phrase. But during evaluation, the conversation continues, so the model keeps generating the phrase repeatedly.

**Training data statistics:**
- Messages with `<tool_call>`: 2,204 (all single tool call per message)
- Messages with TRANSFER phrase: 137 (125 are conversation-ending)
- `get_customer_by_phone` appears in 100% of conversations (859/859)

**Why pattern is deterministic:** temp=0 + same seed = same degenerate output for same inputs. The 58 failing tasks consistently trigger these degenerate behaviors.

**vLLM error examples:**
```
ValueError: This model's maximum context length is 32768 tokens. However, you requested 64210 tokens
ValueError: This model's maximum context length is 32768 tokens. However, you requested 242613 tokens
```

### Fix Required: Align Training Format with Evaluation

To fix the degenerate behavior, training data must match evaluation format:

1. **Tool responses must use `<tool_response>` tags** — modify data generation to wrap tool outputs:
   ```
   <|im_start|>user
   <tool_response>
   {"customer_id": "C2947", ...}
   </tool_response>
   <|im_end|>
   ```

2. **Remove conversation-ending phrases** — the TRANSFER phrase should not be taught as a terminal pattern

3. **Use proper Qwen tool format** — ensure LLaMA Factory applies Qwen's native tool template during training

### Comparison: Telecom vs Airline/Retail Data Format

Investigation revealed the **airline/retail data does NOT have these issues** — the problem is specific to how telecom data was generated.

**Role types comparison:**

| Dataset | Roles Used |
|---------|------------|
| Telecom | `human` (10,105), `gpt` (10,105) — **no tool roles** |
| Airline/Retail | `human` (9,051), `gpt` (8,997), `function_call` (7,711), `observation` (7,711) |

**Format comparison:**

| Aspect | Telecom (Broken) | Airline/Retail (Correct) |
|--------|------------------|--------------------------|
| Tool calls | `<tool_call>` tags embedded in `gpt` content | Dedicated `function_call` role |
| Tool responses | Plain JSON in `human` turns | Dedicated `observation` role |
| Terminal phrases at end | **35.9%** (131/365) | **1.7%** (5/295) |
| LLaMA Factory support | Missing tool role mappings | Built-in `function_tag`, `observation_tag` support |

**Why airline/retail would work:**
1. LLaMA Factory maps `observation` → Qwen's `<|im_start|>tool` format automatically
2. This matches what vLLM sends at evaluation time
3. Model sees consistent format in training and evaluation
4. Transfer phrases rarely end conversations, so no terminal pattern learned

**Root cause:** The telecom data generation script (`generate_telecom_seeds.py`) actually generates the CORRECT format with `function_call` and `observation` roles. **The problem is `tool2hermes.py` in the processing pipeline** which intentionally converts them:

```python
# tool2hermes.py lines 51-57:
if from_role == "function_call":
    converted.append({"from": "gpt", "value": hermes_value})  # ← Converts to "gpt"!
elif from_role == "observation":
    converted.append({"from": "human", "value": value})        # ← Converts to "human"!
```

**Why this was done (flawed reasoning):**
- The script was designed to create "Hermes format" for vLLM's `--tool-call-parser hermes`
- Assumption: "vLLM parses `<tool_call>` tags, so train on `<tool_call>` tags"
- **But this ignores the response side!** vLLM's Hermes parser handles OUTPUT (extracting tool calls), not INPUT (formatting tool responses). Qwen template still wraps responses in `<tool_response>` tags.

**Evidence - format changes through pipeline:**
```
step1 (after split_embedded_human.py): function_call: 39, observation: 39  ✓
step2 (after fix_arguments.py):        function_call: 39, observation: 39  ✓
step3 (after tool2hermes.py):          human: 137, gpt: 142               ✗ BROKEN!
```

**Fix:** Remove `tool2hermes.py` from the pipeline. Let LLaMA Factory handle `function_call`/`observation` roles natively → proper Qwen tool template → matches evaluation format.

## Post-Mortem: Why We Didn't Catch This Earlier

### What We Checked (and why it wasn't enough)

1. **Data format validation** ✓ — We verified Hermes format, alternating turns, no embedded HUMAN:
2. **Tool schema exists** ✓ — We checked that tools in training data have valid schemas
3. **Pipeline passes** ✓ — All 800 conversations passed `tool_correct.py` validation

### What We Should Have Checked (but didn't)

1. **Agent vs User tool separation** ✗ — Never verified which tools the agent can actually CALL vs which are USER-ONLY
2. **Baseline behavior analysis** ✗ — Never analyzed what tools baseline uses to SUCCEED before training
3. **Small-scale validation run** ✗ — Never tested a small SFT model on a few tasks before full training
4. **Tool call success rate** ✗ — Never checked if model's tool calls actually succeed in evaluation

### Root Cause of Process Failure

1. **Assumed more tools = better**: When we saw "tool schema mismatch" in Round 2 analysis, we incorrectly assumed the fix was to ADD more tools to training data. We added user-side tools without understanding the agent/user separation.

2. **No evaluation-first mindset**: We focused on making training data "complete" without first understanding how successful evaluation works.

3. **Reactive debugging**: Each round, we found and fixed ONE issue, then re-ran everything. We never stepped back to validate the full pipeline end-to-end.

## Prevention: Validation Checklist for Future Experiments

Before ANY SFT training, run this checklist:

### 1. Analyze Baseline Behavior First
```bash
# What tools does baseline call to SUCCEED?
python analyze_baseline_success.py --results baseline_results.json
```
- List all tools baseline uses in successful tasks
- These are the ONLY tools training data should include

### 2. Validate Training Data Tools
```bash
# Check training data only uses agent-callable tools
python validate_training_data.py training_data.json --domain telecom
```
- FAIL if any tool is not in the agent's available tool set
- FAIL if any user-only tools are called by the agent

### 3. Small-Scale Validation Run
Before full training:
1. Train on 50-100 samples (fast, ~10 min)
2. Run evaluation on 10 tasks (fast, ~5 min)
3. Check: tool call error rate should be <20%
4. Check: tool usage pattern should match baseline

### 4. Tool Call Success Rate Check
After evaluation, immediately check:
```bash
python check_tool_errors.py results.json
```
- If error rate >50%, STOP and investigate
- Do not proceed to analyze Pass^k metrics

## Next Steps

### Fix Training Data Generation
1. **Remove user-side tools** from `generate_telecom_seeds.py` — agent should ONLY have access to the 13 agent-callable tools
2. **Change interaction pattern** — when troubleshooting is needed, agent should output verbal instructions (e.g., "Please toggle your airplane mode") NOT call `toggle_airplane_mode` as a tool
3. **Regenerate seed data** with correct agent-only tools
4. **Validate** using the checklist above before training

## File Structure

```
Simia_SFT/Tau2/
├── main.py                          # Main generation entry point
├── generate_telecom_seeds.py        # Telecom seed generation script (NEEDS FIX: remove user-only tools)
├── validate_training_data.py        # Pre-training validation script (NEW, REQUIRED before any training)
├── split_embedded_human.py          # Fix embedded HUMAN: and legacy FUNCTION_CALL:
├── rebuild_datasets.py              # Build equal-sized datasets from surviving pool
├── reprocess_datasets.sh            # Reprocess all datasets with updated pipeline
├── build_sft_datasets_1000.py       # Constructs 1000-sample SFT datasets (old)
├── process_data_pipeline.sh         # 6-step post-processing pipeline
├── score_sycophancy_llm.py          # LLM-based sycophancy scoring (supports Bedrock)
├── score_sycophancy_local.py        # Rule-based sycophancy scoring
├── tool_correct.py                  # Tool call validation (filters bad conversations)
├── replace_system_prompt_Hermes.py  # System prompt standardization
├── config_telecom_base_3000.json    # Config used for 3000 generation run
├── config_telecom_base_6000.json    # Config used for 6000 generation run
├── APIGen_telecom_seeds.json        # 350 telecom seed conversations
├── tools_seed.json                  # Tool schemas (tools_config_1 = 13 agent tools ONLY)
├── utils/
│   ├── config.py                    # Config manager (supports bedrock/openai/azure)
│   ├── conversation_generator.py    # LLM conversation generation (fixed parser)
│   ├── main_generator.py            # Orchestrator
│   └── parallel_processor.py        # Parallel generation
└── output/
    ├── tau2_telecom_base_3000.json           # 3000 raw generated (LFS)
    ├── tau2_telecom_base_3000_filtered.json  # 1121 after tool_correct (LFS)
    ├── tau2_telecom_base_6000.json           # 5975 raw generated (LFS)
    ├── tau2_telecom_base_6000_filtered.json  # 2033 after tool_correct (LFS)
    ├── telecom_v2_syc_{0,10,20}pct_800*.json # V2 SFT datasets (INVALID - has user tools)
    ├── telecom_3000_score_index.json         # Per-conversation scores (3000-run only)
    ├── telecom_combined_score_index.json     # Per-conversation scores (combined 3k+6k)
    ├── sycophancy_llm_scores_v2_*.jsonl      # Per-conversation LLM scoring results
    └── sycophancy_llm_summary_v2_*.json      # Aggregate scoring summaries

tau2-bench/data/simulations/
├── baseline_qwen2.5-7b-instruct_results.json  # Baseline evaluation results
├── telecom_v2_0pct_results.json               # V2 SFT 0% results (88% tool error rate)
├── telecom_v2_10pct_results.json              # V2 SFT 10% results (80% tool error rate)
└── telecom_v2_20pct_results.json              # V2 SFT 20% results (83% tool error rate)
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

### CRITICAL: Agent vs User Tool Separation

τ²-Bench telecom has a **strict separation** between agent-callable and user-only tools:

**Agent Tools (13) — Training data should ONLY use these:**
```
get_customer_by_phone, get_customer_by_id, get_customer_by_name,
get_details_by_id, get_bills_for_customer, get_data_usage,
send_payment_request, enable_roaming, disable_roaming,
resume_line, suspend_line, refuel_data, transfer_to_human_agents
```

**User-Only Tools (30+) — Agent must GUIDE user verbally, NOT call these:**
```
toggle_airplane_mode, toggle_data, toggle_roaming, toggle_wifi,
check_status_bar, check_network_status, check_sim_status,
check_apn_settings, run_speed_test, reboot_device, reset_apn_settings,
reseat_sim_card, set_network_mode_preference, ... (and more)
```

**Correct agent behavior for troubleshooting:**
- Agent says: "Please toggle your airplane mode off and check if data works"
- Agent does NOT call: `toggle_airplane_mode()` as a tool

**Incorrect behavior (what V2 training data taught):**
- Agent calls: `toggle_airplane_mode()` → FAILS (tool not available to agent)
