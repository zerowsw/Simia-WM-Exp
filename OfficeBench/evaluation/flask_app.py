"""
Flask web application for Blueprint task evaluation results with improved visualization.

This module provides a web interface to view evaluation results and run new evaluations
with enhanced parsing and visualization of task history steps.
"""

from flask import Flask, render_template_string, render_template, request
import time
import os
import json
import markdown as md
import re
import glob
import sys
import argparse
from . import main as evaluate
from . import report_generator
from .experiment_discovery import ExperimentDiscovery
import traceback

app = Flask(__name__)

# Default values for model and tag
DEFAULT_MODEL_NAME = "azure/gpt-4o"
DEFAULT_TAG_NAME = "test"


def parse_task_history(latest_report, task_history):
    """Parse the task history from the latest report to extract structured data."""
    parsed_data = {
        'task_description': '',
        'steps': [],
        'current_apps': '',
        'instruction': '',
        'history': '',
        'additional_data': None,
        'system_prompt': ''
    }
    
    # If latest_report is a list, extract different elements
    if isinstance(latest_report, list) and len(latest_report) > 1:
        # Extract system prompt from first element (index 0)
        if len(latest_report) > 0:
            try:
                parsed_data['system_prompt'] = str(latest_report[0])
            except (IndexError, TypeError):
                parsed_data['system_prompt'] = ''
        
        # Use the second element (index 1) for parsing task history
        text_to_parse = latest_report[1]
        
        # Check if there's additional JSON data in the third element
        if len(latest_report) > 2:
            try:
                parsed_data['additional_data'] = latest_report[2]
            except (IndexError, TypeError):
                parsed_data['additional_data'] = None
    elif isinstance(latest_report, str):
        text_to_parse = latest_report
    else:
        return parsed_data
    
    # Split the text into different sections
    sections = {}
    current_section = 'task_description'
    current_content = []
    
    lines = text_to_parse.split('\n')
    
    for line in lines:
        if line.strip().startswith('##History:'):
            if current_content:
                sections[current_section] = '\n'.join(current_content).strip()
            current_section = 'history'
            current_content = []
        elif line.strip().startswith('##Current apps:'):
            if current_content:
                sections[current_section] = '\n'.join(current_content).strip()
            current_section = 'current_apps'
            current_content = [line.strip()[15:].strip()]  # Remove "##Current apps:" prefix
        elif line.strip().startswith('##Instruction:'):
            if current_content:
                sections[current_section] = '\n'.join(current_content).strip()
            current_section = 'instruction'
            current_content = [line.strip()[14:].strip()]  # Remove "##Instruction:" prefix
        else:
            current_content.append(line)
    
    # Don't forget the last section
    if current_content:
        sections[current_section] = '\n'.join(current_content).strip()
    
    # Extract task description
    if 'task_description' in sections:
        parsed_data['task_description'] = sections['task_description']
    
    # Extract current apps
    if 'current_apps' in sections:
        parsed_data['current_apps'] = sections['current_apps']
    
    # Extract instruction
    if 'instruction' in sections:
        parsed_data['instruction'] = sections['instruction']
    
    if 'history' in sections:
        parsed_data['history'] = sections['history']


    # Handle cases where there's no " -> " separator
    for step_num, task_entry in enumerate(task_history):
        try:
            step_action = json.loads(task_entry["action"]) 
        except json.JSONDecodeError:
            step_action = task_entry["action"]
        parsed_data['steps'].append({
            'step_num': step_num,
            'thought': task_entry["thinking"],
            'action': step_action,
            'result': task_entry["env_observation"],
        })
    
    return parsed_data


def format_json_safely(data):
    """Safely format JSON data for display."""
    if not data:
        return "No data available"
    
    try:
        return json.dumps(data, indent=2)
    except (TypeError, ValueError):
        return str(data)


def escape_html(text):
    """Escape HTML characters in text."""
    if not text:
        return ""
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#x27;'))


def format_text_with_breaks(text):
    """Format text with proper line breaks for escape characters."""
    if not text:
        return ""
    
    # Convert escape characters to proper line breaks and formatting
    formatted = str(text)
    
    # Handle various escape sequences and actual newlines
    formatted = (formatted
                .replace('\\n', '<br>')
                .replace('\n', '<br>')  # Handle actual newlines
                .replace('\\t', '&nbsp;&nbsp;&nbsp;&nbsp;')
                .replace('\t', '&nbsp;&nbsp;&nbsp;&nbsp;')  # Handle actual tabs
                .replace('\\r', '<br>')
                .replace('\r', '<br>')  # Handle actual carriage returns
                .replace('\\\\n', '<br>')
                .replace('\\\\t', '&nbsp;&nbsp;&nbsp;&nbsp;')
                .replace('\\\\r', '<br>')
                # Handle dashes that should be on new lines
                .replace('\\n--------------------------------------------------', '<br>--------------------------------------------------')
                .replace('--------------------------------------------------', '<br>--------------------------------------------------<br>')
                # Handle common patterns
                .replace('Summary:', '<br><strong>Summary:</strong>')
                .replace('Start Time:', '<br><strong>Start Time:</strong>')
                .replace('End Time:', '<br><strong>End Time:</strong>')
                .replace('Description:', '<br><strong>Description:</strong>')
                .replace('Location:', '<br><strong>Location:</strong>'))
    
    # Clean up multiple consecutive line breaks
    formatted = re.sub(r'(<br>){3,}', '<br><br>', formatted)
    
    # Escape HTML characters (but preserve our <br> and formatting tags)
    formatted = (formatted
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#x27;'))
    
    # Restore our formatting tags
    formatted = (formatted
                .replace('&lt;br&gt;', '<br>')
                .replace('&lt;strong&gt;', '<strong>')
                .replace('&lt;/strong&gt;', '</strong>')
                .replace('&amp;nbsp;', '&nbsp;'))
    
    # Remove leading line breaks
    formatted = re.sub(r'^(<br>)+', '', formatted)
    
    return formatted


def generate_task_html(task_id, subtask_id, model_name, tag, trial_id, is_pass, result_file, task_result, parsed_data, raw_report=None):
    """Generate HTML for task visualization with better formatting."""
    
    status_class = "pass" if is_pass else "fail"
    status_text = "PASS" if is_pass else "FAIL"
    
    trials_div = make_trials_div(task_id, subtask_id, trial_id, model_name, tag)
    
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Task {task_id}.{subtask_id} - {model_name} {tag}</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 1200px;
                margin: 0 auto;
                padding: 20px;
                background: #f8f9fa;
            }}
            .header {{
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            }}
            .status-badge {{
                display: inline-block;
                padding: 4px 12px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 0.9em;
            }}
            .status-badge.pass {{
                background: #d4edda;
                color: #155724;
                border: 1px solid #c3e6cb;
            }}
            .status-badge.fail {{
                background: #f8d7da;
                color: #721c24;
                border: 1px solid #f5c6cb;
            }}
            .trials-nav {{
                margin: 15px 0;
                padding: 10px;
                background: #e9ecef;
                border-radius: 4px;
                font-size: 0.9em;
            }}
            .trials-nav a {{
                color: #007bff;
                text-decoration: none;
                margin-right: 10px;
                padding: 2px 6px;
                border-radius: 3px;
            }}
            .trials-nav a:hover {{
                background: #007bff;
                color: white;
            }}
            .task-description {{
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            }}
            .task-description-content {{
                line-height: 1.8;
                font-size: 1.1em;
                color: #495057;
            }}
            .step {{
                background: white;
                margin-bottom: 15px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                overflow: hidden;
                border-left: 4px solid #007bff;
            }}
            .step-header {{
                background: linear-gradient(135deg, #007bff 0%, #0056b3 100%);
                color: white;
                padding: 15px 20px;
                font-weight: bold;
                cursor: pointer;
                user-select: none;
                display: flex;
                justify-content: space-between;
                align-items: center;
                transition: background 0.3s ease;
            }}
            .step-header:hover {{
                background: linear-gradient(135deg, #0056b3 0%, #004085 100%);
            }}
            .step-toggle {{
                font-size: 1.2em;
                transition: transform 0.3s ease;
            }}
            .step-toggle.collapsed {{
                transform: rotate(-90deg);
            }}
            .step-content {{
                padding: 20px;
                display: block;
                transition: all 0.3s ease;
            }}
            .step-content.collapsed {{
                display: none;
            }}
            .thought {{
                background: #f8f9fa;
                padding: 15px;
                border-left: 4px solid #007bff;
                margin-bottom: 15px;
                border-radius: 0 4px 4px 0;
            }}
            .thought-header {{
                color: #007bff;
                font-weight: bold;
                margin-bottom: 8px;
                display: flex;
                align-items: center;
            }}
            .thought-content {{
                font-style: italic;
                color: #495057;
                line-height: 1.8;
                word-wrap: break-word;
            }}
            .action {{
                background: #fff3cd;
                padding: 15px;
                border-left: 4px solid #ffc107;
                margin-bottom: 15px;
                border-radius: 0 4px 4px 0;
            }}
            .action-header {{
                color: #856404;
                font-weight: bold;
                margin-bottom: 8px;
                display: flex;
                align-items: center;
            }}
            .result {{
                background: #d1ecf1;
                padding: 15px;
                border-left: 4px solid #17a2b8;
                border-radius: 0 4px 4px 0;
            }}
            .result-header {{
                color: #0c5460;
                font-weight: bold;
                margin-bottom: 8px;
                display: flex;
                align-items: center;
            }}
            .result-content {{
                line-height: 1.6;
                word-wrap: break-word;
                white-space: pre-wrap;
            }}
            .json-code {{
                background: #f8f9fa;
                padding: 10px;
                border-radius: 4px;
                font-family: 'Monaco', 'Consolas', monospace;
                font-size: 0.9em;
                overflow-x: auto;
                white-space: pre-wrap;
                max-height: 300px;
                overflow-y: auto;
                border: 1px solid #e9ecef;
                margin-top: 8px;
            }}
            .back-link {{
                display: inline-block;
                margin-top: 20px;
                color: #007bff;
                text-decoration: none;
                padding: 8px 16px;
                border: 1px solid #007bff;
                border-radius: 4px;
                transition: all 0.3s ease;
            }}
            .back-link:hover {{
                background: #007bff;
                color: white;
            }}
            .task-metadata {{
                background: #f8f9fa;
                padding: 15px;
                border-radius: 4px;
                margin-bottom: 20px;
                font-size: 0.9em;
                border: 1px solid #e9ecef;
            }}
            .expand-all, .collapse-all {{
                border: none;
                padding: 10px 20px;
                border-radius: 4px;
                cursor: pointer;
                margin-right: 10px;
                font-weight: bold;
                transition: all 0.3s ease;
            }}
            .expand-all {{
                background: #28a745;
                color: white;
            }}
            .expand-all:hover {{
                background: #218838;
            }}
            .collapse-all {{
                background: #dc3545;
                color: white;
            }}
            .collapse-all:hover {{
                background: #c82333;
            }}
            .controls {{
                margin-bottom: 20px;
                text-align: center;
            }}
            .long-text {{
                max-height: 300px;
                overflow-y: auto;
                border: 1px solid #ddd;
                padding: 10px;
                border-radius: 4px;
                background: #f8f9fa;
            }}
            .step-summary {{
                font-size: 1em;
                color: #ffffff;
                margin-left: 10px;
                background: linear-gradient(135deg, #ffd700 0%, #ffed4e 100%);
                padding: 4px 12px;
                border-radius: 20px;
                font-weight: bold;
                text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
                box-shadow: 0 2px 4px rgba(0,0,0,0.2);
                border: 2px solid #ffcc00;
                color: #333;
                display: inline-block;
                min-width: 80px;
                text-align: center;
            }}
            .icon {{
                margin-right: 8px;
                font-size: 1.1em;
            }}
        </style>
        <script>
            function toggleStep(stepNum) {{
                const content = document.getElementById('step-content-' + stepNum);
                const toggle = document.getElementById('step-toggle-' + stepNum);
                
                content.classList.toggle('collapsed');
                toggle.classList.toggle('collapsed');
            }}
            
            function expandAll() {{
                document.querySelectorAll('.step-content').forEach(el => {{
                    el.classList.remove('collapsed');
                }});
                document.querySelectorAll('.step-toggle').forEach(el => {{
                    el.classList.remove('collapsed');
                }});
            }}
            
            function collapseAll() {{
                document.querySelectorAll('.step-content').forEach(el => {{
                    el.classList.add('collapsed');
                }});
                document.querySelectorAll('.step-toggle').forEach(el => {{
                    el.classList.add('collapsed');
                }});
            }}
            
            // Initialize all steps as collapsed
            document.addEventListener('DOMContentLoaded', function() {{
                collapseAll();
            }});
        </script>
    </head>
    <body>
        <div class="header">
            <h1>🎯 Task {task_id}.{subtask_id} Report</h1>
            <p><strong>Model:</strong> {model_name} | <strong>Tag:</strong> {tag} | <strong>Trial:</strong> {trial_id}</p>
            <span class="status-badge {status_class}">{status_text}</span>
            <div class="trials-nav">{trials_div}</div>
            <div class="task-metadata">
                <strong>📅 Last run:</strong> {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(result_file)))}<br>
                <strong>📊 Task Results:</strong>
                <div class="json-code">{format_json_safely(task_result)}</div>
            </div>
        </div>
        
        {f'''
        <div class="task-description">
            <h2>🔧 System Prompt</h2>
            <div class="task-description-content" style="background: #f0f0f0; padding: 15px; border-left: 4px solid #6c757d; border-radius: 0 4px 4px 0; margin: 10px 0;">
                {format_text_with_breaks(parsed_data['system_prompt'])}
            </div>
        </div>
        ''' if parsed_data.get('system_prompt') else ''}
        
        <div class="task-description">
            <h2>📋 Task Description</h2>
            <div class="task-description-content" style="background: #f8f9fa; padding: 15px; border-left: 4px solid #007bff; border-radius: 0 4px 4px 0; margin: 10px 0;">
                {format_text_with_breaks(parsed_data.get('task_description', 'No description available')) if parsed_data.get('task_description') else '<em style="color: #6c757d;">Task description not found in the parsed data. Raw data might be in a different format.</em>'}
            </div>
        </div>
        
        <div class="controls">
            <button class="expand-all" onclick="expandAll()">🔍 Expand All Steps</button>
            <button class="collapse-all" onclick="collapseAll()">📦 Collapse All Steps</button>
        </div>
        
        <h2>🔄 Execution History ({len(parsed_data.get('steps', []))} steps)</h2>
        
        {f'<div style="background: #fff3cd; padding: 10px; border-radius: 4px; margin: 10px 0; border-left: 4px solid #ffc107;"><strong>Debug Info:</strong> Found {len(parsed_data.get("steps", []))} steps in parsed data. Raw report has {len(raw_report)} items.</div>' if len(parsed_data.get('steps', [])) == 0 else ''}
    """
    
    # Add each step
    for step in parsed_data.get('steps', []):
        # Get action summary for header
        action_summary = ""
        if step['action']:
            if isinstance(step['action'], dict):
                if type(step['action']['action']) == str:
                    action_name = step['action'].get('action', '')
                    app_name = step['action'].get('app', '')
                else:
                    action_name = step['action']['action'].get('action', '')
                    app_name = step['action']['action'].get('app', '')
                if action_name and app_name:
                    action_summary = f"{app_name}.{action_name}"
                elif action_name:
                    action_summary = action_name
                elif app_name:
                    action_summary = app_name
        
        # Escape HTML in text content and format with line breaks
        thought = format_text_with_breaks(step['thought'])
        result = format_text_with_breaks(step['result'])
        
        # Handle long result text
        if len(step['result']) > 1000:
            result = f'<div class="long-text">{result}</div>'
        
        html_template += f"""
        <div class="step">
            <div class="step-header" onclick="toggleStep({step['step_num']})">
                <div>
                    <strong>Step {step['step_num']}</strong>
                    <span class="step-summary">{action_summary}</span>
                </div>
                <span class="step-toggle" id="step-toggle-{step['step_num']}">▼</span>
            </div>
            <div class="step-content" id="step-content-{step['step_num']}">
                <div class="thought">
                    <div class="thought-header">
                        <span class="icon">💭</span>
                        <strong>Thought Process</strong>
                    </div>
                    <div class="thought-content">{thought}</div>
                </div>
                
                <div class="action">
                    <div class="action-header">
                        <span class="icon">⚡</span>
                        <strong>Action Taken</strong>
                    </div>
                    <div class="json-code">{format_json_safely(step['action'])}</div>
                </div>
                
                <div class="result">
                    <div class="result-header">
                        <span class="icon">📋</span>
                        <strong>Result</strong>
                    </div>
                    <div class="result-content">{result}</div>
                </div>
            </div>
        </div>
        """
    
    # Add Current Apps section if available
    if parsed_data.get('current_apps'):
        html_template += f"""
        <div class="task-description" style="margin-top: 30px;">
            <h2>🔧 Current Apps</h2>
            <div class="task-description-content" style="background: #e8f5e8; padding: 15px; border-left: 4px solid #28a745; border-radius: 0 4px 4px 0; margin: 10px 0;">
                {format_text_with_breaks(parsed_data['current_apps'])}
            </div>
        </div>
        """
    
    # Add Instruction section if available
    if parsed_data.get('instruction'):
        html_template += f"""
        <div class="task-description" style="margin-top: 30px;">
            <h2>📖 Instruction & Final Action</h2>
            <div class="task-description-content" style="background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; border-radius: 0 4px 4px 0; margin: 10px 0;">
                {format_text_with_breaks(parsed_data['instruction'])}
            </div>
        </div>
        """
    
    # Add History section if available
    if parsed_data.get('history'):
        html_template += f"""
        <div class="task-description" style="margin-top: 30px;">
            <h2>📚 History</h2>
            <div class="task-description-content" style="background: #f3e5f5; padding: 15px; border-left: 4px solid #9c27b0; border-radius: 0 4px 4px 0; margin: 10px 0;">
                {format_text_with_breaks(parsed_data['history'])}
            </div>
        </div>
        """
    
    # Add Additional Data section if available
    if parsed_data.get('additional_data') is not None:
        html_template += f"""
        <div class="task-description" style="margin-top: 30px;">
            <h2>📊 Assistant Generation at last step</h2>
            <div class="task-description-content" style="background: #e3f2fd; padding: 15px; border-left: 4px solid #2196f3; border-radius: 0 4px 4px 0; margin: 10px 0;">
                <div class="json-code" style="margin-top: 0; max-height: 400px; overflow-y: auto;">
                    {format_json_safely(parsed_data['additional_data'])}
                </div>
            </div>
        </div>
        """
    
    # If no steps were found, show raw data for debugging
    if not parsed_data.get('steps'):
        html_template += f"""
        <div style="background: #f8d7da; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #dc3545;">
            <h3 style="color: #721c24;">⚠️ No steps found in parsed data</h3>
            <p style="color: #721c24;">Here's the raw data for debugging:</p>
            <div style="background: #fff; padding: 10px; border-radius: 4px; max-height: 400px; overflow-y: auto;">
                <pre style="white-space: pre-wrap; font-size: 0.9em;">{escape_html(str(raw_report))}</pre>
            </div>
        </div>
        """
    
    html_template += """
        <div style="text-align: center; margin-top: 30px;">
            <a href="/" class="back-link">← Back to Index</a>
        </div>
    </body>
    </html>
    """
    
    return html_template


def make_trials_div(task_id, subtask_id, current_trial_id, model_name, tag_name):
    """Generate HTML links for trials of a specific task and subtask."""
    trials_div_html = "🔄 Select trial: "
    
    try:
        all_trials = sorted(os.listdir(f'outputs/{model_name.replace("/","_")}_{tag_name}/'))
        for trial_id in all_trials:
            if not os.path.exists(f'outputs/{model_name.replace("/","_")}_{tag_name}/{trial_id}/{task_id}/{subtask_id}'):
                continue
            
            query_params = []
            if model_name:
                query_params.append(f"model={model_name}")
            if tag_name:
                query_params.append(f"tag={tag_name}")
            
            query_string = f"?{'&'.join(query_params)}" if query_params else ""
            
            # Create an HTML link for each trial
            if trial_id == current_trial_id:
                trials_div_html += f'<strong style="background: #007bff; color: white; padding: 2px 8px; border-radius: 3px; margin-right: 5px;">{trial_id}</strong> '
            else:
                trials_div_html += f'<a href="/task/{task_id}.{subtask_id}/{trial_id}{query_string}" style="margin-right: 5px;">{trial_id}</a> '
    except Exception as e:
        trials_div_html += f"<span style='color: red;'>Error loading trials: {str(e)}</span>"
    
    return trials_div_html


@app.route("/")
def index():
    """Render the main index page with a list of all experiments."""
    experiment_list = []
    result_files = glob.glob("results/*_overall.json")
    for result_file in result_files:
        try:
            with open(result_file, "r") as f:
                result = json.load(f)
                for app_tag in result['app_tags']:
                    if 'total_available' not in result['app_tags'][app_tag]:
                        result['app_tags'][app_tag]['total_available'] = int(result['app_tags'][app_tag].get('result_available_avg', 0))
                        result['app_tags'][app_tag]['success'] = int(result['app_tags'][app_tag].get('success_avg', 0))
                if 'total_available' not in result['overall']:
                    result['overall']['total_available'] = int(result['overall'].get('result_available_avg', 0))
                    result['overall']['success'] = int(result['overall'].get('success_avg', 0))
                if result['overall']['total_available'] > 0:
                    experiment_list.append(result)
        except Exception as e:
            app.logger.error(f"Error loading result file {result_file}: {e}")
    
    # Sort experiments by model name and tag
    experiment_list.sort(key=lambda x: x['overall']['success'], reverse=True)

    return render_template("index.html", 
                         experiment_list=experiment_list, 
                         default_model_name=DEFAULT_MODEL_NAME,
                         default_tag_name=DEFAULT_TAG_NAME)


@app.route("/exp")
def exp():
    """Run an evaluation with the specified model and tag."""
    # Get model_name and tag_name from query parameters, or use defaults
    model_name = request.args.get('model', DEFAULT_MODEL_NAME)
    tag = request.args.get('tag', DEFAULT_TAG_NAME)
    
    # Clean the model and tag names for file paths
    model_name_clean = model_name.replace("/", "_")
    tag_clean = tag.replace(":", "_").replace("/", "_")
    
    try:
        # Run the evaluation
        latest_report = evaluate.main(
            model_name=model_name_clean, 
            tag_name=tag_clean, 
            html=True, 
            web=True
        )
        return render_template_string(latest_report)
    except Exception as e:
        error_message = f"Error running evaluation: {str(e)}\n{traceback.format_exc()}"
        app.logger.error(error_message)
        return render_template_string(f"""
        <html>
        <head><title>Evaluation Error</title></head>
        <body>
            <h1>Error Running Evaluation</h1>
            <pre>{error_message}</pre>
            <p><a href="/">Back to index</a></p>
        </body>
        </html>
        """)


@app.route('/task/<task_id>.<subtask_id>', defaults={'trial_id': '0'})
@app.route("/task/<task_id>.<subtask_id>/<trial_id>")
def task_detail(task_id, subtask_id, trial_id=0):
    """Show details for a specific task and subtask."""
    # Get model_name and tag_name from query parameters, or use defaults
    model_name = request.args.get('model', DEFAULT_MODEL_NAME)
    tag = request.args.get('tag', DEFAULT_TAG_NAME)
    
    # Clean the model and tag names for file paths
    model_name_clean = model_name.replace("/", "_")
    tag_clean = tag.replace(":", "_").replace("/", "_")
    
    try:
        # Load task results
        all_results_path = f"results/{model_name_clean}_{tag_clean}_result.jsonl"
        if not os.path.exists(all_results_path):
            return render_template_string(f"""
            <html>
            <head><title>Task Results Not Found</title></head>
            <body>
                <h1>Task Results Not Found</h1>
                <p>No results found for model {model_name} with tag {tag}.</p>
                <p><a href="/">Back to index</a></p>
            </body>
            </html>
            """)
            
        with open(all_results_path, "r") as f:
            all_results = f.readlines()
        all_results = [json.loads(line) for line in all_results]
        task_result = [result for result in all_results if result['task_id'] == task_id and result['subtask_id'] == subtask_id]
        
        # Load LLM history
        output_folder = f'outputs/{model_name.replace("/","_")}_{tag}/{trial_id}/{task_id}/{subtask_id}'
        result_file = f"{output_folder}/llm_history.json"
        env_result_file = f"{output_folder}/env_history.json"

        if not os.path.exists(result_file):
            return render_template_string(f"""
            <html>
            <head><title>Task History Not Found</title></head>
            <body>
                <h1>Task History Not Found</h1>
                <p>No LLM history found for task {task_id}.{subtask_id} with model {model_name} and tag {tag}.</p>
                <p><a href="/">Back to index</a></p>
            </body>
            </html>
            """)
            
        with open(result_file, "r") as f:
            latest_report = json.load(f)
            assert isinstance(latest_report, list), "Expected a list of results"
        
        with open(env_result_file, "r") as f:
            env_history = json.load(f)
            assert isinstance(env_history, list), "Expected a list of environment history"

        task_history = []
        for lm_entry, env_entry in zip(latest_report, env_history):
            gen = lm_entry[-1]
            # Parse <think>...</think> and <action>...</action> tags in gen
            think_match = re.search(r"<think>(.*?)</think>", gen, re.DOTALL)
            action_match = re.search(r"<action>(.*?)</action>", gen, re.DOTALL)
            thinking = think_match.group(1).strip() if think_match else ""
            action = action_match.group(1).strip() if action_match else ""
            _action, _observation = env_entry[0], env_entry[1]
            task_history.append({
                "thinking": thinking,
                "action": action,
                "env_action": _action,
                "env_observation": _observation,
            })
        
        latest_report = latest_report[-1]  # Get the latest report

        is_pass = task_result[0]['is_pass'][int(trial_id)] if len(task_result) > 0 else False
        
        # Parse the history steps for better visualization
        parsed_data = parse_task_history(latest_report, task_history)
        
        # Generate HTML with better visualization
        return render_template_string(generate_task_html(
            task_id, subtask_id, model_name, tag, trial_id, 
            is_pass, result_file, task_result, parsed_data, latest_report
        ))
        
    except Exception as e:
        error_message = f"Error loading task details: {str(e)}\n{traceback.format_exc()}"
        app.logger.error(error_message)
        return render_template_string(f"""
        <html>
        <head><title>Task Detail Error</title></head>
        <body>
            <h1>Error Loading Task Details</h1>
            <pre>{error_message}</pre>
            <p><a href="/">Back to index</a></p>
        </body>
        </html>
        """)


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Blueprint Evaluation Dashboard - Improved Version')
    parser.add_argument('--port', type=int, default=5001, help='Port to run the server on (default: 5001)')
    parser.add_argument('--host', type=str, default="0.0.0.0", help='Host to run the server on (default: 0.0.0.0)')
    parser.add_argument('--debug', action='store_true', default=True, help='Run in debug mode (default: True)')
    args = parser.parse_args()
    
    # Run the Flask application with provided arguments
    app.run(debug=args.debug, host=args.host, port=args.port)

# To run this improved version:
# python -m evaluation.flask_app_improved
