# script to generate a run config for an experiment
# How it works:
# Load the base config and fill in the dynamic parts
# Write to the experiment folder
# When running a new experiment, point to the experiment folder to load the config
# ARGUMENTS:
# --exp-tag: The experiment tag without model_id
# --model-id: The model id short form, see model.yaml
# Example usage:
# python generate_run_config.py --exp-tag debug-13-jan --model-id gpt4o

import argparse
from pathlib import Path
import re
from string import Template
from io import StringIO
from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True  # Preserve the original quoting style
yaml.width = 4096
import os
from utils.constants import *
import debugpy

parser = argparse.ArgumentParser()

repo_root_dir = os.path.dirname(
    os.path.abspath(__file__)
)

MODELS = {}  # List of models
# Load the list of models from the config file
base_config_filepath = Path(f"{repo_root_dir}/configs/base_config.yaml")
models_config_filepath = Path(f"{repo_root_dir}/configs/models.yaml")


with open(models_config_filepath, "r") as file:
    models_config = yaml.load(file)
MODELS = models_config[MODEL]

parser.add_argument("--exp-tag", type=str, required=True, help="The experiment tag without model_id")
parser.add_argument("--model-id", type=str, required=True, help="The model id short form, see model.yaml")
parser.add_argument("--prompt-file", type=str, required=False, help="The prompt file to use", default="configs/prompts.json")
parser.add_argument("--use_thinking_tokens", action="store_true", default=False, help="Use thinking tokens in the prompt")
parser.add_argument("--use-scratchpad", action="store_true", default=False, help="Use scratchpad in the prompt")

def main(exp_tag, model_id, prompt_file, use_thinking_tokens, use_scratchpad):
    with open(base_config_filepath) as f:
        config_template = Template(f.read())
    exp_id = f"{exp_tag}_{model_id}"
    output_exp_dir = Path(f"{repo_root_dir}/exp/{exp_id}/{CONFIG}")
    output_exp_dir.mkdir(parents=True, exist_ok=True)
    
    # update the meta data
    config_updated = override_config_metadata(
        config_template, exp_id, model_id, prompt_file, use_thinking_tokens, use_scratchpad
    )
    config_file_name = f"{exp_id}.yaml"
    output_path = output_exp_dir / config_file_name
    with open(output_path, "w") as f:
        f.write(config_updated)
        print("Generated file", output_path)
    return output_path

def override_config_metadata(base_config, exp_id, model_id, prompt_file, use_thinking_tokens, use_scratchpad):
    config = base_config.substitute(
        exp_id=exp_id,
        model_id=model_id,
        model_name=MODELS[model_id][NAME],
        prompt_file=prompt_file,
        use_thinking_tokens="true" if use_thinking_tokens else "false",
        use_scratchpad="true" if use_scratchpad else "false"
    )
    return config

if __name__ == "__main__":
    args = parser.parse_args()
    main(args.exp_tag, args.model_id, args.prompt_file, args.use_thinking_tokens, args.use_scratchpad)