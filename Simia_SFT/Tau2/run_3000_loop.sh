#!/bin/bash
cd /Volumes/workplace/Simia-WM-Exp/Simia_SFT/Tau2

TARGET=3000
CONFIG=config_telecom_base_3000.json

while true; do
    COUNT=$(python3 -c "
import json
try:
    with open('output/tau2_telecom_base_3000_progress.json') as f:
        d = json.load(f)
    count = len(d) if isinstance(d, list) else len(next(v for v in d.values() if isinstance(v, list)))
    print(count)
except:
    print(0)
" 2>/dev/null)
    
    echo "$(date): Current count: $COUNT/$TARGET"
    
    if [ "$COUNT" -ge "$TARGET" ]; then
        echo "Target reached!"
        break
    fi
    
    echo "$(date): Starting/resuming generation..."
    python3 main.py --config $CONFIG --auto-resume 2>&1 | tail -5
    
    echo "$(date): Run ended. Checking progress..."
    sleep 5
done
