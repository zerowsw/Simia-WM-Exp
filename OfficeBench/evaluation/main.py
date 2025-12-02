"""
Evaluation module for Blueprint tasks.

This module provides functionality to evaluate task results and generate reports.
"""

import fire
import json
import os
import logging

# Import our local modules directly, not as part of a package
from .report_generator import ReportGenerator
from . import task_discovery
from .task_evaluator import TaskEvaluator, TaskEvaluation


# Constants and configuration
DEFAULT_MODEL = 'gpt-4o-2024-05-13'
DEFAULT_TAG = 'test'
DEFAULT_RESULT_DIR = './results'
DEFAULT_OUTPUT_SUBDIR = 'outputs'


def configure_logging(debug):
    """
    Configure logging settings based on debug flag.
    
    Args:
        debug: Whether to enable debug logging
    """
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=log_level)
    logging.getLogger().setLevel(log_level)
    logging.getLogger("utils.evaluate").setLevel(log_level)
    logging.debug("Test")


def main(model_name=DEFAULT_MODEL, 
         tag_name=DEFAULT_TAG, 
         result_dir=DEFAULT_RESULT_DIR, 
         output_subdir=DEFAULT_OUTPUT_SUBDIR, 
         debug:bool=False, 
         list_missing:bool=False, 
         html:bool=False,
         web:bool=False,
         task=None):
    """
    Main function to evaluate tasks and generate reports.
    
    Args:
        model_name: Name of the model to evaluate
        tag_name: Tag for the evaluation
        result_dir: Directory to store results
        output_subdir: Subdirectory for outputs
        debug: Enable debug logging
        list_missing: List missing result cases
        html: Generate HTML report
        web: Generate web report
        task: Specific task to evaluate (optional)
    """
    # Configure logging
    configure_logging(debug)
    logging.debug("Debug mode is enabled")
    
    # Create result directory if it doesn't exist
    if not os.path.exists(result_dir):
        os.makedirs(result_dir)
    
    # Set up file paths
    result_path = f'{result_dir}/{model_name.replace("/", "_")}_{tag_name}_result.jsonl'
    
    # Discover tasks
    task_discovery_obj = task_discovery.TaskDiscovery()
    all_tasks_info = task_discovery_obj.discover_tasks()
    
    # Initialize the evaluator
    evaluator = TaskEvaluator(model_name, tag_name, output_subdir, debug)
    
    # Open result file for writing task-specific results
    with open(result_path, 'w') as f_result:
        # Evaluate each task
        for task_id, subtask_id in all_tasks_info:
            if task is not None and task_id != task:
                continue
            
            # Evaluate the task
            evaluation = evaluator.evaluate_task(task_id, subtask_id)
            
            # Write task result to file
            f_result.write(json.dumps(evaluation.to_dict()) + '\n')
    
    # Generate statistics
    stats = evaluator.generate_stats()
    
    # Print report to console
    print(ReportGenerator.format_overall_report(stats))
    
    # Save JSON report
    ReportGenerator.save_json_report(stats, result_path)
    
    # Print missing results if requested
    if list_missing:
        logging.debug(f"Unfound result cases:")
        for task_id, subtask_id in sorted(stats['unfound_result_cases'], 
                                         key=lambda x: tuple(map(int, x[0].split('-'))) + (int(x[1]),)):
            logging.debug(f"{task_id} {subtask_id}")
        logging.debug('Total unfound result cases: %d', len(stats['unfound_result_cases']))
    
    # Generate HTML report if requested
    if html:
        if web:
            return ReportGenerator.make_html_report(stats, evaluator.html_results, None)
        else:
            ReportGenerator.make_html_report(stats, evaluator.html_results, result_path)


# Update the main function to accept a debug flag
if __name__ == '__main__':
    fire.Fire(main)
