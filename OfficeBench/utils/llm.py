from openai import OpenAI
import time
import numpy as np
import google.generativeai as genai
from mimetypes import guess_type
from utils.substrate_api import LLMApiWrapper, AzureApiWrapper
import base64
import logging
import os
import threading
from typing import Dict, Optional, Tuple, Any

# Set up a dedicated logger for this module
logger = logging.getLogger('llm')
logger.setLevel(logging.INFO)

# Global Model Manager
class vLLMModelManager:
    """Global vLLM model manager to ensure each model is loaded only once"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not getattr(self, '_initialized', False):
            self._models: Dict[str, Tuple[Any, Any]] = {}  # model_name -> (llm, tokenizer)
            self._model_locks: Dict[str, threading.Lock] = {}
            self._initialized = True
    
    def get_model(self, model_name: str):
        """Get or create model instance"""
        if model_name not in self._models:
            # Create lock for each model
            if model_name not in self._model_locks:
                self._model_locks[model_name] = threading.Lock()
            
            with self._model_locks[model_name]:
                # Double-checked locking pattern
                if model_name not in self._models:
                    logger.info(f"Loading vLLM model: {model_name}")
                    try:
                        from transformers import AutoTokenizer
                        from vllm import LLM
                        
                        llm = LLM(model=model_name, dtype='bfloat16', tensor_parallel_size=4)
                        tokenizer = AutoTokenizer.from_pretrained(model_name)
                        
                        self._models[model_name] = (llm, tokenizer)
                        logger.info(f"vLLM model loaded successfully: {model_name}")
                    except Exception as e:
                        logger.error(f"Failed to load vLLM model {model_name}: {e}")
                        raise
        
        return self._models[model_name]
    
    def unload_model(self, model_name: str):
        """Unload model (release GPU memory)"""
        if model_name in self._models:
            with self._model_locks.get(model_name, threading.Lock()):
                if model_name in self._models:
                    del self._models[model_name]
                    logger.info(f"Unloaded vLLM model: {model_name}")
    
    def list_loaded_models(self):
        """List loaded models"""
        return list(self._models.keys())
    
    def clear_all_models(self):
        """Clear all loaded models"""
        with self._lock:
            self._models.clear()
            logger.info("Cleared all vLLM models")
    
    def is_model_loaded(self, model_name: str) -> bool:
        """Check if model is already loaded"""
        return model_name in self._models

# Global model manager instance
model_manager = vLLMModelManager()

# Convenience functions
def get_vllm_model(model_name: str):
    """Convenience function: get vLLM model instance"""
    return model_manager.get_model(model_name)

def unload_vllm_model(model_name: str):
    """Convenience function: unload vLLM model"""
    model_manager.unload_model(model_name)

def list_loaded_vllm_models():
    """Convenience function: list loaded vLLM models"""
    return model_manager.list_loaded_models()

def clear_all_vllm_models():
    """Convenience function: clear all vLLM models"""
    model_manager.clear_all_models()

def is_vllm_model_loaded(model_name: str) -> bool:
    """Convenience function: check if vLLM model is loaded"""
    return model_manager.is_model_loaded(model_name)

# Configure logger with file and console output
def configure_logger(log_file=None, log_level=logging.INFO):
    """
    Configure the logger with optional file output
    
    Args:
        log_file: Optional path to a log file
        log_level: Logging level (default: INFO)
    """
    global logger
    logger.setLevel(log_level)
    
    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Add file handler if a log file is specified
    if log_file:
        # Create directory if it doesn't exist
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            
        # Add file handler (append mode)
        file_handler = logging.FileHandler(log_file, mode='a')
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.info(f"Logging to file: {log_file}")

# Initialize with default console handler
if not logger.handlers:
    configure_logger()
    
# Function to set up logging from outside this module
def set_log_file(log_file, log_level=logging.INFO):
    """
    Set up logging to a file from outside the module.
    
    Args:
        log_file: Path to the log file
        log_level: Logging level (default: INFO)
    """
    configure_logger(log_file=log_file, log_level=log_level)
    return logger

def _setup_logging(log_file, log_level):
    """Helper method to configure logging from model classes"""
    if log_file:
        configure_logger(log_file=log_file, log_level=log_level)
        logger.info(f"LLM module logging to: {log_file}")

class vLLM_API:
    # for parsing image to text
    def __init__(self, model_name='dev-phi-35-vision-instruct', log_file=None, log_level=logging.INFO):
        # Configure logging
        _setup_logging(log_file, log_level)
            
        self.sampling_params = {
            "max_tokens": 1024,
            "temperature": 1.0 if 'o1' in model_name else 0.0,
            "top_p": 1.0,
        }
        self.llm_model = LLMApiWrapper(model_name, self.sampling_params)
        
    def get_response(self, image_path):
        encoded_image = base64.b64encode(open(image_path, 'rb').read()).decode('ascii')
        mime_type, _ = guess_type(image_path)
        messages = [{ "role": "user",
            "content": [
                {"type": "text", "text": "List the text in the message as a table, separate the columns with a comma and rows by newline."},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"}}]}]
        response_text = self.llm_model.get_response(messages)[1]
        return response_text
    
class SimpleLLM:
    def __init__(self, service='llmapi', model_name='dev-phi-35-mini-instruct', is_embedding=False, log_file=None, log_level=logging.INFO):
        # Configure logging
        _setup_logging(log_file, log_level)
            
        self.is_embedding = is_embedding
        max_token_key = 'max_tokens'
        if 'o1' in model_name:
            max_token_key = 'max_completion_tokens'
        self.sampling_params = {
            max_token_key: 4096,
            "temperature": 1.0 if 'o1' in model_name else 0.0,
            "top_p": 1.0,
        }
        if service == 'llmapi':
            self.llm_model = LLMApiWrapper(model_name, self.sampling_params, is_embedding=is_embedding)
        else:
            assert service=='azure'
            self.llm_model = AzureApiWrapper(model_name, self.sampling_params)
    def generate_response(self, prompt='hello'):
        messages = [
            {"role": "user", "content": prompt}
        ]
        response = self.llm_model.get_response(messages)
        logger.info(f"SimpleLLM response: {response}")
        if self.is_embedding:
            return response['data'][0]['embedding']
        else:
            return response[1]
       

class ChatGPT:
    def __init__(self, model_name, key, service='azure', system_message=None, log_file=None, log_level=logging.INFO):
        # Configure logging
        _setup_logging(log_file, log_level)
            
        self.model_name = model_name
        self.key = key
        self.system_message = system_message
        
        self.client = OpenAI(
            api_key=key
        )
        
        temperature = 1.0 if 'o1' in model_name else 0.0
        max_token_key = 'max_completion_tokens' if 'o1' in self.model_name or 'o4' in self.model_name or '4o' in self.model_name or 'gpt-5' in self.model_name else 'max_tokens'    
        # max_token_key = 'max_completion_tokens'
        top_p = 1.0
        sampling_params = {
            max_token_key: 4096,
            "temperature": temperature,
            "top_p": top_p,
        }
        if service == 'llmapi':
            self.llm_model = LLMApiWrapper(model_name, sampling_params)
        else:
            assert service == 'azure'
            self.llm_model = AzureApiWrapper(model_name, sampling_params)
                

    def get_model_options(
        self,
        temperature=0.0,
        per_example_max_decode_steps=1024,
        per_example_top_p=1,
        n_sample=1,
    ):
        if 'o1' in self.model_name or 'o4' in self.model_name or 'gpt' in self.model_name:
            return dict(
                temperature=temperature,
                n=n_sample,
                top_p=per_example_top_p,
                max_completion_tokens=per_example_max_decode_steps,
            )
        else:
            return dict(
                temperature=temperature,
                n=n_sample,
                top_p=per_example_top_p,
                max_tokens=per_example_max_decode_steps,
            )

    def generate_plus_with_score(self, prompt, options=None, end_str=None):
        if options is None:
            options = self.get_model_options()
        messages = [
            {
                "role": "user" if 'o1' in self.model_name or 'gpt' in self.model_name else "system",
                "content": (
                    "I will give you some examples, you need to follow the examples and complete the text, and no other content."
                    if self.system_message is None
                    else self.system_message
                ),
            },
            {"role": "user", "content": prompt},
        ]
        gpt_responses = None
        retry_num = 0
        retry_limit = 2
        error = None
        while gpt_responses is None:
            try:
                # gpt_responses = self.client.chat.completions.create(
                #     model=self.model_name,
                #     messages=messages,
                #     stop=end_str,
                #     **options,
                # )
                
                gpt_responses = self.llm_model.get_response(messages)[0]
                error = None
            except Exception as e:
                logger.error(f"ChatGPT: {str(e)}")
                error = str(e)
                if "This model's maximum context length is" in str(e):
                    logger.error(f"Context length exceeded: {e}")
                    gpt_responses = {
                        "choices": [{"message": {"content": "PLACEHOLDER"}}]
                    }
                elif "invalid_prompt" in str(e):
                    gpt_responses = {
                        "choices": [{"message": {"content": "PLACEHOLDER"}}]
                    }
                elif retry_num > retry_limit:
                    error = f"too many retry times: {e}"
                    gpt_responses = {
                        "choices": [{"message": {"content": "PLACEHOLDER"}}]
                    }
                else:
                    time.sleep(60)
                retry_num += 1
        if error:
            raise Exception(error)
        results = []
        for i, res in enumerate(gpt_responses["choices"]):
            text = res["message"]["content"]
            fake_conf = (len(gpt_responses["choices"]) - i) / len(
                gpt_responses["choices"]
            )
            results.append((text, np.log(fake_conf)))

        return results

    def generate(self, prompt, options=None, end_str=None):
        if options is None:
            options = self.get_model_options()
        options["n"] = 1
        result = self.generate_plus_with_score(prompt, options, end_str)[0][0]
        # print ('PROMPT', prompt)
        # print ('RESPONSE', result)
        return result


class Gemini:
    # gemini-1.0-pro
    # gemini-1.5-pro
    def __init__(self, model_name, key, system_message=None, log_file=None, log_level=logging.INFO):
        # Configure logging
        _setup_logging(log_file, log_level)
            
        self.model_name = model_name
        genai.configure(api_key=key)
        self.model = genai.GenerativeModel(model_name)
        self.system_message = system_message

    def generate(self, prompt):
        combined_prompt = (
            f"{self.system_message}\n\n{prompt}" if self.system_message else prompt
        )
        response = self.model.generate_content(
            combined_prompt,
            generation_config=genai.types.GenerationConfig(
                # Only one candidate for now.
                candidate_count=1,
                max_output_tokens=1024,
                temperature=1.0,
            ),
        )
        return response.text


class vLLM:
    def __init__(self, model_name, system_message=None, log_file=None, log_level=logging.INFO):
        # Configure logging
        _setup_logging(log_file, log_level)
            
        self.model_name = model_name
        self.system_message = system_message
        self.temperature = 1.0 if 'o1' in model_name or 'gpt' in self.model_name else 0.0
        self.client = OpenAI(
            base_url="http://localhost:8000/v1",
            api_key="token-abc123",
        )
    
    def get_model_options(
        self,
        temperature=0.7,
        per_example_max_decode_steps=512,
        per_example_top_p=1,
        n_sample=1,
    ):
        return dict(
            temperature=temperature,
            n=n_sample,
            top_p=per_example_top_p,
            max_tokens=per_example_max_decode_steps,
        )

    def generate(self, prompt):
        try:
            options = self.get_model_options(temperature=self.temperature)
            completion = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role":  "user" if 'o1' in self.model_name or 'gpt' in self.model_name else "system", "content": self.system_message},
                    {"role": "user", "content": prompt},
                ],
                **options,
            )
            return completion.choices[0].message.content
        except Exception as e:
            logger.error(f"vLLM generation Error: {e}")
            return "None"


class vLLMLocal:
    def __init__(self, model_name, system_message=None, log_file=None, log_level=logging.INFO):
        # Configure logging
        _setup_logging(log_file, log_level)
        
        self.model_name = model_name
        self.system_message = system_message
        
        # Use global model manager to get model instance, avoiding duplicate loading
        logger.info(f"Getting vLLM model instance: {model_name}")
        self.llm, self.tokenizer = model_manager.get_model(model_name)
    
    def get_model_options(
        self,
        temperature=0.7,
        per_example_max_decode_steps=512,
        per_example_top_p=1,
        n_sample=1,
    ):
        return dict(
            temperature=temperature,
            n=n_sample,
            top_p=per_example_top_p,
            max_tokens=per_example_max_decode_steps,
        )

    def generate(self, prompt):
        try:
            from vllm import SamplingParams
            options = self.get_model_options()
            sampling_params = SamplingParams(**options)
            # messages = [
            #     {"role": "system", "content": self.system_message},
            #     {"role": "user", "content": prompt},]
            # inputs = self.tokenizer.apply_chat_template(messages,
            #                             add_generation_prompt=True,
            #                             tokenize=False)
            completion = self.llm.generate(prompt, sampling_params)
            return completion[0].outputs[0].text
        except Exception as e:
            print("Generation Error:", e)
            return "None"