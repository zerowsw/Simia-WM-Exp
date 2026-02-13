#!/bin/bash
# ==========================================================================
# Telecom SFT Training + Tau-Bench Evaluation
# ==========================================================================
# For each sycophancy proportion (0%, 5%, 10%, 20%), trains a model via
# run_sft.sh and evaluates it on the tau-bench telecom domain.
#
# Usage:
#   bash Simia_SFT/sft_training/run_telecom_sft_eval.sh
#
# Prerequisites:
#   - Merged SFT data in Simia_SFT/Tau2/output/telecom_syc_{pct}pct_500_merged.json
#   - tau2-bench/.env with OPENAI_API_KEY (for gpt-4.1 user-llm)
#   - vLLM installed and accessible
# ==========================================================================

set -e

# --------------- Color logging ---------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

# --------------- Resolve paths ---------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TAU2_BENCH_DIR="$REPO_ROOT/tau2-bench"
DATA_DIR="$REPO_ROOT/Simia_SFT/Tau2/output"
SAVES_DIR="$SCRIPT_DIR/saves/Qwen2.5-7B-Instruct"

SYCOPHANCY_PCTS=(0 5 10 20)

# --------------- Preflight checks ---------------
log_info "========================================="
log_info "Telecom SFT + Tau-Bench Evaluation"
log_info "========================================="

# Check that all input data files exist
for pct in "${SYCOPHANCY_PCTS[@]}"; do
    INPUT_FILE="$DATA_DIR/telecom_syc_${pct}pct_500_merged.json"
    if [ ! -f "$INPUT_FILE" ]; then
        log_error "Missing input file: $INPUT_FILE"
        exit 1
    fi
done
log_success "All 4 input data files found"

# Check run_sft.sh exists
if [ ! -f "$SCRIPT_DIR/run_sft.sh" ]; then
    log_error "run_sft.sh not found at $SCRIPT_DIR/run_sft.sh"
    exit 1
fi

# Check tau2-bench directory
if [ ! -d "$TAU2_BENCH_DIR" ]; then
    log_error "tau2-bench directory not found at $TAU2_BENCH_DIR"
    exit 1
fi

# Load OPENAI_API_KEY for user-llm (gpt-4.1)
if [ -f "$TAU2_BENCH_DIR/.env" ]; then
    source "$TAU2_BENCH_DIR/.env" 2>/dev/null || true
fi
if [ -z "$OPENAI_API_KEY" ]; then
    log_warning "OPENAI_API_KEY not set. Evaluation will fail without it."
fi

# Set vLLM API base for tau2 evaluation
export VLLM_API_BASE="http://localhost:8000/v1"

# Portable sed -i
if [[ "$(uname)" == "Darwin" ]]; then
    SED_INPLACE=(sed -i '')
else
    SED_INPLACE=(sed -i)
fi

# --------------- Main loop ---------------
for pct in "${SYCOPHANCY_PCTS[@]}"; do
    DATASET_NAME="telecom_syc_${pct}pct"
    INPUT_FILE="$DATA_DIR/telecom_syc_${pct}pct_500_merged.json"
    MODEL_OUTPUT_DIR="$SAVES_DIR/$DATASET_NAME"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)

    log_info ""
    log_info "##############################################"
    log_info "  Processing: ${pct}% sycophancy dataset"
    log_info "##############################################"

    # ============================================================
    # Step 1: SFT Training (skip if model already exists)
    # ============================================================
    if [ -d "$MODEL_OUTPUT_DIR" ] && [ -f "$MODEL_OUTPUT_DIR/config.json" ]; then
        log_warning "Step 1/3: Model already exists at $MODEL_OUTPUT_DIR — skipping training"
    else
        log_info "Step 1/3: SFT Training for $DATASET_NAME"

        bash "$SCRIPT_DIR/run_sft.sh" "$INPUT_FILE" \
            --skip-process \
            --dataset-name "$DATASET_NAME" \
            --epochs 3 \
            --deepspeed "$SCRIPT_DIR/ds_zero3.json"

        if [ ! -d "$MODEL_OUTPUT_DIR" ]; then
            log_error "Training failed: model output dir not found at $MODEL_OUTPUT_DIR"
            exit 1
        fi
        log_success "Training complete: $MODEL_OUTPUT_DIR"
    fi

    # ============================================================
    # Step 2: Start vLLM server with trained model
    # ============================================================
    log_info "Step 2/3: Starting vLLM server for $DATASET_NAME"

    # Update vllm_server_config.yaml to point to the trained model
    VLLM_CONFIG="$TAU2_BENCH_DIR/vllm_server_config.yaml"

    # Set model path to the local trained model
    "${SED_INPLACE[@]}" "s|^model:.*|model: $MODEL_OUTPUT_DIR|" "$VLLM_CONFIG"

    # Set tool-call-parser to hermes (Qwen2.5)
    "${SED_INPLACE[@]}" "/^tool-call-parser:/d" "$VLLM_CONFIG"
    "${SED_INPLACE[@]}" "/^tool-parser-plugin:/d" "$VLLM_CONFIG"
    echo "tool-call-parser: hermes" >> "$VLLM_CONFIG"

    # Remove chat-template (not needed for Qwen2.5-Instruct)
    "${SED_INPLACE[@]}" "/^chat-template:/d" "$VLLM_CONFIG"

    # Kill any existing vLLM process
    log_info "Stopping existing vLLM processes..."
    pkill -f "vllm serve" 2>/dev/null || true
    sleep 5

    # Start vLLM server
    log_info "Launching vLLM server..."
    cd "$TAU2_BENCH_DIR"
    bash host_server.sh &
    cd "$REPO_ROOT"

    # Health-check loop
    log_info "Waiting for vLLM server to be ready..."
    sleep 30
    SERVER_READY=false
    for i in {1..50}; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            log_success "vLLM server is ready"
            SERVER_READY=true
            break
        else
            log_info "Waiting for server... ($i/50)"
            sleep 10
        fi
    done

    if [ "$SERVER_READY" = false ]; then
        log_error "vLLM server failed to start for $DATASET_NAME"
        pkill -f "vllm serve" 2>/dev/null || true
        exit 1
    fi

    # ============================================================
    # Step 3: Run tau-bench telecom evaluation
    # ============================================================
    log_info "Step 3/3: Running tau-bench telecom evaluation for $DATASET_NAME"

    mkdir -p "$TAU2_BENCH_DIR/logs"
    EVAL_LOG="$TAU2_BENCH_DIR/logs/telecom_syc_${pct}pct_eval_${TIMESTAMP}.log"

    tau2 run \
        --domain telecom \
        --agent-llm "openai/$MODEL_OUTPUT_DIR" \
        --user-llm gpt-4.1 \
        --num-trials 4 \
        --max-concurrency 6 2>&1 | tee "$EVAL_LOG"

    log_success "Evaluation complete for $DATASET_NAME. Log: $EVAL_LOG"

    # ============================================================
    # Cleanup: kill vLLM server before next iteration
    # ============================================================
    log_info "Stopping vLLM server..."
    pkill -f "vllm serve" 2>/dev/null || true
    sleep 5

    log_success "Finished ${pct}% sycophancy variant"
done

log_success ""
log_success "##############################################"
log_success "  All 4 variants complete!"
log_success "##############################################"
log_info "Trained models: $SAVES_DIR/telecom_syc_{0,5,10,20}pct/"
log_info "Evaluation logs: $TAU2_BENCH_DIR/logs/telecom_syc_*_eval_*.log"
