"""
Configuration loading utilities for Blueprint.

This module provides utility functions for loading and parsing
configuration files for the Blueprint system.
"""

import os
from ruamel.yaml import YAML
from typing import Dict, Any, Optional, TextIO
import logging
from utils.config.config_classes import BlueprintConfig
logging.basicConfig(level=logging.INFO)

yaml = YAML()
yaml.preserve_quotes = True  # Preserve the original quoting style
yaml.width = 4096


def load_yaml_config(config_path: str) -> Dict[str, Any]:
    """
    Load a YAML configuration file.
    
    Args:
        config_path: Path to the YAML configuration file
        
    Returns:
        Dictionary containing the configuration
        
    Raises:
        FileNotFoundError: If the configuration file does not exist
        yaml.YAMLError: If the YAML file is invalid
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    with open(config_path, 'r') as f:
        config_dict = yaml.load(f)
    
    return config_dict


def load_blueprint_config(config_path: str, 
                         interpolate_vars: bool = True,
                         variables: Optional[Dict[str, str]] = None) -> BlueprintConfig:
    """
    Load and parse a Blueprint configuration file.
    
    Args:
        config_path: Path to the YAML configuration file
        interpolate_vars: Whether to interpolate variables in the configuration
        variables: Dictionary of variables to interpolate, if None, environment variables are used
        
    Returns:
        BlueprintConfig instance
        
    Raises:
        FileNotFoundError: If the configuration file does not exist
        yaml.YAMLError: If the YAML file is invalid
        KeyError: If a required configuration value is missing
    """
    config_dict = load_yaml_config(config_path)
    
    if interpolate_vars:
        config_dict = _interpolate_variables(config_dict, variables or os.environ)
    
    return BlueprintConfig.from_dict(config_dict)


def _interpolate_variables(config: Dict[str, Any], 
                          variables: Dict[str, str]) -> Dict[str, Any]:
    """
    Interpolate variables in a configuration dictionary.
    
    Args:
        config: Configuration dictionary
        variables: Dictionary of variables to interpolate
        
    Returns:
        Configuration dictionary with variables interpolated
    """
    result = {}
    
    for key, value in config.items():
        if isinstance(value, dict):
            result[key] = _interpolate_variables(value, variables)
        elif isinstance(value, str) and value.startswith('$'):
            var_name = value[1:]
            if var_name in variables:
                result[key] = variables[var_name]
            else:
                # Keep the original value if the variable is not found
                result[key] = value
        else:
            result[key] = value
    
    return result

# save to an open filehandle
    yaml.dump(config.to_dict(), file)

def save_blueprint_config(config: BlueprintConfig, file_or_path: TextIO | str) -> None:
    """
    Save a Blueprint configuration to a YAML file.
    
    Args:
        config: BlueprintConfig instance to save
        config_path: Path to save the configuration file
    """
    if isinstance(file_or_path, (str, os.PathLike)):
        os.makedirs(os.path.dirname(file_or_path), exist_ok=True)
        with open(file_or_path, 'w') as f:
            yaml.dump(config.to_dict(), f)
        logging.info(f"Configuration saved to {file_or_path}")
    elif hasattr(file_or_path, "write"):
        yaml.dump(config.to_dict(), file_or_path)
    else:
        raise ValueError("file_or_path must be a string or a file-like object")

