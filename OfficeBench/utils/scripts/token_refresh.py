import sys
import os
import fire
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from generate_token import main as generate_token
import time

def main(model_name: str = 'dev-phi-35-vision-instruct'):
    """
    Generate a token for the LLM API.
    """
    # every 5 minutes
    while True:
        try:
            generate_token(model_name=model_name)
        except Exception as e:
            print(f"Error generating token: {e}")
            raise e
        time.sleep(300)

if __name__ == '__main__':
    fire.Fire(main)