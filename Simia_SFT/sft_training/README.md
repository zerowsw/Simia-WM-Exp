# SFT Training with LLaMA Factory

This directory provides an end-to-end SFT (Supervised Fine-Tuning) training pipeline using [LLaMA Factory](https://github.com/hiyouga/LLaMA-Factory). It takes the processed conversation data from `Simia_SFT/Tau2/` and fine-tunes a language model.

## Prerequisites

- LLaMA Factory installed (`pip install llamafactory`, already included in the Docker image)
- GPU(s) with sufficient VRAM (A100 80GB recommended for full fine-tuning of 7B models)
- Processed training data in ShareGPT format (output of `Simia_SFT/Tau2/process_data_pipeline.sh`)

## Quick Start

### Full Pipeline (process raw data + train)

```bash
bash Simia_SFT/sft_training/run_sft.sh Simia_SFT/Tau2/output/tau2_base_hardcase_200.json
```

### Skip Processing (data already processed)

```bash
bash Simia_SFT/sft_training/run_sft.sh path/to/processed_data.json --skip-process
```

### Custom Model and Hyperparameters

```bash
bash Simia_SFT/sft_training/run_sft.sh data.json \
    --model Qwen/Qwen3-8B \
    --template qwen \
    --epochs 3 \
    --lr 0.00001 \
    --batch-size 2
```

### Multi-GPU with DeepSpeed (required for A100-40GB)

For 8x A100-40GB, full fine-tuning of a 7B model requires DeepSpeed ZeRO-3 with CPU offloading to fit in memory:

```bash
bash Simia_SFT/sft_training/run_sft.sh Simia_SFT/Tau2/output/tau2_base_hardcase_200.json \
    --deepspeed Simia_SFT/sft_training/ds_zero3.json
```

ZeRO-2 (no CPU offloading, faster but needs more VRAM — suitable for A100-80GB):

```bash
bash Simia_SFT/sft_training/run_sft.sh Simia_SFT/Tau2/output/tau2_base_hardcase_200.json \
    --deepspeed Simia_SFT/sft_training/ds_zero2.json
```

### Telecom Sycophancy Experiment (single dataset)

```bash
bash Simia_SFT/sft_training/run_sft.sh \
    Simia_SFT/Tau2/output/telecom_syc_20pct_500_merged.json \
    --skip-process \
    --dataset-name telecom_syc_20pct \
    --epochs 3 \
    --deepspeed Simia_SFT/sft_training/ds_zero3.json
```

### Telecom Sycophancy Experiment (all 4 datasets)

Train all 4 controlled sycophancy variants (0%, 5%, 10%, 20%) with identical hyperparameters:

```bash
for pct in 0 5 10 20; do
    bash Simia_SFT/sft_training/run_sft.sh \
        Simia_SFT/Tau2/output/telecom_syc_${pct}pct_500_merged.json \
        --skip-process \
        --dataset-name "telecom_syc_${pct}pct" \
        --epochs 3 \
        --deepspeed Simia_SFT/sft_training/ds_zero3.json
done
```

### Telecom Sycophancy Experiment (end-to-end: train + evaluate)

Train all 4 variants and automatically evaluate each on the tau-bench telecom domain:

```bash
bash Simia_SFT/sft_training/run_telecom_sft_eval.sh
```

For each sycophancy proportion (0%, 5%, 10%, 20%), this script:
1. Trains a model via `run_sft.sh` (3 epochs, DeepSpeed ZeRO-3)
2. Starts a vLLM server hosting the trained model
3. Runs `tau2 run --domain telecom` (4 trials, gpt-4.1 user-llm)
4. Kills the vLLM server and moves to the next variant

**Prerequisites:**
- Merged data files: `Simia_SFT/Tau2/output/telecom_syc_{0,5,10,20}pct_500_merged.json`
- `tau2-bench/.env` with `OPENAI_API_KEY` (for the gpt-4.1 user-llm)
- vLLM installed and accessible

**Outputs:**
- Trained models: `saves/Qwen2.5-7B-Instruct/telecom_syc_{0,5,10,20}pct/`
- Evaluation logs: `tau2-bench/logs/telecom_syc_{0,5,10,20}pct_eval_<timestamp>.log`

### Use a Custom LLaMA Factory Config

```bash
bash Simia_SFT/sft_training/run_sft.sh data.json \
    --skip-process \
    --config path/to/my_config.yaml
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--model` | `Qwen/Qwen2.5-7B-Instruct` | Model name or HuggingFace path |
| `--template` | `qwen` | Chat template for tokenization |
| `--output-dir` | `saves/<model>/<dataset>` | Directory to save trained model |
| `--dataset-name` | `tau2_sft` | Dataset name for LLaMA Factory |
| `--epochs` | `2` | Number of training epochs |
| `--lr` | `0.000005` | Learning rate |
| `--batch-size` | `1` | Per-device train batch size |
| `--grad-accum` | `2` | Gradient accumulation steps |
| `--cutoff-len` | `12000` | Max sequence length |
| `--finetuning-type` | `full` | `full` or `lora` |
| `--deepspeed` | _(none)_ | Path to DeepSpeed config |
| `--skip-process` | `false` | Skip data processing step |
| `--config` | _(none)_ | Custom LLaMA Factory YAML (overrides all above) |

## Pipeline Steps

The `run_sft.sh` script runs three steps:

1. **Data Processing** (optional, skipped with `--skip-process`): Runs `Simia_SFT/Tau2/process_data_pipeline.sh` to convert raw generated data into the clean ShareGPT format (fix arguments, convert to Hermes format, correct tool calls, remove think tags, replace system prompts).

2. **Data Preparation**: Runs `prepare_sft_data.py` to validate the processed data and generate `dataset_info.json` that LLaMA Factory needs to locate the dataset.

3. **Training**: Launches `llamafactory-cli train` with either a generated config (from CLI arguments) or a custom YAML config.

## Files

| File | Description |
|------|-------------|
| `run_sft.sh` | Main entry point - end-to-end pipeline script |
| `run_telecom_sft_eval.sh` | Trains all 4 telecom sycophancy variants and evaluates each on tau-bench |
| `prepare_sft_data.py` | Validates data and writes `dataset_info.json` |
| `sft_config.yaml` | Reference LLaMA Factory training config |
| `ds_zero2.json` | DeepSpeed ZeRO-2 config (A100-80GB) |
| `ds_zero3.json` | DeepSpeed ZeRO-3 config with CPU offloading (A100-40GB) |

## Data Format

The training data should be in ShareGPT format (produced by `process_data_pipeline.sh`):

```json
[
  {
    "conversations": [
      {"from": "human", "value": "User message"},
      {"from": "gpt", "value": "Assistant response"},
      ...
    ],
    "system": "System prompt with policy and tools"
  }
]
```

### Airline/Retail vs Telecom Format Differences

The **airline/retail** data (e.g., `tau2_base_hardcase_200.json`) uses explicit tool-calling roles:
- Tool calls: `"from": "function_call"` with `<think>...</think>\n{"name": ..., "arguments": {...}}`
- Tool responses: `"from": "observation"` with JSON result

The **telecom** data (e.g., `telecom_syc_*_processed.json`) encodes tool calls within standard roles:
- Tool calls: `"from": "gpt"` with `<tool_call>{"name": ..., "arguments": {...}}</tool_call>`
- Tool responses: `"from": "human"` with JSON result

### Known Issue: Consecutive Same-Role Turns in Telecom Data (TO FIX)

The telecom `*_processed.json` files have **consecutive `gpt` turns** — the assistant sends a text message and then immediately makes a tool call in a separate turn, both with `"from": "gpt"`. This pattern appears in 483/500 conversations (1676 total consecutive pairs). Additionally, 28 conversations end with a trailing `human` turn (odd turn count).

LLaMA Factory's ShareGPT converter (`llamafactory/data/converter.py`, `SharegptDatasetConverter`) enforces **strictly alternating roles**: odd positions must be `human`/`observation`, even positions must be `gpt`/`function_call`. When consecutive same-role turns are encountered, the converter marks them as `broken_data` and sets `_prompt = [], _response = []`. This causes a `ValueError` during HuggingFace dataset concatenation because the empty lists are inferred as `List(Value('null'))` instead of the expected `List({'content': Value('string'), 'role': Value('string')})`.

**To fix**, the data must be preprocessed before training:
1. **Merge consecutive same-role turns** by concatenating their `value` fields with a newline separator.
2. **Trim trailing `human` turns** so every conversation ends with a `gpt` turn (even turn count).


quick way to fix:

```
#!/usr/bin/env python3
"""
Merge consecutive same-role turns in ShareGPT format data.

LLaMA Factory's ShareGPT converter requires strictly alternating roles
(human/observation at odd positions, gpt/function_call at even positions).
The telecom data has consecutive gpt turns (text message followed by tool call),
which breaks this requirement. This script merges them into single turns.

Usage:
    python merge_consecutive_turns.py --input data.json --output data_merged.json
"""

import argparse
import json


def merge_consecutive_turns(conversations):
    """Merge consecutive same-role turns by concatenating their values."""
    if not conversations:
        return conversations

    merged = [conversations[0].copy()]
    for turn in conversations[1:]:
        if turn["from"] == merged[-1]["from"]:
            merged[-1]["value"] += "\n" + turn["value"]
        else:
            merged.append(turn.copy())
    return merged


def main():
    parser = argparse.ArgumentParser(
        description="Merge consecutive same-role turns in ShareGPT data"
    )
    parser.add_argument("--input", required=True, help="Input JSON file")
    parser.add_argument("--output", required=True, help="Output JSON file")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_before = 0
    total_after = 0
    merged_count = 0
    trimmed_count = 0

    for item in data:
        convs = item["conversations"]
        total_before += len(convs)
        merged = merge_consecutive_turns(convs)
        if len(merged) != len(convs):
            merged_count += 1
        # LLaMA Factory requires even turn count (ending with gpt).
        # Drop trailing human turn if present.
        if len(merged) % 2 != 0 and merged[-1]["from"] == "human":
            merged = merged[:-1]
            trimmed_count += 1
        total_after += len(merged)
        item["conversations"] = merged

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Processed {len(data)} conversations")
    print(f"Merged consecutive turns in {merged_count} conversations")
    print(f"Trimmed trailing human turn in {trimmed_count} conversations")
    print(f"Total turns: {total_before} -> {total_after} ({total_before - total_after} removed)")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
```

## Step-by-Step Manual Usage

If you prefer to run each step manually instead of using `run_sft.sh`:

### 1. Process raw data

```bash
bash Simia_SFT/Tau2/process_data_pipeline.sh input.json output_processed.json
```

### 2. Prepare dataset_info.json

```bash
python Simia_SFT/sft_training/prepare_sft_data.py \
    --input output_processed.json \
    --dataset-name tau2_sft \
    --output-dir ./workdir
```

### 3. Create your training config

Edit `sft_config.yaml` and set `dataset_dir` to point to the directory containing `dataset_info.json`:

```yaml
dataset: tau2_sft
dataset_dir: ./workdir
```

### 4. Launch training

```bash
llamafactory-cli train sft_config.yaml
```

## Notes

- **Template must match model**: If you change the model (e.g., to Llama-3), update the `--template` accordingly (e.g., `llama3`). See [LLaMA Factory templates](https://github.com/hiyouga/LLaMA-Factory/blob/main/src/llamafactory/data/template.py).
- **cutoff_len**: The default `12000` should cover most Tau2 conversations. If you see truncation warnings, increase this value.
- **LoRA**: Pass `--finetuning-type lora` for parameter-efficient fine-tuning, which requires significantly less VRAM.
- **Wandb logging**: Set `WANDB_API_KEY` environment variable and add `report_to: wandb` to your config for experiment tracking.
