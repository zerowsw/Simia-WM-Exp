"""
Blueprint configuration data classes.

This module provides data classes that represent the configuration structure
of the Blueprint system, based on the base_config.yaml template.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
import yaml


@dataclass
class MemoryConfig:
    """Configuration for model memory capabilities."""
    
    mode: Optional[str] = None


@dataclass
class ModelConfig:
    """Configuration for the model being used."""
    
    id: str
    name: str
    memory: MemoryConfig = field(default_factory=MemoryConfig)

@dataclass
class DockerConfig:
    """Configuration for Docker settings."""
    docker_name: str = 'officebench'
    dockerfile_path: str = './docker/Dockerfile'

@dataclass
class EnvConfig:
    """Configuration for the task environment."""
    
    max_iter: int = 50


@dataclass
class ExperimentConfig:
    """Configuration for the experiment."""
    
    exp_id: str
    model_id: str
    exp_dir: Optional[Path] = None
    evaluation: str = "online"
    memory: bool = False
    use_thinking_tokens: bool = False
    use_scratchpad: bool = False


@dataclass
class BlueprintConfig:
    """Root configuration class for Blueprint."""
    
    experiment: ExperimentConfig
    env: EnvConfig
    model: ModelConfig
    docker: DockerConfig
    prompt_file: str = "configs/prompts.json"

    def set_model_id(self, model_id: str):
        """
        Set the model ID in the experiment configuration.
        
        Args:
            model_id: The new model ID to set
        """
        self.experiment.model_id = model_id
        if model_id != self.model.id:
            self.model.id = model_id
            with open('configs/models.yaml', 'r') as file:
                models_config = yaml.load(file)
            if model_id in models_config["model"]:
                self.model.name = models_config["model"][model_id]["name"]
            else:
                raise ValueError(f"Model ID {model_id} not found in models.yaml")
    
    def set_experiment_id(self, exp_id: str, repo_root_dir: str):
        """
        Set the experiment ID in the experiment configuration.
        
        Args:
            exp_id: The new experiment ID to set
        """
        self.experiment.exp_id = exp_id
        self.experiment.exp_dir = Path(f"{repo_root_dir}/exp/{exp_id}")
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "BlueprintConfig":
        """
        Create a BlueprintConfig instance from a dictionary.
        
        Args:
            config_dict: Dictionary containing configuration values
            
        Returns:
            Configured BlueprintConfig instance
        """
        experiment_config = ExperimentConfig(
            exp_id=config_dict["experiment"]["exp_id"],
            model_id=config_dict["experiment"]["model_id"],
            evaluation=config_dict["experiment"]["evaluation"],
            memory=config_dict["experiment"]["memory"],
            use_thinking_tokens=config_dict["experiment"]["use_thinking_tokens"],
            use_scratchpad=config_dict["experiment"]["use_scratchpad"]
        )
        
        env_config = EnvConfig(
            max_iter=config_dict["env"]["max_iter"]
        )
        
        memory_config = MemoryConfig(
            mode=config_dict["model"]["memory"]["mode"]
        )

        docker_config = DockerConfig(
            docker_name=config_dict["docker"]["docker_name"],
            dockerfile_path=config_dict["docker"]["dockerfile_path"]
        )
        
        model_config = ModelConfig(
            id=config_dict["model"]["id"],
            name=config_dict["model"]["name"],
            memory=memory_config
        )
        
        return cls(
            experiment=experiment_config,
            env=env_config,
            model=model_config,
            docker=docker_config,
            prompt_file=config_dict.get("prompt_file", "configs/prompts.json")
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the configuration to a dictionary.
        
        Returns:
            Dictionary representation of the configuration
        """
        return {
            "experiment": {
                "exp_id": self.experiment.exp_id,
                "model_id": self.experiment.model_id,
                "evaluation": self.experiment.evaluation,
                "memory": self.experiment.memory,
                "use_thinking_tokens": self.experiment.use_thinking_tokens,
                "use_scratchpad": self.experiment.use_scratchpad
            },
            "env": {
                "max_iter": self.env.max_iter
            },
            "model": {
                "id": self.model.id,
                "name": self.model.name,
                "memory": {
                    "mode": self.model.memory.mode
                }
            },
            "docker": {
                "docker_name": self.docker.docker_name,
                "dockerfile_path": self.docker.dockerfile_path
            },
            "prompt_file": self.prompt_file
        }


