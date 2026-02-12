#!/usr/bin/env python3
"""
Telecom Seed Conversation Generator

Generates ~300-500 telecom customer service seed conversations using an LLM (via AWS Bedrock).
Uses domain definitions (tools, policy, workflow, database) from tau2-bench — NOT task definitions
(to avoid eval contamination).

Output: APIGen_telecom_seeds.json in the same format as existing airline/retail seeds.

Usage:
    python generate_telecom_seeds.py [--output OUTPUT] [--num-per-category N] [--workers W] [--region REGION] [--model MODEL]
"""

import argparse
import json
import os
import re
import sys
import time
import hashlib
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "APIGen_telecom_seeds.json"
DEFAULT_REGION = "us-east-1"
DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-20250514-v1:0"

# 13 telecom tool schemas (loaded from tools_seed.json)
TOOLS_SEED_PATH = SCRIPT_DIR / "tools_seed.json"

# Domain reference files
TAU2_TELECOM_DIR = SCRIPT_DIR.parent.parent / "tau2-bench" / "data" / "tau2" / "domains" / "telecom"
MAIN_POLICY_PATH = TAU2_TELECOM_DIR / "main_policy.md"
TECH_WORKFLOW_PATH = TAU2_TELECOM_DIR / "tech_support_workflow.md"
DB_PATH = TAU2_TELECOM_DIR / "db.toml"

# ---------------------------------------------------------------------------
# Scenario taxonomy
# ---------------------------------------------------------------------------
SCENARIO_CATEGORIES = {
    "no_service": {
        "name": "No Service / No Connection",
        "description": "Phone shows No Service or cannot connect to the network",
        "sub_problems": [
            "airplane mode accidentally enabled",
            "SIM card dislodged or missing",
            "SIM card locked with PIN/PUK",
            "APN settings corrupted",
            "line suspended due to overdue bill",
            "line suspended due to expired contract",
        ],
    },
    "data_unavailable": {
        "name": "Mobile Data Unavailable",
        "description": "Cannot access mobile internet — speed test returns no connection",
        "sub_problems": [
            "mobile data toggle turned off",
            "traveling abroad without data roaming enabled",
            "roaming not enabled on the line (carrier side)",
            "data usage exceeded plan limit",
            "no cellular service (needs Path 1 first)",
        ],
    },
    "slow_data": {
        "name": "Slow Mobile Data",
        "description": "Mobile data works but speed is below Excellent",
        "sub_problems": [
            "Data Saver mode enabled",
            "network mode set to 2G/3G instead of 5G/4G",
            "active VPN reducing speed",
            "combination of Data Saver + old network mode",
        ],
    },
    "mms_issues": {
        "name": "MMS / Picture Messaging Issues",
        "description": "Unable to send or receive picture/group messages",
        "sub_problems": [
            "network type below 3G (connected on 2G only)",
            "Wi-Fi Calling interfering with MMS",
            "messaging app missing storage or SMS permissions",
            "APN MMSC URL missing or corrupted",
            "no mobile data connectivity (needs Path 2.1 first)",
        ],
    },
    "overdue_bill": {
        "name": "Overdue Bill Payment",
        "description": "Customer has overdue bill and wants to pay",
        "sub_problems": [
            "single overdue bill — straightforward payment",
            "multiple bills, only one is overdue",
            "customer confused about bill amount",
            "customer tries to pay a bill that is not overdue",
        ],
    },
    "line_suspension": {
        "name": "Line Suspension / Resumption",
        "description": "Line suspended — customer wants to restore service",
        "sub_problems": [
            "suspended due to overdue bill — pay and resume",
            "suspended due to expired contract — cannot resume",
            "customer requests voluntary suspension",
            "resume after payment but user forgets to reboot device",
        ],
    },
    "data_refueling_roaming": {
        "name": "Data Refueling & Roaming",
        "description": "Check usage, refuel data, enable roaming for travel",
        "sub_problems": [
            "data exceeded — customer wants to refuel 1GB",
            "data exceeded — customer requests more than 2GB (must deny excess)",
            "customer traveling abroad — needs roaming enabled",
            "roaming already enabled but data still not working (carrier side issue)",
            "check data usage — usage is fine, no action needed",
        ],
    },
}

USER_PERSONAS = [
    "patient and polite customer",
    "frustrated customer who has been having issues for days",
    "confused elderly customer not familiar with technology",
    "tech-savvy customer who has already tried basic troubleshooting",
    "non-native English speaker who may describe issues imprecisely",
    "impatient customer in a hurry",
]

OUTCOMES = [
    "fully resolved",
    "partially resolved (one issue fixed, another remains)",
    "transferred to human agent",
    "customer gives up or hangs up",
]

COMPLEXITIES = [
    "single fault — one clear problem",
    "compound — two related problems (e.g., no service + overdue bill causing suspension)",
    "compound — problem plus a secondary discovery during diagnosis",
]

TURN_RANGES = [(6, 10), (10, 15), (15, 20)]

# ---------------------------------------------------------------------------
# Database examples (representative samples for prompt context)
# ---------------------------------------------------------------------------
DB_EXAMPLES = """
## Example Customer Profile:
customer_id = "C1001"
full_name = "John Smith"
date_of_birth = "1985-03-15"
email = "john.smith@example.com"
phone_number = "555-123-1001"
account_status = "Active"
line_ids = ["L1001", "L1002", "L1003"]
bill_ids = ["B1001", "B1002", "B1003"]
payment_methods: Credit Card ending 4532, exp 09/2026

## Example Line:
line_id = "L1001"
phone_number = "555-123-2001"
status = "Active"
plan_id = "P1001"
device_id = "D1001"
data_used_gb = 4.2
data_refueling_gb = 0.0
roaming_enabled = false
contract_end_date = "2026-06-30"

## Example Plans:
P1001 - Basic Plan: 5GB data, $40/month, refuel $5/GB
P1002 - Premium Plan: 20GB data, $65/month, refuel $3/GB
P1003 - Unlimited Plan: 100GB data, $85/month, refuel $2/GB
P1004 - Family Plan: 50GB shared, $120/month, refuel $4/GB

## Example Bill:
bill_id = "B1002"
customer_id = "C1001"
period = 2025-02-01 to 2025-02-28
total_due = 160.50
due_date = "2025-02-19"
status = "Overdue"

## Example Device:
device_id = "D1001"
device_type = "phone"
model = "Smartphone X"
imei = "123456789012345"
is_esim_capable = true
activated = true
"""

# ---------------------------------------------------------------------------
# Load telecom tools
# ---------------------------------------------------------------------------
def load_telecom_tools() -> List[Dict[str, Any]]:
    """Load the 13 telecom tool schemas from tools_seed.json."""
    with open(TOOLS_SEED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    config = data.get("tools_config_1", {})
    tools = config.get("tools", [])
    # Convert from OpenAI function-calling format to APIGen seed format
    seed_tools = []
    for t in tools:
        if t.get("type") == "function":
            func = t["function"]
            seed_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {}),
            })
    return seed_tools


def load_policy() -> str:
    """Load main_policy.md content."""
    return MAIN_POLICY_PATH.read_text(encoding="utf-8")


def load_workflow() -> str:
    """Load tech_support_workflow.md content."""
    return TECH_WORKFLOW_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Build generation prompt
# ---------------------------------------------------------------------------
def build_seed_generation_prompt(
    category_key: str,
    sub_problem: str,
    persona: str,
    outcome: str,
    complexity: str,
    turn_range: Tuple[int, int],
    tools_json_str: str,
    policy_text: str,
    workflow_text: str,
) -> str:
    cat = SCENARIO_CATEGORIES[category_key]
    min_turns, max_turns = turn_range

    return f"""You are generating synthetic telecom customer service conversations for agent training data.

## Task
Generate a COMPLETE multi-turn conversation between a customer (HUMAN) and a telecom customer service agent (ASSISTANT/GPT).
The agent has access to tools and must follow the telecom policy below.

## Scenario Parameters
- **Category**: {cat['name']} — {cat['description']}
- **Specific Problem**: {sub_problem}
- **Complexity**: {complexity}
- **Customer Persona**: {persona}
- **Expected Outcome**: {outcome}
- **Target Length**: {min_turns}-{max_turns} conversation turns (including tool calls and observations)

## Available Tools (13 telecom tools)
The agent can ONLY use these tools:
{tools_json_str}

## Telecom Policy
{policy_text}

## Technical Support Workflow
{workflow_text}

## Database Context (use realistic IDs following these patterns)
{DB_EXAMPLES}

## Output Format
You MUST output a valid JSON object with this exact structure:
```json
{{
  "conversations": [
    {{"from": "human", "value": "...customer message..."}},
    {{"from": "gpt", "value": "...agent message..."}},
    {{"from": "function_call", "value": "{{\\"name\\": \\"tool_name\\", \\"arguments\\": {{...}}}}"}},
    {{"from": "observation", "value": "...tool response JSON..."}},
    ...
  ]
}}
```

## Critical Rules
1. Start with a "human" turn (the customer describing their issue).
2. "gpt" turns are agent messages to the customer.
3. "function_call" turns contain a JSON object with "name" and "arguments" — the agent calling a tool.
4. "observation" turns contain the tool's JSON response (simulate realistic responses matching the tool schemas).
5. The agent MUST verify customer identity before any write operation.
6. Follow the tech support workflow paths sequentially — don't skip diagnostic steps.
7. Tool responses in "observation" turns must be realistic JSON matching the tool's return schema.
8. Use IDs following the patterns: customer_id="C####", line_id="L####", bill_id="B####", plan_id="P####", device_id="D####".
9. Generate DIVERSE, REALISTIC customer IDs, names, phone numbers — do NOT reuse the exact examples above.
10. The conversation should feel natural — the customer may be confused, provide information gradually, or ask clarifying questions.
11. Do NOT include any system/instruction turns — only human, gpt, function_call, and observation.
12. Ensure the "function_call" value is a STRINGIFIED JSON object (not a nested object).

Output ONLY the JSON object, nothing else. No markdown fences, no explanation.
"""


# ---------------------------------------------------------------------------
# Call Bedrock
# ---------------------------------------------------------------------------
def call_bedrock(client, model_id: str, prompt: str, max_tokens: int = 16000, temperature: float = 1.0) -> str:
    """Call Bedrock Converse API and return text response."""
    response = client.converse(
        modelId=model_id,
        messages=[{
            "role": "user",
            "content": [{"text": prompt}],
        }],
        inferenceConfig={
            "temperature": temperature,
            "maxTokens": max_tokens,
        },
    )
    output = response.get("output", {})
    message = output.get("message", {})
    content_blocks = message.get("content", [])
    parts = []
    for block in content_blocks:
        if "text" in block:
            parts.append(block["text"])
    return "\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Parse and validate generated conversation
# ---------------------------------------------------------------------------
VALID_TOOL_NAMES = {
    "disable_roaming", "enable_roaming", "get_bills_for_customer",
    "get_customer_by_id", "get_customer_by_name", "get_customer_by_phone",
    "get_data_usage", "get_details_by_id", "refuel_data", "resume_line",
    "send_payment_request", "suspend_line", "transfer_to_human_agents",
}

VALID_FROM_FIELDS = {"human", "gpt", "function_call", "observation"}


def extract_json_from_response(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON object from LLM response, handling markdown fences."""
    text = text.strip()
    # Remove markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        start = 1
        end = len(lines)
        for j in range(len(lines) - 1, 0, -1):
            if lines[j].strip() == "```":
                end = j
                break
        text = "\n".join(lines[start:end]).strip()

    # Find the JSON object
    start = text.find("{")
    if start == -1:
        return None
    # Find matching closing brace
    depth = 0
    for idx in range(start, len(text)):
        if text[idx] == "{":
            depth += 1
        elif text[idx] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:idx + 1])
                except json.JSONDecodeError:
                    return None
    return None


def validate_conversation(conv: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate a generated conversation. Returns (is_valid, reason)."""
    if not isinstance(conv, dict):
        return False, "not a dict"

    conversations = conv.get("conversations")
    if not isinstance(conversations, list):
        return False, "missing or invalid 'conversations' field"

    if len(conversations) < 6:
        return False, f"too few turns ({len(conversations)}, need >= 6)"

    # Check first turn is human
    if not conversations or conversations[0].get("from") != "human":
        return False, "first turn must be 'human'"

    for idx, turn in enumerate(conversations):
        if not isinstance(turn, dict):
            return False, f"turn {idx} is not a dict"
        from_field = turn.get("from")
        value = turn.get("value")
        if from_field not in VALID_FROM_FIELDS:
            return False, f"turn {idx}: invalid 'from' field '{from_field}'"
        if not isinstance(value, str) or not value.strip():
            return False, f"turn {idx}: empty or missing 'value'"

        # Validate function_call turns
        if from_field == "function_call":
            try:
                call_data = json.loads(value)
                tool_name = call_data.get("name")
                if tool_name not in VALID_TOOL_NAMES:
                    return False, f"turn {idx}: invalid tool name '{tool_name}'"
                args = call_data.get("arguments")
                if not isinstance(args, dict):
                    return False, f"turn {idx}: arguments must be a dict"
            except json.JSONDecodeError:
                return False, f"turn {idx}: function_call value is not valid JSON"

        # Validate observation follows function_call
        if from_field == "observation" and idx > 0:
            prev_from = conversations[idx - 1].get("from")
            if prev_from != "function_call":
                return False, f"turn {idx}: observation must follow function_call, got '{prev_from}'"

    return True, "ok"


def compute_fingerprint(conv: Dict[str, Any]) -> str:
    """Compute a fingerprint of the first human turn for dedup."""
    conversations = conv.get("conversations", [])
    for turn in conversations:
        if turn.get("from") == "human":
            text = turn.get("value", "").strip().lower()
            # Normalize whitespace
            text = re.sub(r'\s+', ' ', text)
            return hashlib.md5(text.encode()).hexdigest()
    return ""


# ---------------------------------------------------------------------------
# Generate one seed conversation
# ---------------------------------------------------------------------------
def generate_one_seed(
    client,
    model_id: str,
    category_key: str,
    sub_problem: str,
    persona: str,
    outcome: str,
    complexity: str,
    turn_range: Tuple[int, int],
    tools_json_str: str,
    tools_stringified: str,
    policy_text: str,
    workflow_text: str,
    system_prompt: str,
    seed_idx: int,
) -> Optional[Dict[str, Any]]:
    """Generate and validate a single seed conversation."""
    prompt = build_seed_generation_prompt(
        category_key=category_key,
        sub_problem=sub_problem,
        persona=persona,
        outcome=outcome,
        complexity=complexity,
        turn_range=turn_range,
        tools_json_str=tools_json_str,
        policy_text=policy_text,
        workflow_text=workflow_text,
    )

    for attempt in range(3):
        try:
            response_text = call_bedrock(client, model_id, prompt, max_tokens=16000, temperature=1.0)
            conv = extract_json_from_response(response_text)
            if conv is None:
                print(f"  [seed {seed_idx}] attempt {attempt+1}: failed to extract JSON")
                continue

            is_valid, reason = validate_conversation(conv)
            if not is_valid:
                print(f"  [seed {seed_idx}] attempt {attempt+1}: validation failed: {reason}")
                continue

            # Wrap in APIGen seed format
            seed = {
                "conversations": conv["conversations"],
                "tools": tools_stringified,
                "system": system_prompt,
                "category": category_key,
                "sub_problem": sub_problem,
                "persona": persona,
                "outcome": outcome,
                "complexity": complexity,
            }
            return seed

        except Exception as e:
            print(f"  [seed {seed_idx}] attempt {attempt+1}: error: {e}")
            time.sleep(2 * (attempt + 1))

    return None


# ---------------------------------------------------------------------------
# Build system prompt for seeds
# ---------------------------------------------------------------------------
def build_telecom_system_prompt(policy_text: str) -> str:
    """Build the telecom system prompt that will be stored in the 'system' field of each seed."""
    return f"""<instructions>
You are a telecom customer service agent that helps the user according to the <policy> provided below.
In each turn you can either:
- Send a message to the user.
- Make a tool call.
You cannot do both at the same time.

Try to be helpful and always follow the policy. Always make sure you generate valid JSON only.
</instructions>
<policy>
{policy_text}
</policy>"""


# ---------------------------------------------------------------------------
# Main generation loop
# ---------------------------------------------------------------------------
def generate_all_seeds(
    region: str,
    model_id: str,
    num_per_category: int,
    max_workers: int,
    output_path: Path,
):
    import boto3
    client = boto3.client("bedrock-runtime", region_name=region)

    # Load resources
    tools = load_telecom_tools()
    tools_json_str = json.dumps(tools, indent=2)
    tools_stringified = json.dumps(tools)
    policy_text = load_policy()
    workflow_text = load_workflow()
    system_prompt = build_telecom_system_prompt(policy_text)

    # Build generation tasks
    tasks = []
    seed_idx = 0
    for category_key, cat_info in SCENARIO_CATEGORIES.items():
        sub_problems = cat_info["sub_problems"]
        for _ in range(num_per_category):
            sub_problem = random.choice(sub_problems)
            persona = random.choice(USER_PERSONAS)
            outcome = random.choice(OUTCOMES)
            complexity = random.choice(COMPLEXITIES)
            turn_range = random.choice(TURN_RANGES)
            tasks.append({
                "seed_idx": seed_idx,
                "category_key": category_key,
                "sub_problem": sub_problem,
                "persona": persona,
                "outcome": outcome,
                "complexity": complexity,
                "turn_range": turn_range,
            })
            seed_idx += 1

    total = len(tasks)
    print(f"Generating {total} seed conversations ({num_per_category} per category x {len(SCENARIO_CATEGORIES)} categories)")
    print(f"Model: {model_id}, Region: {region}, Workers: {max_workers}")

    all_seeds = []
    fingerprints = set()
    failed = 0

    def worker(task_params):
        return generate_one_seed(
            client=client,
            model_id=model_id,
            tools_json_str=tools_json_str,
            tools_stringified=tools_stringified,
            policy_text=policy_text,
            workflow_text=workflow_text,
            system_prompt=system_prompt,
            **task_params,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(worker, t): t for t in tasks}
        for i, future in enumerate(as_completed(futures)):
            task_params = futures[future]
            try:
                seed = future.result()
                if seed is not None:
                    fp = compute_fingerprint(seed)
                    if fp and fp in fingerprints:
                        print(f"  [{i+1}/{total}] duplicate, skipping")
                        continue
                    if fp:
                        fingerprints.add(fp)
                    all_seeds.append(seed)
                    if (len(all_seeds) % 10) == 0:
                        print(f"  Progress: {len(all_seeds)} valid seeds / {i+1} attempted")
                else:
                    failed += 1
                    print(f"  [{i+1}/{total}] failed after retries (category={task_params['category_key']})")
            except Exception as e:
                failed += 1
                print(f"  [{i+1}/{total}] worker error: {e}")

    # Save results
    print(f"\nGeneration complete: {len(all_seeds)} valid, {failed} failed, {total} total attempted")

    # Category breakdown
    cat_counts = {}
    for s in all_seeds:
        cat = s.get("category", "unknown")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    print("Category breakdown:")
    for cat, count in sorted(cat_counts.items()):
        print(f"  {cat}: {count}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_seeds, f, ensure_ascii=False, indent=2)
    print(f"Saved to: {output_path}")

    return all_seeds


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Generate telecom seed conversations")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT), help="Output file path")
    parser.add_argument("--num-per-category", type=int, default=50, help="Seeds per scenario category (default: 50 -> ~350 total)")
    parser.add_argument("--workers", type=int, default=5, help="Parallel workers")
    parser.add_argument("--region", type=str, default=DEFAULT_REGION, help="AWS Bedrock region")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Bedrock model ID")
    parser.add_argument("--test", action="store_true", help="Test mode: generate 2 per category")
    args = parser.parse_args()

    num_per_category = 2 if args.test else args.num_per_category

    generate_all_seeds(
        region=args.region,
        model_id=args.model,
        num_per_category=num_per_category,
        max_workers=args.workers,
        output_path=Path(args.output),
    )


if __name__ == "__main__":
    main()
