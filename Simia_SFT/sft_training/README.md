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
