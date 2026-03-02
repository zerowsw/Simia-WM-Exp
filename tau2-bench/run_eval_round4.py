#!/usr/bin/env python3
"""
Round 4 Evaluation Script - Sequential execution (bypasses ThreadPoolExecutor bug)

The ThreadPoolExecutor in run_tasks() causes litellm.AuthenticationError even though
direct run_task() calls work perfectly. This script bypasses that by calling run_task()
directly in a loop.

Usage:
    python run_eval_round4.py --model Qwen/Qwen2.5-7B-Instruct --domain airline \
        --num-trials 3 --save-to data/simulations/round4/baseline.json
"""
import json
import os
import random
import sys
import uuid
from pathlib import Path

from loguru import logger

# Add tau2 to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from tau2.run import run_task, load_tasks, get_environment_info
from tau2.data_model.simulation import Results, SimulationRun, TerminationReason
from tau2.data_model.message import SystemMessage
from tau2.evaluator.evaluator import RewardInfo, EvaluationType
from tau2.metrics.agent_metrics import compute_metrics
from tau2.utils.utils import get_now


def run_evaluation(
    domain: str,
    model_path: str,
    user_llm: str,
    num_trials: int = 3,
    max_steps: int = 200,
    max_errors: int = 10,
    save_to: str = None,
    task_ids: list = None,
    seed: int = 300,
):
    """Run evaluation sequentially (bypasses ThreadPoolExecutor issue)"""
    tasks = load_tasks(domain)
    if task_ids:
        tasks = [t for t in tasks if t.id in task_ids]

    # Generate seeds for each trial
    random.seed(seed)
    seeds = [random.randint(0, 1000000) for _ in range(num_trials)]

    # Create results container
    from tau2.run import get_info
    info = get_info(
        domain=domain,
        agent='llm_agent',
        user='user_simulator',
        llm_agent=f'openai/{model_path}',
        llm_args_agent={'temperature': 0.0},
        llm_user=user_llm,
        llm_args_user={'temperature': 0.0},
        num_trials=num_trials,
        max_steps=max_steps,
        max_errors=max_errors,
        seed=seed,
    )

    results = Results(
        info=info,
        tasks=tasks,
        simulations=[],
    )

    # Check for existing results to resume
    done_runs = set()
    if save_to:
        save_path = Path(save_to)
        if save_path.exists():
            logger.info(f"Found existing results at {save_to}, resuming...")
            with open(save_path, "r") as f:
                prev_results = Results.model_validate_json(f.read())
            results.simulations = prev_results.simulations
            done_runs = set(
                (sim.trial, sim.task_id, sim.seed)
                for sim in prev_results.simulations
            )
            logger.info(f"Loaded {len(done_runs)} completed runs")

    total_runs = len(tasks) * num_trials
    completed = len(done_runs)

    for trial in range(num_trials):
        trial_seed = seeds[trial]
        for i, task in enumerate(tasks):
            # Skip if already done
            if (trial, task.id, trial_seed) in done_runs:
                logger.info(f"Skipping task {task.id}, trial {trial+1} (already done)")
                continue

            completed += 1
            logger.info(f"[{completed}/{total_runs}] Task {task.id}, trial {trial+1}/{num_trials}")

            try:
                simulation = run_task(
                    domain=domain,
                    task=task,
                    agent='llm_agent',
                    user='user_simulator',
                    llm_agent=f'openai/{model_path}',
                    llm_args_agent={'temperature': 0.0, 'max_tokens': 4096},
                    llm_user=user_llm,
                    llm_args_user={'temperature': 0.0},
                    max_steps=max_steps,
                    max_errors=max_errors,
                    seed=trial_seed,
                    evaluation_type=EvaluationType.ENV,  # ENV only, no LLM judge (avoids OpenAI API)
                )
                simulation.trial = trial
                simulation.seed = trial_seed
                results.simulations.append(simulation)
                logger.info(f"  Reward: {simulation.reward_info.reward:.2f}")

            except Exception as e:
                logger.error(f"  ERROR: {e}")
                # Create a failed simulation object
                start_time = get_now()
                simulation = SimulationRun(
                    id=str(uuid.uuid4()),
                    task_id=task.id,
                    start_time=start_time,
                    end_time=get_now(),
                    duration=0.0,
                    termination_reason=TerminationReason.ERROR,
                    messages=[SystemMessage(
                        role="system",
                        content=f"Simulation failed with error: {str(e)}",
                        turn_idx=0
                    )],
                    reward_info=RewardInfo(
                        reward=0.0,
                        reward_breakdown={}
                    )
                )
                simulation.trial = trial
                simulation.seed = trial_seed
                results.simulations.append(simulation)

            # Save after each task
            if save_to:
                save_path = Path(save_to)
                save_path.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path, 'w') as f:
                    f.write(results.model_dump_json(indent=2))

    # Final save
    if save_to:
        save_path = Path(save_to)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, 'w') as f:
            f.write(results.model_dump_json(indent=2))

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Round 4 Evaluation (Sequential)')
    parser.add_argument('--model', required=True, help='Model path (e.g., Qwen/Qwen2.5-7B-Instruct)')
    parser.add_argument('--domain', default='airline', help='Domain to evaluate on')
    parser.add_argument('--user-llm', default='bedrock/us.anthropic.claude-opus-4-6-v1',
                        help='User simulator LLM')
    parser.add_argument('--num-trials', type=int, default=3, help='Number of trials per task')
    parser.add_argument('--max-steps', type=int, default=200, help='Max steps per simulation')
    parser.add_argument('--save-to', required=True, help='Path to save results')
    parser.add_argument('--task-ids', nargs='+', default=None, help='Specific task IDs to run')
    parser.add_argument('--seed', type=int, default=300, help='Random seed')
    args = parser.parse_args()

    logger.info(f"Starting Round 4 evaluation")
    logger.info(f"  Model: {args.model}")
    logger.info(f"  Domain: {args.domain}")
    logger.info(f"  User LLM: {args.user_llm}")
    logger.info(f"  Num trials: {args.num_trials}")
    logger.info(f"  Save to: {args.save_to}")

    results = run_evaluation(
        domain=args.domain,
        model_path=args.model,
        user_llm=args.user_llm,
        num_trials=args.num_trials,
        max_steps=args.max_steps,
        save_to=args.save_to,
        task_ids=args.task_ids,
        seed=args.seed,
    )

    # Compute and display metrics
    metrics = compute_metrics(results)
    print("\n" + "="*50)
    print("RESULTS")
    print("="*50)
    print(f"Model: {args.model}")
    print(f"Domain: {args.domain}")
    print(f"Total simulations: {len(results.simulations)}")
    print(f"Average reward: {metrics.avg_reward:.3f}")
    print("Pass^k metrics:")
    for k, v in sorted(metrics.pass_hat_ks.items()):
        print(f"  Pass^{k}: {v:.3f}")
    print(f"Average agent cost: ${metrics.avg_agent_cost:.4f}")
    print("="*50)

    return results, metrics


if __name__ == '__main__':
    main()
