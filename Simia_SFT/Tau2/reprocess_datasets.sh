#!/bin/bash
# Reprocess all 3 SFT datasets with the updated pipeline (includes split_embedded_human).
# Then apply merge_consecutive_turns for LLaMA Factory compatibility.
#
# Usage: bash Simia_SFT/Tau2/reprocess_datasets.sh [SIZE]
# Default SIZE=920

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_DIR="$SCRIPT_DIR/output"
MERGE_SCRIPT="$REPO_ROOT/Simia_SFT/sft_training/merge_consecutive_turns.py"
PIPELINE_SCRIPT="$SCRIPT_DIR/process_data_pipeline.sh"

SIZE="${1:-920}"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

PCTS=(0 5 10)

for pct in "${PCTS[@]}"; do
    RAW="$DATA_DIR/telecom_syc_${pct}pct_${SIZE}.json"
    PROCESSED="$DATA_DIR/telecom_syc_${pct}pct_${SIZE}_processed.json"
    MERGED="$DATA_DIR/telecom_syc_${pct}pct_${SIZE}_merged.json"

    if [ ! -f "$RAW" ]; then
        log_error "Missing raw dataset: $RAW"
        exit 1
    fi

    log_info "==========================================="
    log_info "Processing ${pct}% sycophancy dataset (size=${SIZE})"
    log_info "==========================================="

    # Step 1: Run updated pipeline (split_embedded_human + fix_arguments + tool2hermes + tool_correct + remove_think_tag + replace_system_prompt)
    log_info "Running pipeline..."
    bash "$PIPELINE_SCRIPT" "$RAW" "$PROCESSED"

    # Step 2: Merge remaining consecutive same-role turns
    log_info "Running merge_consecutive_turns..."
    python3 "$MERGE_SCRIPT" --input "$PROCESSED" --output "$MERGED"

    log_success "${pct}% dataset complete: $MERGED"
    echo
done

# Validate all outputs
log_info "==========================================="
log_info "Validation"
log_info "==========================================="

python3 -c "
import json

pcts = [0, 5, 10]
size = $SIZE
for pct in pcts:
    path = f'$DATA_DIR/telecom_syc_{pct}pct_{size}_merged.json'
    with open(path) as f:
        data = json.load(f)

    # Check alternation
    bad_alt = 0
    embedded_human = 0
    for item in data:
        convs = item['conversations']
        for i in range(1, len(convs)):
            if convs[i]['from'] == convs[i-1]['from']:
                bad_alt += 1
        for t in convs:
            if t['from'] == 'gpt' and 'HUMAN:' in t['value']:
                embedded_human += 1

    total_turns = sum(len(item['conversations']) for item in data)
    print(f'{pct}%: {len(data)} convs, {total_turns} turns, {bad_alt} non-alternating, {embedded_human} gpt+HUMAN:')
"

log_success "All 3 datasets reprocessed successfully"
