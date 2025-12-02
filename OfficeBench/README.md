# OfficeBench Evaluation

This repository contains the evaluation code for OfficeBench (2-apps and 3-apps tasks), modified from the [official OfficeBench implementation](https://github.com/zlwang-cs/OfficeBench).

## Environment Setup

```bash
# Install dependencies
pip install -r requirements.txt
pip install vllm==0.8.5
pip install --force-reinstall numpy pandas scikit-learn

sudo apt install libreoffice
```

## How to Evaluate

Update experiment settings** in `run_models.sh`:

```bash
declare -a EXPERIMENTS=(
    "HF_Model Model-Pretty-Name Tag"
)
```


Results will be saved in `results/` and logs in `log/`.

## Differences from Official OfficeBench

Our internal implementation differs from the official OfficeBench codebase in the following ways:

| Change | Description |
|--------|-------------|
| **Think Step** | Added a think step before each tool call |
| **Local Execution** | Changed Docker-based execution to local execution for faster runtime (files are generated locally in `local_workdir/`) |
| **OCR Tasks Removed** | Removed OCR-related tasks from the benchmark |

## Important Notes

⚠️ **Local Path Generation**: Our SFT data format is based on the modified codebase above. As a result, the trained model [Simia-Agent/Simia-OfficeBench-SFT-Qwen3-8B](https://huggingface.co/Simia-Agent/Simia-OfficeBench-SFT-Qwen3-8B) may be overfitted to local execution paths, making **the generation format of our model different from that in the official OfficeBench implementation, resulting in different evaluation scores**.

⚠️ **High Variance**: There may be large variance in results, especially for **3-apps tasks**. We recommend running multiple evaluations to get reliable estimates.