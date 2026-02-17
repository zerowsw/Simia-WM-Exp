#!/bin/bash
# ==========================================================================
# Monitor tau2-bench evaluation progress in real-time
# ==========================================================================
# Usage:
#   bash Simia_SFT/sft_training/monitor_eval.sh [log_file]
#
# If no log file is given, uses the most recent telecom eval log.
# ==========================================================================

BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$REPO_ROOT/tau2-bench/logs"

# Find log file
if [ -n "$1" ]; then
    LOG_FILE="$1"
else
    LOG_FILE=$(ls -t "$LOG_DIR"/telecom_syc_*_eval_*.log 2>/dev/null | head -1)
fi

if [ -z "$LOG_FILE" ] || [ ! -f "$LOG_FILE" ]; then
    echo -e "${RED}No eval log found.${NC}"
    echo "Usage: $0 [log_file]"
    exit 1
fi

echo -e "${BLUE}Monitoring:${NC} $LOG_FILE"
echo -e "${BLUE}Press Ctrl+C to stop${NC}"
echo ""

while true; do
    clear

    # Header
    echo -e "${BLUE}══════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  tau2-bench Evaluation Monitor${NC}"
    echo -e "${BLUE}══════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}Log:${NC} $(basename "$LOG_FILE")"
    echo -e "${BLUE}Time:${NC} $(date '+%H:%M:%S')"
    echo ""

    # Current task
    LATEST=$(grep "Running task" "$LOG_FILE" | tail -1)
    if [ -n "$LATEST" ]; then
        echo -e "${YELLOW}Current:${NC} $LATEST"
    else
        echo -e "${YELLOW}Current:${NC} Waiting for tasks to start..."
    fi
    echo ""

    # Counts
    TOTAL_COMPLETED=$(grep -c "Reward:" "$LOG_FILE" 2>/dev/null || echo 0)
    PASSES=$(grep "Reward:" "$LOG_FILE" | grep -c "1.0000" 2>/dev/null || echo 0)
    FAILS=$((TOTAL_COMPLETED - PASSES))
    ERRORS=$(grep -c "^Task.*failed:" "$LOG_FILE" 2>/dev/null)
    ERRORS=${ERRORS:-0}
    ERRORS=$(echo "$ERRORS" | tr -d '[:space:]')

    echo -e "${GREEN}Completed:${NC} $TOTAL_COMPLETED / 342  (114 tasks x 3 trials)"
    if [ "$TOTAL_COMPLETED" -gt 0 ]; then
        PASS_RATE=$(awk "BEGIN {printf \"%.1f\", ($PASSES/$TOTAL_COMPLETED)*100}")
        echo -e "${GREEN}  Passed:${NC}  $PASSES  ($PASS_RATE%)"
        echo -e "${RED}  Failed:${NC}  $FAILS"
    fi
    if [ "$ERRORS" -gt 0 ]; then
        echo -e "${RED}  Errors:${NC}  $ERRORS"
    fi
    echo ""

    # Progress bar
    if [ "$TOTAL_COMPLETED" -gt 0 ]; then
        PCT=$((TOTAL_COMPLETED * 100 / 342))
        FILLED=$((PCT / 2))
        EMPTY=$((50 - FILLED))
        BAR=$(printf '█%.0s' $(seq 1 $FILLED 2>/dev/null) 2>/dev/null)
        SPACE=$(printf '░%.0s' $(seq 1 $EMPTY 2>/dev/null) 2>/dev/null)
        echo -e "  [${GREEN}${BAR}${NC}${SPACE}] ${PCT}%"
        echo ""
    fi

    # Last 5 rewards
    echo -e "${BLUE}Recent results:${NC}"
    grep "Reward:" "$LOG_FILE" | tail -5 | while read -r line; do
        if echo "$line" | grep -q "1.0000"; then
            echo -e "  ${GREEN}$line${NC}"
        else
            echo -e "  ${RED}$line${NC}"
        fi
    done
    echo ""

    # Check if process is still running
    if pgrep -f "tau2 run" > /dev/null 2>&1; then
        echo -e "${GREEN}Status: RUNNING${NC}"
    else
        echo -e "${YELLOW}Status: FINISHED (or not running)${NC}"
        # Show final summary if available
        SUMMARY=$(grep -A 20 "Results" "$LOG_FILE" | tail -20)
        if [ -n "$SUMMARY" ]; then
            echo ""
            echo -e "${BLUE}Final Summary:${NC}"
            echo "$SUMMARY"
        fi
        break
    fi

    sleep 10
done
