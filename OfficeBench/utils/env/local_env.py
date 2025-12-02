import os
from termcolor import cprint
from utils.config import BlueprintConfig, save_blueprint_config
import re
import json
import traceback
from typing import Dict, List, Tuple
import logging

from intercode.envs.ic_env import (
    IntercodeEnv,
    AGENT_OBS, EVAL_OBS, CORRUPT_GOLD, ACTION_EXEC, REWARD
)
from intercode.utils import timeout, IntercodeDataLoader

from utils.shell_executor import execute_shell_command
from utils.prompts import PROMPT_DICT as DEFAULT_PROMPT_DICT
import apps
from .docker_env import OfficeAgentEnv, TIMEOUT_DURATION

class OfficeAgentLocalEnv(OfficeAgentEnv):
    """Gym environment for bash shell"""
    name = "officeagent_local_bash"

    def __init__(self, exp_config: BlueprintConfig, **kwargs):
        self.kwargs = kwargs
        self.container = None

        # load prompts
        self.PROMPT_DICT = DEFAULT_PROMPT_DICT
        assert isinstance(exp_config, BlueprintConfig), f"exp_config should be a BlueprintConfig object, but got {type(exp_config)}"
        if exp_config.prompt_file is not None:
            logging.info(f"LLM Policy: Loading prompt file: {exp_config.prompt_file}")
            prompt_file = exp_config.prompt_file
            with open(prompt_file, 'r') as f:
                self.PROMPT_DICT = json.load(f)
        else:
            logging.info(f"LLM Policy: Using default prompt file")
            logging.info(exp_config)

        # Setup logging
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

        self.task_dir = kwargs.get("task_dir", None)
        self.workdir = kwargs.get("workdir", "./")
        self.exp_config = exp_config

        if "scratchpad" in apps.AVAILABLE_APPS: # and not self.exp_config.experiment.use_scratchpad:
            # Remove scratchpad app - it gets special treatment
            del apps.AVAILABLE_APPS["scratchpad"]
            del apps.AVAILABLE_ACTIONS["scratchpad"]

        if "verbose" not in self.kwargs or self.kwargs["verbose"] != True:
            self.logger.disabled = True

        self.tool_mode = True
        if "data_path" in self.kwargs and self.kwargs["data_path"] is not None:
            self.data_path = self.kwargs["data_path"]
            self.data_loader = IntercodeDataLoader(self.data_path)
            self.logger.info(f"Loaded dataset from {self.data_path}")
            self.tool_mode = False
        else:
            self.logger.info("No dataset provided, running in interactive mode")
        
        # Verify that preprocess function matches specifications
        self.preprocess = None
        if "preprocess" in self.kwargs and self.kwargs["preprocess"] is not None:
            self.logger.info("Verifying preprocess function...")
            preprocess = self.kwargs["preprocess"]
            assert(isinstance(preprocess, type(lambda x: x)))
            assert(preprocess.__annotations__["return"] == List)
            assert("record" in preprocess.__annotations__)
            assert(preprocess.__annotations__["record"] == Dict)
            self.preprocess = preprocess

        # Record logging directory if provided as a keyword argument
        self.traj_dir = None
        if "traj_dir" in self.kwargs and self.kwargs["traj_dir"]:
            self.traj_dir = self.kwargs["traj_dir"]

        if not self.tool_mode:
            self.logger.info("* Note *: `reset` should be explicitly called to load new task episode")

        self.task = kwargs.get("task", '<undefined>')
        self.current_app = None
        self.available_apps = apps.AVAILABLE_APPS
        self.history = []
        if os.path.exists(os.path.join(self.workdir, "scratchpad.txt")):
            logging.info("Deleting scratchpad file")
            os.remove(os.path.join(self.workdir, "scratchpad.txt"))

        self.logger = logging.getLogger(__name__)

    def exec_action(self, action_string: str) -> None:
        self.observation = None
        self.thinking_string = None
        try:
            if self.exp_config.experiment.use_thinking_tokens:
                # The new prompt requires the LLM to return <think>...</think><answer>[JSON payload]</answer>
                # parse out the thinking and action tokens. There may be whitespace between /think and action.
                match = re.match(r"<think>(.*?)</think>\s*<answer>(.*)</answer>", action_string)
                if match:
                    thinking_string, action_string = match.groups()
                else:
                    # Also handle cases where response only contains <answer> tags
                    answer_match = re.match(r"<answer>(.*)</answer>", action_string)
                    if answer_match:
                        thinking_string = None
                        action_string = answer_match.group(1)
                    else:
                        raise ValueError(f"Malformed action string:{action_string}. Expected <think>...</think>\n<answer>[JSON payload]</answer>")
            
            # strip markdown if present
            if action_string.startswith("```json") and action_string.endswith("```"):
                action_string = re.match(r'```json(.*)```', action_string, re.DOTALL).group(1)
            action = json.loads(action_string)
            action = self._minor_action_fix(action)
            assert self.check_valid_action(action)

            # special case for switch app
            if action['action'] == 'switch_app':
                action['app'] = 'system'
            elif len(action['action'].split('.')) > 1:
                maybe_app = action['action'].split('.')[0]
                if maybe_app in self.available_apps:
                    action['app'] = action['action'].split('.')[0]
                    action['action'] = action['action'].split('.')[1]
                    self.current_app = action['app']
            is_cd_flag = False
            if action["app"] == "scratchpad":
                assert action["action"] == "write" and action["content"] is not None
                from apps.scratchpad_app.scratchpad import scratchpad_write
                scratchpad_write(self.workdir, action["content"])
                self.observation = f"Successfully wrote to scratchpad."
                command = None
            elif action["app"] == "shell":
                if 'command' not in action:
                    raise ValueError("Missing command in json request. Use the format specified: {\"app\": \"shell\", \"action\": \"command\", \"command\": \"<command>\"}")
                command = action["command"]
                if isinstance(command, list):
                    command = ' '.join(command)
                is_cd_flag = command.startswith("cd")
                if is_cd_flag:
                    # TODO: What if multiple commands on one line w/ `cd` as first one?
                    cd_arg = command[command.index("cd ")+3:].strip()
                    new_path = self.simplify_path(self.workdir, cd_arg)
                    command = f"cd {new_path}"
            elif action["app"] == "system":
                if action["action"] == "switch_app":
                    if "target_app" not in action:
                        raise ValueError("Missing target_app in json request. Use the json format specified: {\"app\": \"system\", \"action\": \"switch_app\", \"target_app\": \"<target_app>\"}")
                    if action["target_app"] not in self.available_apps:
                        raise ValueError(f"App {action['target_app']} not available")
                    self.current_app = action["target_app"]
                    def format_action_list():
                        return "\n".join([f"- {action}" for action in apps.AVAILABLE_ACTIONS[self.current_app].keys()])
                    self.observation = f"Successfully switched to app: {self.current_app}. Available actions:\n{format_action_list()}\n"
                    detailed_instruction = ''
                    for action in self.get_available_actions():
                        action_module = apps.AVAILABLE_ACTIONS[self.current_app][action]
                        detailed_instruction += f" - {action_module.DEMO}\n"
                    available_apps = [app for app in self.available_apps.keys() if app != self.current_app]
                    prompt_decided_app = self.PROMPT_DICT['prompt_decided_app'].format_map({
                        'task': self.task,
                        'current_app': self.current_app,
                        'detailed_instruction': detailed_instruction,
                        'available_apps': available_apps,
                    })
                    self.observation += prompt_decided_app
                elif action["action"] == "finish_task":
                    answer = action.get("answer", 'None')                    
                    output_path = os.path.join(self.task_dir, "testbed", "data", "answer.txt")
                    self._write_answer(answer, output_path)
                    self.observation = "Task finished"
                elif action["action"] == 'got_stuck':
                    answer = 'None'
                    self.observation = "Task failed"
                command = None
            else:
                # TODO: config flag for quick actions
                if self.current_app != action["app"]:
                    command = None
                    self.observation = f"Error: you must switch to the {action['app']} app before executing this action. Use the switch_app action to switch apps."
                elif action["action"] in apps.AVAILABLE_ACTIONS[action["app"]]:
                    action_module = apps.AVAILABLE_ACTIONS[action["app"]][action["action"]]
                    command = action_module.construct_action(self.task_dir, args=action)
                    if "/apps/" in command:
                        command = command.replace("/apps/", "apps/")
                else:
                    command = None
                    self.observation = f"Error: Action {action['action']} not available in app {action['app']}"

            if command is not None:
                with timeout(seconds=TIMEOUT_DURATION):
                    cleaned_cmd = self.clean_cmd(command, )
                    self.logger.info(f"Executing command: [{cleaned_cmd}]")
                    exit_code, std_output, std_error = execute_shell_command(cleaned_cmd)
                    self.observation = std_output.decode("utf-8").split('OBSERVATION:')[-1].strip()

                    cprint(100*'+', color='yellow', attrs=['bold'])
                    cprint(f'OBSERVATION: {self.observation}', color='yellow', attrs=['bold'])
                    cprint(100*'+', color='yellow', attrs=['bold'])
                    self.info[ACTION_EXEC] = exit_code == 0

                if is_cd_flag and self.info[ACTION_EXEC]:
                    self.workdir = new_path
                
                if action["app"] == "shell":
                    if not self.info[ACTION_EXEC]:  # Command failed
                        self.observation = f"Command failed with exit code {exit_code}: {command}. The error was [{std_error.decode('utf-8')}]."
                    elif self.observation == "":  # Command succeeded but no output
                        self.observation = f"Successfully executed command: {command}. The output was [{std_output.decode('utf-8')}]."

            self.history.append((action, self.observation))
        except Exception as e:
            cprint('!!!!!!!!', color='red')
            cprint(e, color='red')
            # print the stack trace            
            traceback.print_exc()
            #output a log to the outputs folder
            with open(f'{self.task_dir}/error.log', 'a') as f:
                f.write(f"Task: {self.task}\n")
                f.write(f"Error: {e}\n")
                f.write(f"Action: {action_string}\n")
                f.write(f"Traceback: {traceback.format_exc()}\n")
                f.write("=" * 20 + "\n")
            cprint(f"Attempted action: {action_string}", color='red')
            cprint('!!!!!!!!', color='red')
            self.observation = f"Error: [{self.current_app}] {e}"
            if isinstance(e, json.JSONDecodeError):
                self.observation += " Malformed action! You must follow the given action JSON format!"
            self.info[ACTION_EXEC] = False
            self.history.append(({'action': action_string}, self.observation))
            if isinstance(e, TimeoutError) and self.current_app == "ocr": # bail aggressively on ocr timeouts which are likely auth failures
                raise e
        return
    

    def reset(self, index: int = None) -> Tuple[str, Dict]:
        """
        Create new session and reset environment variables

        Args:
            index (`int`) - index of query, gold pair to use for new session. If None, random index is used.
        """
        # Reset instance variables
        self.info = {}
        self.trajectory = []
        self.observation = None
        
        # Set query, gold command
        if not self.tool_mode:
            self.logger.info("-------------\nNew task episode initialized")
            self.query_idx = np.random.randint(0, len(self.data_loader)) if index is None else index
            self.record = self.data_loader.get(self.query_idx)
            self.query = self.record["query"]
            self.gold = self.record["gold"] if "gold" in self.record else "N/A"
            self.logger.info(f"Query: {self.query}")
            self.logger.info(f"Gold: {self.gold}")
            self.observation = self.query
            self.reward = None
        else:
            self.logger.info("-------------\nExecution Environment Reset")


        # Run preprocess function if provided
        if self.preprocess is not None:
            preprocess_cmds = self.preprocess(self.record)
            for cmd in preprocess_cmds:
                self.exec_action(cmd)
                if not self.info[ACTION_EXEC]:
                    raise RuntimeError(f"Preprocess command failed to execute successfully: {self.preprocess(self.record)}")
        
        return self.observation, self.info
    
    def get_reward(self) -> Tuple[float, Dict]:
        
        print("======================================================")
        print('get_reward called')
        print("======================================================")
        return 0.0, {}

    def close(self):
        # Not using docker, so no need to stop container
        pass
    
    def clean_cmd(self, action: str) -> str:
        """Cleans action string"""
        entrypoint = "/bin/bash" 
        if self.current_app == "calendar" or self.current_app == "email":
            action += f" --workdir {self.task_dir}"
        command = '{} -c """ {} """'.format(entrypoint, action.strip())
        print('COMMAND:', command)
        return command
    
    def _write_answer(self, answer: str, file_path: str):
        answer = str(answer)
        answer = answer.replace('"', '').replace("'", '')
        
        try:
            if not os.path.exists(os.path.dirname(file_path)):
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w') as f:
                f.write(answer)
                return 
        except Exception as e:
            print(f"Write Answer: Failed to write answer to container: {e}")