import json
import apps

from utils.llm import ChatGPT, Gemini, vLLM, vLLMLocal
from utils.prompts import PROMPT_DICT as DEFAULT_PROMPT_DICT
import logging
from utils.config import BlueprintConfig
import os
from apps.scratchpad_app.scratchpad import scratchpad_read


class BasePolicy:
    def __init__(self):
        pass

    def forward(self, *args, **kwargs):
        raise NotImplementedError
    
class HumanPolicy(BasePolicy):
    def __init__(self):
        super().__init__()
    
    def forward(self, query, observation, available_actions):
        action = input('> ')
        return action

class LLMPolicy(BasePolicy):
    def __init__(self, model_name, key, env, config, llm_cache=None, debug_mode=False, exp_config: BlueprintConfig=None):
        super().__init__()

        # store model name for use in build_prompt
        self.model_name = model_name
        
        # store config for use in build_prompt
        self.config = config

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

        assert not os.path.exists(f'{env.workdir}/scratchpad.txt'), f"Scratchpad file {env.workdir}/scratchpad.txt already exists, please remove it before running the experiment"
        self.system_message = self.construct_system_message(config, env.available_apps)
        if 'gpt' in model_name or 'phi' in model_name or 'mistral' in model_name or 'r1' in model_name or 'o1' in model_name or 'o4' in model_name or '4o' in model_name:
            service='llmapi'
            if model_name.startswith('azure/'):
                service='azure'
                model_name = model_name.split('/')[1]
            self.llm = ChatGPT(model_name, key, service=service, system_message=self.system_message)
        elif 'gemini' in model_name:
            self.llm = Gemini(model_name, key, self.system_message)
        else:
            # For all other models (including llama, qwen, etc.), use local vLLM
            self.llm = vLLMLocal(model_name, self.system_message)
            # Tokenizer is already obtained in vLLMLocal through model manager, no need to load again
            self.tokenizer = self.llm.tokenizer
            
        self.llm_history = []

        self.action_window = []
        self.action_window_size = 5

        self.llm_cache = llm_cache

        self.logger = logging.getLogger(__name__)

        self.debug_mode = debug_mode
        self.exp_config = exp_config

        logging.debug(f"LLM Policy: System message: {self.system_message}")
        
    def dump_history(self, output_dir):
        with open(f'{output_dir}/llm_history.json', 'w') as f:
            json.dump(self.llm_history, f, indent=2)

    def construct_system_message(self, config, available_apps):
        app_introduction = ''
        for app in available_apps:
            app_introduction += f' - {apps.AVAILABLE_APPS[app].INTRO}\n'
        username = config['username']
        date = config['date']
        weekday = config['weekday']
        time = config['time']
        testbed_data_path = config['testbed_data_path']

        system_message = self.PROMPT_DICT['system_message'].format_map(
            {
                'username': username,
                'date': date,
                'weekday': weekday,
                'time': time,
                'app_introduction': app_introduction,
                'testbed_data_path': testbed_data_path
            }
        ).strip()
        return system_message

    def proc_action(self, action):
        if '{' not in action or '}' not in action:
            self.logger.warning(f"LLM Policy: Invalid action format: {action}")
            return action
        left = action.find('{')
        right = action.rfind('}') + 1
        action = action[left:right]
        return action

    def forward(self, env):
        prompt = self.build_prompt(env)
        try:
            if self.llm_cache:
                if prompt in self.llm_cache:
                    print('!!!')
                    print('LLM Cache Hit!')
                    print('!!!')
                    response = self.llm_cache[prompt]
                else:
                    # Check if we need to use GPT messages format
                    if (hasattr(self, '_use_messages_format') and self._use_messages_format 
                        and hasattr(self, '_current_messages') and isinstance(self.llm, ChatGPT)):
                        # For GPT models with o4/4o, use messages format directly
                        response = self.llm.llm_model.get_response(self._current_messages)[1]
                    else:
                        response = self.llm.generate(prompt)
            else:
                # Check if we need to use GPT messages format
                if (hasattr(self, '_use_messages_format') and self._use_messages_format 
                    and hasattr(self, '_current_messages') and isinstance(self.llm, ChatGPT)):
                    # For GPT models with o4/4o, use messages format directly
                    response = self.llm.llm_model.get_response(self._current_messages)[1]
                else:
                    response = self.llm.generate(prompt)
        except Exception as e:
            self.logger.error(f"LLM Policy: Error generating response: {e}")
            response = f"Error: {str(e)}"
        self.llm_history.append((self.system_message, prompt, response))

        if self.debug_mode:
            print('\n' + '='*50)
            print(f'🤖 Latest generation: {response}')
            print('='*50 + '\n')

        # for use_thinking_tokens, the process is applied at env.step
        if not self.exp_config.experiment.use_thinking_tokens:
            action = self.proc_action(response)
        else:
            action = response

        if action == '':
            action = response

        self.action_window.append(action)
        self.action_window = self.action_window[-self.action_window_size:]
        if len(self.action_window) >= self.action_window_size and all([action == self.action_window[0] for action in self.action_window]):
            self.logger.warning(f"LLM Policy: Action stuck in the action window: {action}")
            action = json.dumps({'app': 'system', 'action': 'got_stuck'})   

        return action
    
    def build_prompt(self, env):

        scratchpad_content = ''
        if self.exp_config.experiment.use_scratchpad:
            scratchpad_content = "\n\n*scratchpad:* you may write plans, track progress, etc using the scratchpad. This is highly encouraged for multi-step tasks. Writing to the scratchpad will replace its contents.\n\nAt any time you may write to the scratchpad using the scratchpad action. This will not change the current app or otherwise change the task state, and any scratchpad contents are deleted once the task is complete. Since it is volatile, scratchpad is *not* a place to store final results- follow the instructions for your task to save any final results or answers. The scratchpad will always be displayed here.\n\nScratchpad contents:\n\n"
            import_content = scratchpad_read(env.workdir)
            if import_content:
                scratchpad_content += import_content.replace('\n', '\\n')+"\n\n"
            else:
                scratchpad_content += "No content in scratchpad.\n\n"
            scratchpad_content += "/end scratchpad content\n\n"

        
        prompt = self.system_message + "\n\n" + scratchpad_content + \
                    self.PROMPT_DICT['prompt_undecided_app'].format_map({
                        'task': env.task,
                        'available_apps': list(env.available_apps.keys()),
                    })
        messages = [
                {"role": "system", "content": f"You're a helpful assistant. "}, 
                {"role": "user", "content": prompt}
        ]

        for llm_history, env_history in zip(self.llm_history, env.history):
            response = llm_history[2] or ""
            observation = env_history[1] or ""
            messages.append({"role": "assistant", "content": response})
            # observation = observation + f"\nYou can only manipulate files under the `{self.config['testbed_data_path']}` directory."
            messages.append({"role": "user", "content": observation})
        
        # Check if model uses GPT format (including o4 and 4o models)
        if ('gpt' in self.model_name or 'phi' in self.model_name or 'mistral' in self.model_name or 
            'llama' in self.model_name or 'r1' in self.model_name or 'o1' in self.model_name or 
            'o4' in self.model_name or '4o' in self.model_name):
            # For GPT format models, we need to handle this differently in forward method
            # Store messages in a special attribute for GPT models
            self._current_messages = messages
            
            # For GPT models, create a prompt version using a fallback tokenizer for saving purposes
            try:
                # Try to use global model manager to get Qwen tokenizer (if loaded)
                from utils.llm import is_vllm_model_loaded, get_vllm_model
                qwen_model = "Qwen/Qwen2.5-7B"
                if is_vllm_model_loaded(qwen_model):
                    _, qwen_tokenizer = get_vllm_model(qwen_model)
                else:
                    # If not loaded, use transformers directly (only for prompt generation)
                    from transformers import AutoTokenizer
                    qwen_tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B")
                
                prompt = qwen_tokenizer.apply_chat_template(messages,
                                                add_generation_prompt=True,
                                                tokenize=False)
            except Exception as e:
                # If tokenizer loading fails, use simple string concatenation as fallback
                logging.warning(f"Failed to load tokenizer for prompt generation: {e}")
                prompt = self.system_message + "\n\n"
                for msg in messages[1:]:  # Skip the first system message
                    prompt += f"{msg['role']}: {msg['content']}\n\n"
            
            # Store the actual format indicator for forward method
            self._use_messages_format = True
            
        else:
            # For other models, use tokenizer
            prompt = self.tokenizer.apply_chat_template(messages,
                                            add_generation_prompt=True,
                                            tokenize=False)
            self._use_messages_format = False

        logging.debug(f"LLM Policy: Prompt: {prompt}")
        return prompt


