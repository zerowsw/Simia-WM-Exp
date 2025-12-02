#!/bin/bash


# ==============================================
# Configuration Section - Define triplet array (model_name model_pretty_name tag)
# ==============================================
declare -a EXPERIMENTS=(
    "Simia-Agent/Simia-OfficeBench-SFT-Qwen3-8B Simia-OfficeBench-SFT-Qwen3-8B eval_1201"
)

MAIN_TIMESTAMP=$(date +%Y-%m-%d:%H:%M:%S)
MAIN_LOG_FILE="log/main_log_${MAIN_TIMESTAMP}.log"

echo "=============================================="
echo "Starting batch automated experiment runs"
echo "Time: ${MAIN_TIMESTAMP}"
echo "Total experiments: ${#EXPERIMENTS[@]}"
echo "Main log file: ${MAIN_LOG_FILE}"
echo "=============================================="

# Ensure log directory exists
mkdir -p log

# Iterate through all experiment configurations
for i in "${!EXPERIMENTS[@]}"; do
    # Parse triplet
    IFS=' ' read -r model_name model_pretty_name tag <<< "${EXPERIMENTS[$i]}"
    
    # Generate model_name_short
    model_name_short="$model_pretty_name"
    
    TIMESTAMP=$(date +%Y-%m-%d:%H:%M:%S)
    LOG_FILE="log/log_${model_pretty_name}_${tag}_${TIMESTAMP}.log"
    
    echo ""
    echo "=============================================="
    echo "Experiment $((i+1))/${#EXPERIMENTS[@]} - Starting"
    echo "Time: ${TIMESTAMP}"
    echo "Model: ${model_name}"
    echo "Model short name: ${model_name_short}"
    echo "Tag: ${tag}"
    echo "Log file: ${LOG_FILE}"
    echo "=============================================="
    
    {
        echo "=============================================="
        echo "Experiment $((i+1))/${#EXPERIMENTS[@]} - Configuration Info"
        echo "Model: ${model_name}"
        echo "Model short name: ${model_name_short}"
        echo "Tag: ${tag}"
        echo "Start time: ${TIMESTAMP}"
        echo "=============================================="
        
        # ==============================================
        # Auto-update configuration files
        # ==============================================
        
        echo "Auto-updating configuration files..."
        
        # 1. Update configs/models.yaml - Add model configuration (if not exists)
        echo "1. Updating configs/models.yaml"
        if ! grep -q "  ${model_name_short}:" configs/models.yaml; then
            echo "  ${model_name_short}:" >> configs/models.yaml
            echo "    name: \"${model_name}\"" >> configs/models.yaml
            echo "   ✓ Added new model configuration"
        else
            echo "   ✓ Model configuration already exists"
        fi
        
        # 2. Update configuration in run_all.py
        echo "2. Updating run_all.py"
        sed -i "s/tag = '.*'/tag = '${tag}'/g" run_all.py
        sed -i "s/model_name_short = '.*'/model_name_short = '${model_name_short}'/g" run_all.py
        echo "   ✓ Updated configuration in run_all.py"
        
        echo "=============================================="
        echo "Configuration update complete, starting experiment..."
        echo "=============================================="
        
        # Run main script
        echo "Running run_all.py..."
        python run_all.py --generate-config 
        
        echo "=============================================="
        echo "run_all.py completed"
        echo "=============================================="
        
        python -m evaluation.main --tag_name ${tag} --model_name ${model_name}

        
        echo "=============================================="
        echo "Experiment $((i+1))/${#EXPERIMENTS[@]} completed - Time: $(date +%Y-%m-%d:%H:%M:%S)"
        echo "=============================================="
        
    } 2>&1 | tee -a ${LOG_FILE} | tee -a ${MAIN_LOG_FILE}
    
    echo ""
    echo "✅ Experiment $((i+1))/${#EXPERIMENTS[@]} completed"
    echo "   Model: ${model_name}"
    echo "   Tag: ${tag}"
    echo "   Log: ${LOG_FILE}"
    echo ""
    
done

echo "=============================================="
echo "🎉 All experiments completed!"
echo "Total experiments: ${#EXPERIMENTS[@]}"
echo "Completion time: $(date +%Y-%m-%d:%H:%M:%S)"
echo "Main log file: ${MAIN_LOG_FILE}"
echo "=============================================="