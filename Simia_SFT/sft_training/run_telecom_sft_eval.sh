#!/bin/bash
# ==========================================================================
# Telecom SFT Training + Tau-Bench Evaluation
# ==========================================================================
# Phase 1: Train 4 SFT models sequentially (all GPUs via DeepSpeed ZeRO-3)
# Phase 2: Evaluate 5 models in parallel (1 GPU each, 5 concurrent vLLM servers)
#
#   GPU 0: Baseline Qwen2.5-7B-Instruct (no SFT)     port 8000
#   GPU 1: SFT 0% sycophancy                          port 8001
#   GPU 2: SFT 5% sycophancy                          port 8002
#   GPU 3: SFT 10% sycophancy                         port 8003
#   GPU 4: SFT 20% sycophancy                         port 8004
#
# Usage:
#   bash Simia_SFT/sft_training/run_telecom_sft_eval.sh
#
# Prerequisites:
#   - Merged SFT data in Simia_SFT/Tau2/output/telecom_syc_{pct}pct_1000_merged.json
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
BASE_MODEL="Qwen/Qwen2.5-7B-Instruct"

SYCOPHANCY_PCTS=(0 5 10 20)

# --------------- Preflight checks ---------------
log_info "========================================="
log_info "Telecom SFT + Tau-Bench Evaluation (5 models)"
log_info "========================================="

# Check that all input data files exist
for pct in "${SYCOPHANCY_PCTS[@]}"; do
    INPUT_FILE="$DATA_DIR/telecom_syc_${pct}pct_1000_merged.json"
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

# Load env vars for user-llm (gpt-4.1 via OpenRouter or OpenAI)
if [ -f "$TAU2_BENCH_DIR/.env" ]; then
    source "$TAU2_BENCH_DIR/.env" 2>/dev/null || true
fi
if [ -z "$OPENAI_API_KEY" ]; then
    log_warning "OPENAI_API_KEY not set. Evaluation will fail without it."
fi

# ================================================================
# PHASE 1: SFT Training (sequential, all GPUs via DeepSpeed)
# ================================================================
log_info ""
log_info "========================================="
log_info "PHASE 1: SFT Training (4 models)"
log_info "========================================="

for pct in "${SYCOPHANCY_PCTS[@]}"; do
    DATASET_NAME="telecom_syc_${pct}pct"
    INPUT_FILE="$DATA_DIR/telecom_syc_${pct}pct_1000_merged.json"
    MODEL_OUTPUT_DIR="$SAVES_DIR/$DATASET_NAME"

    if [ -d "$MODEL_OUTPUT_DIR" ] && [ -f "$MODEL_OUTPUT_DIR/config.json" ]; then
        log_warning "[${pct}%] Model already exists at $MODEL_OUTPUT_DIR — skipping"
    else
        log_info "[${pct}%] Training SFT model: $DATASET_NAME"

        bash "$SCRIPT_DIR/run_sft.sh" "$INPUT_FILE" \
            --skip-process \
            --dataset-name "$DATASET_NAME" \
            --epochs 3 \
            --deepspeed "$SCRIPT_DIR/ds_zero3.json"

        if [ ! -d "$MODEL_OUTPUT_DIR" ] || [ ! -f "$MODEL_OUTPUT_DIR/config.json" ]; then
            log_error "Training failed for $DATASET_NAME"
            exit 1
        fi
        log_success "[${pct}%] Training complete: $MODEL_OUTPUT_DIR"
    fi
done

log_success "PHASE 1 complete: all 4 SFT models trained"

# ================================================================
# PHASE 2: Parallel Evaluation (5 models, 5 GPUs, 5 vLLM servers)
# ================================================================
log_info ""
log_info "========================================="
log_info "PHASE 2: Parallel Evaluation (5 models)"
log_info "========================================="

# Kill any leftover vLLM processes
pkill -9 -f "vllm serve" 2>/dev/null || true
sleep 3

# Define the 5 models: label, model_path, gpu_id, port
LABELS=("baseline_qwen2.5-7b" "telecom_syc_0pct" "telecom_syc_5pct" "telecom_syc_10pct" "telecom_syc_20pct")
MODEL_PATHS=("$BASE_MODEL" "$SAVES_DIR/telecom_syc_0pct" "$SAVES_DIR/telecom_syc_5pct" "$SAVES_DIR/telecom_syc_10pct" "$SAVES_DIR/telecom_syc_20pct")
GPU_IDS=(0 1 2 3 4)
PORTS=(8000 8001 8002 8003 8004)

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$TAU2_BENCH_DIR/logs"

# --- Start all 5 vLLM servers ---
log_info "Starting 5 vLLM servers..."

for i in "${!LABELS[@]}"; do
    LABEL="${LABELS[$i]}"
    MODEL="${MODEL_PATHS[$i]}"
    GPU="${GPU_IDS[$i]}"
    PORT="${PORTS[$i]}"

    log_info "  [$LABEL] GPU=$GPU PORT=$PORT MODEL=$MODEL"

    CUDA_VISIBLE_DEVICES=$GPU vllm serve "$MODEL" \
        --host 0.0.0.0 \
        --port "$PORT" \
        --max-model-len 16000 \
        --gpu-memory-utilization 0.85 \
        --tensor-parallel-size 1 \
        --dtype auto \
        --enable-auto-tool-choice \
        --tool-call-parser hermes \
        > "$TAU2_BENCH_DIR/logs/vllm_${LABEL}_${TIMESTAMP}.log" 2>&1 &
done

# --- Wait for all servers to be healthy ---
log_info "Waiting for all 5 vLLM servers to be ready..."
sleep 30

ALL_READY=true
for i in "${!LABELS[@]}"; do
    LABEL="${LABELS[$i]}"
    PORT="${PORTS[$i]}"
    SERVER_READY=false

    for attempt in $(seq 1 50); do
        if curl -s "http://localhost:${PORT}/health" > /dev/null 2>&1; then
            log_success "  [$LABEL] Server ready on port $PORT"
            SERVER_READY=true
            break
        else
            if [ $((attempt % 5)) -eq 0 ]; then
                log_info "  [$LABEL] Waiting... ($attempt/50)"
            fi
            sleep 10
        fi
    done

    if [ "$SERVER_READY" = false ]; then
        log_error "  [$LABEL] Server failed to start on port $PORT"
        ALL_READY=false
    fi
done

if [ "$ALL_READY" = false ]; then
    log_error "Some servers failed to start. Cleaning up..."
    pkill -9 -f "vllm serve" 2>/dev/null || true
    exit 1
fi

log_success "All 5 vLLM servers are ready"

# --- Launch all 5 tau2 evaluations in parallel ---
log_info "Launching 5 tau2 evaluations in parallel..."

EVAL_PIDS=()
for i in "${!LABELS[@]}"; do
    LABEL="${LABELS[$i]}"
    MODEL="${MODEL_PATHS[$i]}"
    PORT="${PORTS[$i]}"
    EVAL_LOG="$TAU2_BENCH_DIR/logs/${LABEL}_eval_${TIMESTAMP}.log"

    log_info "  [$LABEL] Starting evaluation -> $EVAL_LOG"

    VLLM_API_BASE="http://localhost:${PORT}/v1" \
    tau2 run \
        --domain telecom \
        --agent-llm "openai/$MODEL" \
        --user-llm gpt-4.1 \
        --num-trials 3 \
        --max-concurrency 6 \
        > "$EVAL_LOG" 2>&1 &

    EVAL_PIDS+=($!)
done

log_info "All 5 evaluations launched. PIDs: ${EVAL_PIDS[*]}"
log_info "Waiting for all evaluations to complete..."

# --- Wait for all evaluations and collect exit codes ---
FAILED=0
for i in "${!LABELS[@]}"; do
    LABEL="${LABELS[$i]}"
    PID="${EVAL_PIDS[$i]}"
    EVAL_LOG="$TAU2_BENCH_DIR/logs/${LABEL}_eval_${TIMESTAMP}.log"

    if wait "$PID"; then
        log_success "  [$LABEL] Evaluation complete (PID $PID)"
    else
        log_error "  [$LABEL] Evaluation failed (PID $PID). Check: $EVAL_LOG"
        FAILED=$((FAILED + 1))
    fi
done

# --- Cleanup: kill all vLLM servers ---
log_info "Stopping all vLLM servers..."
pkill -9 -f "vllm serve" 2>/dev/null || true
sleep 3

# --- Summary ---
log_info ""
log_info "========================================="
log_info "EXPERIMENT SUMMARY"
log_info "========================================="
log_info "Evaluation logs:"
for i in "${!LABELS[@]}"; do
    LABEL="${LABELS[$i]}"
    EVAL_LOG="$TAU2_BENCH_DIR/logs/${LABEL}_eval_${TIMESTAMP}.log"
    log_info "  [$LABEL] $EVAL_LOG"
done

if [ "$FAILED" -eq 0 ]; then
    log_success ""
    log_success "##############################################"
    log_success "  All 5 models evaluated successfully!"
    log_success "##############################################"
else
    log_error ""
    log_error "##############################################"
    log_error "  $FAILED evaluation(s) failed!"
    log_error "##############################################"
    exit 1
fi
