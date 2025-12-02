# iterate through all the task configurations in the tasks directory
# and generate a csv of the task ids, subtask ids, and task descriptions

import os
import json
import csv
from typing import List, Dict, Tuple
from pathlib import Path
from uuid import uuid4
import shutil
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Force output to the console
handler = logging.StreamHandler()
logger = logging.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Define the base tasks directory
TASKS_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))) / "tasks"

def get_all_task_files() -> List[Tuple[str, str, Path]]:
    """
    Find all task JSON files in the tasks directory structure.
    
    Returns:
        List of tuples (task_id, subtask_id, file_path)
    """
    task_files = []
    
    # Walk through the tasks directory
    logging.info(f"Scanning directory: {TASKS_DIR}")
    
    for task_dir in TASKS_DIR.iterdir():
        if not task_dir.is_dir() or not task_dir.name[0].isdigit():
            continue
        
        task_id = task_dir.name
        subtasks_dir = task_dir / "subtasks"
        
        if not subtasks_dir.exists() or not subtasks_dir.is_dir():
            logging.warning(f"No subtasks directory found for task {task_id}")
            continue
            
        for subtask_file in subtasks_dir.iterdir():
            if subtask_file.suffix == ".json":
                subtask_id = subtask_file.stem
                task_files.append((task_id, subtask_id, subtask_file))
    
    return task_files

def extract_task_info(task_file: Path) -> Dict:
    """
    Extract relevant information from a task JSON file.
    
    Args:
        task_file: Path to the task JSON file
        
    Returns:
        Dictionary containing the extracted task information
    """
    try:
        with open(task_file, 'r') as f:
            task_data = json.load(f)
        
        # Extract the task description
        task_description = task_data.get("task", "")
        
        # Extract other relevant fields
        username = task_data.get("username", "")
        date = task_data.get("date", "")
        
        # Get the task_id from the file path
        task_id = task_file.parent.parent.name
        
        # Find all file extensions in the testbed folder
        testbed_path = task_file.parent.parent / "testbed"
        file_extensions = set()
        
        if testbed_path.exists() and testbed_path.is_dir():
            # Walk through all files in testbed and collect extensions
            for root, _, files in os.walk(testbed_path):
                for file in files:
                    # Get the file extension (without the dot)
                    _, ext = os.path.splitext(file)
                    if ext:  # Only add non-empty extensions
                        file_extensions.add(ext[1:].lower())  # Remove the leading dot
        
        # Sort extensions for consistent output
        sorted_extensions = sorted(list(file_extensions))
        
        return {
            "task_description": task_description,
            "username": username,
            "date": date,
            "file_extensions": ",".join(sorted_extensions),
            "num_file_types": len(sorted_extensions)
        }
    
    except Exception as e:
        logging.error(f"Error processing {task_file}: {e}")
        return {
            "task_description": f"ERROR: {str(e)}",
            "username": "",
            "date": "",
            "file_extensions": "",
            "num_file_types": 0
        }

# Main execution
logging.info("Starting task extraction")

with open('tasks.csv', 'w', newline='') as csvfile:
    # Set up CSV writer with appropriate headers
    fieldnames = ['task_id', 'subtask_id', 'task_description', 'username', 'date', 'file_extensions', 'num_file_types']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    
    # Write the header row
    writer.writeheader()
    
    # Get all task files
    task_files = get_all_task_files()
    logging.info(f"Found {len(task_files)} task files")
    
    # Process each task file
    for task_id, subtask_id, file_path in sorted(task_files):
        try:
            # Extract task information
            task_info = extract_task_info(file_path)
            
            # Write the task information to the CSV
            # Add apostrophes to task_id and subtask_id to prevent Excel from converting them to dates
            writer.writerow({
                'task_id': f"'{task_id}",  # Add apostrophe prefix to force Excel to treat as text
                'subtask_id': f"'{subtask_id}",  # Add apostrophe prefix to force Excel to treat as text
                'task_description': task_info['task_description'],
                'username': task_info['username'],
                'date': task_info['date'],
                'file_extensions': task_info['file_extensions'],
                'num_file_types': task_info['num_file_types']
            })
            
        except Exception as e:
            logging.error(f"Error processing {task_id}.{subtask_id}: {e}")

logging.info("Task extraction complete. Results saved to tasks.csv")

# Print summary information
with open('tasks.csv', 'r') as f:
    lines = f.readlines()
    logging.info(f"CSV file contains {len(lines)-1} tasks")
    logging.info(f"First 3 lines of the CSV:")
    for i in range(min(4, len(lines))):
        logging.info(lines[i].strip())

if __name__ == "__main__":
    # The script will execute automatically when run directly
    pass
