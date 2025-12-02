# running all tasks from the folder
import argparse
import shutil
import os
from agent_interact import main
from pathlib import Path
from generate_run_config import main as generate_run_config
from ruamel.yaml import YAML
from utils.constants import *
from tqdm import tqdm

import logging
yaml = YAML()
yaml.preserve_quotes = True  # Preserve the original quoting style
yaml.width = 4096



def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    httpx_logger = logging.getLogger("httpx")
    httpx_logger.setLevel(logging.WARNING)
    azure_logger = logging.getLogger("azure.identity")
    azure_logger.setLevel(logging.WARNING)
    azure_core_logger = logging.getLogger("azure.core")
    azure_core_logger.setLevel(logging.WARNING)
    


tag = 'eval_1201'
model_name_short = 'Simia-OfficeBench-SFT-Qwen3-8B'
exp_id = f"{tag}_{model_name_short}"


repo_root_dir = os.path.dirname(
    os.path.abspath(__file__)
)

# Create the parser
parser = argparse.ArgumentParser()

# Add arguments
parser.add_argument("--generate-config", action="store_true", help="Generate configuration file")
parser.add_argument("--no-debug", action="store_true", help="Run in non-debug mode")
parser.add_argument("--task", type=str, help="Task to run", default=None)
parser.add_argument("--no-force-new", action="store_true", help="Do not force new run, keep existing output directories")

# Parse the arguments
args = parser.parse_args()

setup_logging()

# check if the config is already generated, if not, generate new
output_exp_dir = Path(f"{repo_root_dir}/exp/{exp_id}")
if not os.path.exists(output_exp_dir) or args.generate_config:
    print ('Config not found, generating new ... ')
    generate_run_config(exp_tag=tag, model_id=model_name_short, prompt_file="configs/prompts_v2.json", use_thinking_tokens=True, use_scratchpad=False)
else:
    print ('Config found successfully, skipping generation ... ')    

# clear the error log
if os.path.exists("error.log"):
    os.remove("error.log")

# load the config file
exp_config_path = Path(f"{repo_root_dir}/exp/{exp_id}/{CONFIG}/{exp_id}.yaml")
exp_config = yaml.load(exp_config_path)

max_iter = exp_config[ENV][MAX_ITER]

models_config_filepath = Path(f"{repo_root_dir}/configs/models.yaml")

with open(models_config_filepath, "r") as file:
    models_config = yaml.load(file)
MODEL_NAMES = {}
for model_short in models_config["model"]:
    MODEL_NAMES[model_short] = models_config["model"][model_short]["name"]

model_name = MODEL_NAMES[model_name_short]
# first list all task folders within tasks
task_list = os.listdir('tasks')
if args.task is not None:
    assert args.task in task_list, f"Task {args.task} not found in tasks folder"
    task_list = [args.task]



for i, task in enumerate(task_list):
    if not '-' in task:
        continue
    
    subtask_list = os.listdir(f'tasks/{task}/subtasks')
    

    task_desc = f"Task {task} ({i+1}/{len([t for t in task_list if '-' in t])})"
    subtask_pbar = tqdm(subtask_list, desc=task_desc, leave=True)
    
    for subtask in subtask_pbar:
        subtask_desc = f"{task}/{subtask}"
        subtask_pbar.set_postfix_str(subtask_desc)
        
        config_file = f'tasks/{task}/subtasks/{subtask}'
        subtask_name = subtask.split('.')[0]
        
        output_folder = f'tasks/{task}/outputs/{subtask_name}/{model_name}_{tag}'
        if os.path.exists(output_folder):
            if not args.no_force_new:
                print(f"Force new mode: removing existing output directory: {output_folder}")
                shutil.rmtree(output_folder)
            else:
                subtask_pbar.write(f"⏭️  Skipping {subtask_desc} - output directory already exists")
                continue
    
        subtask_pbar.write(f"🚀 Starting: {subtask_desc}")
        
        main(docker_name='officebench',
            container_name=f'officebench-debug-{tag}-{model_name_short}',
            dockerfile_path='./docker/Dockerfile',
            model_name=model_name,
            task_dir=f'tasks/{task}',
            config_file=config_file,
            task=None,
            tag=tag,
            max_iter=max_iter,
            mode='force_new',
            exp_config=exp_config,
            debug_mode=False,
            use_docker=False,
            local_workdir='./local_workdir',
            output_dir=f'./outputs/{model_name.replace("/","_")}_{tag}/0/{task}/{subtask_name}',
            )
        
        subtask_pbar.write(f"✅ Completed: {subtask_desc}")