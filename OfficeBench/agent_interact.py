import json
import os
import fire
import shutil
from datetime import datetime
import pytz
from termcolor import cprint

from utils.helper import build_docker
from utils.env import OfficeAgentEnv, OfficeAgentLocalEnv
from utils.policies import LLMPolicy
from utils.config import load_blueprint_config, BlueprintConfig



def main(docker_name='officebench',
         container_name='officebench-debug',
         dockerfile_path='./docker/Dockerfile',
         model_name='dev-gpt-4o-2024-05-13',
         task_dir='tasks/1-1',
         config_file='tasks/1-1/subtasks/0.json',
         output_dir='outputs',
         task=None,
         trial=None,
         tag=None,
         max_iter=20,
         mode='default',
         exp_config: BlueprintConfig | str = None,
         local_workdir=None,
         use_docker=True,
         debug_mode=True):
    
    assert mode in ['force_new', 'use_llm_cache', 'default']
    if mode == 'force_new':
        force_new = True
        use_llm_cache = False
    elif mode == 'use_llm_cache':
        force_new = False
        use_llm_cache = True
    else:
        force_new = False
        use_llm_cache = False

    if use_docker:
        if not os.path.exists(dockerfile_path):
            raise FileNotFoundError(f"Dockerfile not found: {dockerfile_path}")
        build_docker(docker_name, dockerfile_path)

    else:
        if local_workdir is None:
            raise ValueError("local_workdir must be specified when use_docker is False")
        if force_new and os.path.exists(local_workdir):
            print(f"Force new mode: removing existing local workdir: {local_workdir}")
            shutil.rmtree(local_workdir)
        os.makedirs(local_workdir, exist_ok=True)
        shutil.copytree(task_dir, os.path.join(local_workdir, task_dir), dirs_exist_ok=True)
        config_file = os.path.join(local_workdir, config_file)
        task_dir = os.path.join(local_workdir, task_dir)

    config = json.load(open(config_file))
    task = config.get('task', task)
    subtask_id = config_file.split('/')[-1].split('.')[0]
    
    if tag is None:
        timezone = pytz.timezone('America/Los_Angeles')
        tag = datetime.now(timezone).strftime('%Y%m%d%H%M%S')
    if output_dir is None:
        output_dir = f'{task_dir}/outputs/{subtask_id}/{model_name.replace("/", "_")}_{tag}'
        if trial is not None:
            output_dir += f'_{trial}'
    

    attrs = ['bold']

    def black_on_white(text):
        cprint(text, 'black', 'on_white', attrs=attrs)
    black_on_white('-------------------META DATA INFORMATION-------------------')
    cprint(f'TASK DIRECTORY {task_dir}', attrs=attrs)
    cprint(f'TASK: {task}', attrs=attrs)
    cprint(f'Subtask ID: {subtask_id}', attrs=attrs)
    cprint(f'Config File: {config_file}', attrs=attrs)
    cprint(f'Output Directory: {output_dir}', attrs=attrs)
    black_on_white('-------------------META DATA INFORMATION-------------------')
    
    if tag is None:
        timezone = pytz.timezone('America/Los_Angeles')
        tag = datetime.now(timezone).strftime('%Y%m%d%H%M%S')
    
    if os.path.exists(output_dir) and use_llm_cache and not force_new:
        assert os.path.exists(f'{output_dir}/llm_history.json'), f"LLM history not found: {output_dir}/llm_history.json"
        llm_cache = {}
        llm_history = json.load(open(f'{output_dir}/llm_history.json'))
        for item in llm_history:
            llm_cache[item[1]] = item[2]
    else:
        llm_cache = None

    if os.path.exists(output_dir) and not force_new and not use_llm_cache:
        print(f"Output directory already exists: {output_dir}")
        return
    
    if os.path.exists(output_dir) and force_new:
        print(f"Force new mode: removing existing output directory: {output_dir}")
        shutil.rmtree(output_dir)
    
    if exp_config is None:
        exp_config = BlueprintConfig()
    elif isinstance(exp_config, str):
        exp_config = load_blueprint_config(exp_config)
    elif isinstance(exp_config, dict):
        exp_config = BlueprintConfig.from_dict(exp_config)
    
    if use_docker:
        print('container name', container_name)
        config["testbed_data_path"] = '/testbed/data'

        env = OfficeAgentEnv(image_name=docker_name,
                            container_name=container_name,
                            exp_config=exp_config,
                            task=task,
                            verbose=True)
        env.reset()
        env.prepare_docker_env(
            testbed_dir=f'{task_dir}/testbed/',
            app_dir=f'apps/',
        )
        env.cache_docker_status(local_cache_dir=f'{output_dir}/cache/{subtask_id}/')
    else:
        print('local workdir', local_workdir)
        print('task_dir', task_dir)
        config["testbed_data_path"] = f'{task_dir}/testbed/data'

        env = OfficeAgentLocalEnv(
            exp_config=exp_config,
            task_dir=task_dir,
            app_dir='apps/',
            workdir=local_workdir,
            task=task,
            verbose=True
        )
        env.reset()
        # check if the testbed directory exists
        if os.path.exists(f'{task_dir}/testbed'):
            shutil.copytree(f'{task_dir}/testbed', f'{output_dir}/cache/testbed', dirs_exist_ok=True)
        else:
            os.makedirs(f'{output_dir}/cache/testbed', exist_ok=True)         
        
    # copy references folder to the output directory
    if os.path.exists(f'{task_dir}/reference'):
        shutil.copytree(f'{task_dir}/reference', f'{output_dir}/reference')   

    if 'gpt' in model_name:
        # TODO: Load GPT4 API
        api_key = ""
        
    elif 'gemini' in model_name:
        api_key = open('gemini_key.txt').read().strip()
    else:
        api_key = ""

    policy = LLMPolicy(
        model_name=model_name,
        key=api_key,
        env=env,
        config=config,
        llm_cache=llm_cache,
        debug_mode=debug_mode,
        exp_config=exp_config,
    )
    try:
        obs = env.observation
        done = False
        n_iter = 0
        while not done:
            n_iter += 1
            action = policy.forward(env)
            obs, reward, done, info = env.step(action)
            if n_iter >= max_iter:
                print(f"Max iterations reached: {max_iter}")
                break
    except KeyboardInterrupt:
        print("Exiting InterCode environment...")
    
    cprint(f"TASK {task}-{subtask_id} COMPLETED", 'green', attrs=attrs)
    os.makedirs(output_dir, exist_ok=True)


    if use_docker:
        env.cache_docker_status(local_cache_dir=output_dir)
    else:
        work_testbed = f'{task_dir}/testbed'
        output_testbed = f'{output_dir}/testbed'
        if os.path.exists(work_testbed):
            print(f"Copying testbed from {work_testbed} to {output_testbed}")
            shutil.copytree(work_testbed, output_testbed, dirs_exist_ok=True)
        else:
            print(f"Testbed not found in {work_testbed}, skipping copy")
    env.dump_history(output_dir)
    policy.dump_history(output_dir)
    with open(f'{output_dir}/settings.json', 'w') as f:
        json.dump(config | {'model_name': model_name}, f, indent=2)
    
    env.close()

if __name__ == '__main__':
    fire.Fire(main)
