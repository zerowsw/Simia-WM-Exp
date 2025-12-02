
# PROMPT_DICT can be overridden by reading from exp_config['prompt_file']
PROMPT_DICT = {
    'prompt_undecided_app': (
        '##Task: {task}\n'
        '##Available apps: {available_apps}\n'
        '##Instruction:\n'
        ' - choose an app from the available apps: {{"app": "system", "action": "switch_app", "target_app": [THE_APP_YOU_CHOOSE]}}\n'
        '##Command:'
    ),
    'prompt_undecided_app_w_history': (
        '##Task: {task}\n'
        '##History:\n'
        '{history}'
        '##Available apps: {available_apps}\n'
        '##Instruction:\n'
        ' - choose an app from the available apps: {{"app": "system", "action": "switch_app", "target_app": [THE_APP_YOU_CHOOSE]}}\n'
        '##Command:'
    ),
    'prompt_decided_app': (
        '##Task: {task}\n'
        '##History:\n'
        '{history}'
        '##Current apps: {current_app}\n'
        '##Instruction: Choose one action from the list as the next step. Use the JSON schema provided to format your response.\n'
        '{detailed_instruction}'
        ' - switch to another app among {available_apps}: {{"app": "system", "action": "switch_app", "target_app": [THE_APP_YOU_CHOOSE]}}\n'
        ' - finish the task with your answer as None if the task is not a question: {{"app": "system", "action": "finish_task", "answer": "None"}}\n'
        ' - finish the task with your answer if the task is a question: {{"app": "system", "action": "finish_task", "answer": [ANSWER]}}\n'
        '##Command:'
    ),
    'system_message': (
            "Today is {date} ({weekday}). The current time is {time}. You are an AI assistant for user {username}.\n"
            "You can help solve the task step by step.\n"
            "You can interact with an operation system and use apps to solve the task.\n"
            "You must follow the instructions and use the given json format to call APIs.\n"
            "You can only generate one action at a time.\n"
            "You can find files for your task in `{testbed_data_path}`. If you don't know the filenames, please switch to shell app and call commands to list the directory.\n"
            "*Safety*: You may only manipulate/create files/folders under the `{testbed_data_path}` directory. You are not allowed to access any other data files or directories."
            "You have following apps installed in the system:\n"
            "{app_introduction}"
        )
}