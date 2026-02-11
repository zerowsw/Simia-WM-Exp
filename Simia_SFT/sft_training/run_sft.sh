#!/bin/bash
# ==========================================================================
# Simia SFT Training Script
# ==========================================================================
# End-to-end pipeline: process data -> prepare for LLaMA Factory -> train
#
# Usage:
#   bash Simia_SFT/sft_training/run_sft.sh <input_json> [options]
#
# Examples:
#   # Full pipeline (process raw data + train)
#   bash Simia_SFT/sft_training/run_sft.sh Simia_SFT/Tau2/output/tau2_base_hardcase_200.json
#
#   # Skip processing (data already processed)
#   bash Simia_SFT/sft_training/run_sft.sh data_processed.json --skip-process
#
#   # Custom model and hyperparameters
#   bash Simia_SFT/sft_training/run_sft.sh data.json --model Qwen/Qwen3-8B --epochs 3
#
#   # Use a custom LLaMA Factory config directly
#   bash Simia_SFT/sft_training/run_sft.sh data.json --skip-process --config my_config.yaml
# ==========================================================================

set -e

# --------------- Color logging (matches process_data_pipeline.sh) ---------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

# --------------- Defaults ---------------
MODEL="Qwen/Qwen2.5-7B-Instruct"
TEMPLATE="qwen"
DATASET_NAME="tau2_sft"
EPOCHS=2
LR="0.000005"
BATCH_SIZE=1
GRAD_ACCUM=2
CUTOFF_LEN=12000
DEEPSPEED=""
SKIP_PROCESS=false
CUSTOM_CONFIG=""
OUTPUT_DIR=""
FINETUNING_TYPE="full"

# --------------- Parse arguments ---------------
usage() {
    echo "Usage: $0 <input_json> [options]"
    echo ""
    echo "Options:"
    echo "  --model           Model name or path (default: Qwen/Qwen2.5-7B-Instruct)"
    echo "  --template        Chat template (default: qwen)"
    echo "  --output-dir      Training output directory"
    echo "  --dataset-name    Dataset name (default: tau2_sft)"
    echo "  --epochs          Number of training epochs (default: 2)"
    echo "  --lr              Learning rate (default: 0.000005)"
    echo "  --batch-size      Per-device batch size (default: 1)"
    echo "  --grad-accum      Gradient accumulation steps (default: 2)"
    echo "  --cutoff-len      Max sequence length (default: 12000)"
    echo "  --finetuning-type Finetuning type: full or lora (default: full)"
    echo "  --deepspeed       Path to DeepSpeed config (optional)"
    echo "  --skip-process    Skip data processing step"
    echo "  --config          Path to custom LLaMA Factory YAML config (overrides all above)"
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

INPUT_FILE="$1"
shift

while [ $# -gt 0 ]; do
    case "$1" in
        --model)           MODEL="$2";           shift 2 ;;
        --template)        TEMPLATE="$2";        shift 2 ;;
        --output-dir)      OUTPUT_DIR="$2";      shift 2 ;;
        --dataset-name)    DATASET_NAME="$2";    shift 2 ;;
        --epochs)          EPOCHS="$2";          shift 2 ;;
        --lr)              LR="$2";              shift 2 ;;
        --batch-size)      BATCH_SIZE="$2";      shift 2 ;;
        --grad-accum)      GRAD_ACCUM="$2";      shift 2 ;;
        --cutoff-len)      CUTOFF_LEN="$2";      shift 2 ;;
        --finetuning-type) FINETUNING_TYPE="$2"; shift 2 ;;
        --deepspeed)       DEEPSPEED="$2";       shift 2 ;;
        --skip-process)    SKIP_PROCESS=true;    shift ;;
        --config)          CUSTOM_CONFIG="$2";   shift 2 ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

# --------------- Resolve paths ---------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

INPUT_FILE="$(realpath "$INPUT_FILE")"
if [ ! -f "$INPUT_FILE" ]; then
    log_error "Input file does not exist: $INPUT_FILE"
    exit 1
fi

# Default output dir
if [ -z "$OUTPUT_DIR" ]; then
    MODEL_BASENAME=$(basename "$MODEL")
    OUTPUT_DIR="$SCRIPT_DIR/saves/${MODEL_BASENAME}/${DATASET_NAME}"
fi
OUTPUT_DIR="$(mkdir -p "$OUTPUT_DIR" && realpath "$OUTPUT_DIR")"

# Working directory for dataset_info.json and generated configs
WORK_DIR="$SCRIPT_DIR/workdir/${DATASET_NAME}"
mkdir -p "$WORK_DIR"

log_info "========================================="
log_info "Simia SFT Training Pipeline"
log_info "========================================="
log_info "Input file:   $INPUT_FILE"
log_info "Model:        $MODEL"
log_info "Template:     $TEMPLATE"
log_info "Output dir:   $OUTPUT_DIR"
log_info "Skip process: $SKIP_PROCESS"

# --------------- Step 1: Data Processing ---------------
if [ "$SKIP_PROCESS" = false ]; then
    log_info ""
    log_info "========================================="
    log_info "Step 1/3: Processing raw data"
    log_info "========================================="

    DIR=$(dirname "$INPUT_FILE")
    BASENAME=$(basename "$INPUT_FILE" .json)
    PROCESSED_FILE="$DIR/${BASENAME}_processed.json"

    PIPELINE_SCRIPT="$REPO_ROOT/Simia_SFT/Tau2/process_data_pipeline.sh"
    if [ ! -f "$PIPELINE_SCRIPT" ]; then
        log_error "Processing pipeline not found: $PIPELINE_SCRIPT"
        exit 1
    fi

    bash "$PIPELINE_SCRIPT" "$INPUT_FILE" "$PROCESSED_FILE"

    if [ ! -f "$PROCESSED_FILE" ]; then
        log_error "Processing failed: output file not found: $PROCESSED_FILE"
        exit 1
    fi

    log_success "Data processed: $PROCESSED_FILE"
    INPUT_FILE="$PROCESSED_FILE"
else
    log_info ""
    log_info "Step 1/3: Skipping data processing (--skip-process)"
fi

# --------------- Step 2: Prepare for LLaMA Factory ---------------
log_info ""
log_info "========================================="
log_info "Step 2/3: Preparing data for LLaMA Factory"
log_info "========================================="

python3 "$SCRIPT_DIR/prepare_sft_data.py" \
    --input "$INPUT_FILE" \
    --dataset-name "$DATASET_NAME" \
    --output-dir "$WORK_DIR"

if [ ! -f "$WORK_DIR/dataset_info.json" ]; then
    log_error "Data preparation failed: dataset_info.json not created"
    exit 1
fi

log_success "dataset_info.json created at: $WORK_DIR/dataset_info.json"

# --------------- Step 3: Launch Training ---------------
log_info ""
log_info "========================================="
log_info "Step 3/3: Launching LLaMA Factory training"
log_info "========================================="

if [ -n "$CUSTOM_CONFIG" ]; then
    # Use custom config directly
    CUSTOM_CONFIG="$(realpath "$CUSTOM_CONFIG")"
    if [ ! -f "$CUSTOM_CONFIG" ]; then
        log_error "Custom config file not found: $CUSTOM_CONFIG"
        exit 1
    fi
    CONFIG_FILE="$CUSTOM_CONFIG"
    log_info "Using custom config: $CONFIG_FILE"
else
    # Generate config from CLI arguments
    CONFIG_FILE="$WORK_DIR/sft_config.yaml"

    # Build deepspeed line
    DEEPSPEED_LINE=""
    if [ -n "$DEEPSPEED" ]; then
        DEEPSPEED="$(realpath "$DEEPSPEED")"
        DEEPSPEED_LINE="deepspeed: ${DEEPSPEED}"
        log_info "DeepSpeed enabled: $DEEPSPEED"
    fi

    cat > "$CONFIG_FILE" << EOF
### model
model_name_or_path: ${MODEL}

### method
stage: sft
do_train: true
finetuning_type: ${FINETUNING_TYPE}
${DEEPSPEED_LINE}
flash_attn: fa2
neat_packing: true

### dataset
dataset: ${DATASET_NAME}
dataset_dir: ${WORK_DIR}
template: ${TEMPLATE}
overwrite_cache: true
preprocessing_num_workers: 32
cutoff_len: ${CUTOFF_LEN}

### output
output_dir: ${OUTPUT_DIR}
logging_steps: 1
save_steps: 50
plot_loss: true
overwrite_output_dir: true
save_only_model: true
report_to: none

### train
lr_scheduler_type: cosine
per_device_train_batch_size: ${BATCH_SIZE}
gradient_accumulation_steps: ${GRAD_ACCUM}
learning_rate: ${LR}
num_train_epochs: ${EPOCHS}
bf16: true
ddp_timeout: 180000000
EOF

    log_info "Generated config: $CONFIG_FILE"
fi

log_info "Starting training..."
llamafactory-cli train "$CONFIG_FILE"

log_success "========================================="
log_success "SFT Training completed!"
log_success "Model saved to: $OUTPUT_DIR"
log_success "========================================="
