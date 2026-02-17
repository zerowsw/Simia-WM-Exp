#!/bin/bash
# ==========================================================================
# Telecom SFT Evaluation (Single Model)
# ==========================================================================
# Evaluate the SFT 10% sycophancy (920-sample) model on tau2-bench telecom.
#
#   GPU 0: SFT 10% sycophancy (920)    port 8000
#
# Usage:
#   bash Simia_SFT/sft_training/run_telecom_sft_eval.sh
#
# Prerequisites:
#   - Trained model at saves/Qwen2.5-7B-Instruct/telecom_syc_10pct_920/
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
SAVES_DIR="$SCRIPT_DIR/saves/Qwen2.5-7B-Instruct"

LABEL="telecom_syc_10pct_920"
MODEL_PATH="$SAVES_DIR/$LABEL"
GPU_ID=0
PORT=8000

# --------------- Preflight checks ---------------
log_info "========================================="
log_info "Telecom SFT Evaluation: $LABEL"
log_info "========================================="

# Check trained model exists
if [ ! -d "$MODEL_PATH" ] || [ ! -f "$MODEL_PATH/config.json" ]; then
    log_error "Trained model not found at $MODEL_PATH"
    exit 1
fi
log_success "Trained model found: $MODEL_PATH"

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
# Start vLLM server
# ================================================================

# Kill any leftover vLLM processes
pkill -9 -f "vllm serve" 2>/dev/null || true
sleep 3

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$TAU2_BENCH_DIR/logs"

log_info "Starting vLLM server..."
log_info "  [$LABEL] GPU=$GPU_ID PORT=$PORT MODEL=$MODEL_PATH"

CUDA_VISIBLE_DEVICES=$GPU_ID vllm serve "$MODEL_PATH" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --max-model-len 16000 \
    --gpu-memory-utilization 0.85 \
    --tensor-parallel-size 1 \
    --dtype auto \
    --enable-auto-tool-choice \
    --tool-call-parser hermes \
    > "$TAU2_BENCH_DIR/logs/vllm_${LABEL}_${TIMESTAMP}.log" 2>&1 &

# --- Wait for server to be healthy ---
log_info "Waiting for vLLM server to be ready..."
sleep 30

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
    pkill -9 -f "vllm serve" 2>/dev/null || true
    exit 1
fi

# ================================================================
# Run tau2 evaluation
# ================================================================
EVAL_LOG="$TAU2_BENCH_DIR/logs/${LABEL}_eval_${TIMESTAMP}.log"
log_info "Launching tau2 evaluation -> $EVAL_LOG"

VLLM_API_BASE="http://localhost:${PORT}/v1" \
tau2 run \
    --domain telecom \
    --agent-llm "openai/$MODEL_PATH" \
    --user-llm gpt-4.1 \
    --num-trials 3 \
    --max-concurrency 6 \
    > "$EVAL_LOG" 2>&1

EVAL_EXIT=$?

# --- Cleanup: kill vLLM server ---
log_info "Stopping vLLM server..."
pkill -9 -f "vllm serve" 2>/dev/null || true
sleep 3

# --- Summary ---
log_info ""
log_info "========================================="
log_info "EXPERIMENT SUMMARY"
log_info "========================================="
log_info "Evaluation log: $EVAL_LOG"

if [ "$EVAL_EXIT" -eq 0 ]; then
    log_success ""
    log_success "##############################################"
    log_success "  $LABEL evaluated successfully!"
    log_success "##############################################"
    echo ""
    log_info "Results (last 20 lines of log):"
    tail -20 "$EVAL_LOG"
else
    log_error ""
    log_error "##############################################"
    log_error "  Evaluation failed! Check: $EVAL_LOG"
    log_error "##############################################"
    exit 1
fi
