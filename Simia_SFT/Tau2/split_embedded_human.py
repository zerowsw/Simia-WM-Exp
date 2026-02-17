#!/usr/bin/env python3
"""
Fix conversation role issues in generated telecom data.

Two problems addressed:
1. Embedded HUMAN: text in gpt turns — the conversation generator (Claude Sonnet)
   sometimes produces gpt turns like:
     "I'll need your phone number.HUMAN: Sure, it's 555-123-9876."
   These are split into separate gpt + human turns.

2. Tool calls in gpt role with FUNCTION_CALL: prefix — some tool calls are generated
   as gpt turns instead of function_call turns:
     gpt: "FUNCTION_CALL: {"name": "get_customer_by_phone", ...}"
   These are converted to function_call role so tool2hermes.py can process them
   into proper <tool_call> hermes format.

This MUST be run BEFORE tool2hermes.py to ensure proper role separation.

Usage:
    python split_embedded_human.py --input data.json --output data_split.json
"""

import argparse
import json
import re
from typing import List, Dict, Any


def convert_gpt_function_call(turn: Dict[str, str]) -> Dict[str, str]:
    """Convert a gpt turn with FUNCTION_CALL: prefix to function_call role.

    Strips the FUNCTION_CALL: prefix and extracts the JSON (with optional <think> tags),
    so tool2hermes.py can then convert it to hermes format.
    """
    value = turn["value"].strip()

    # Match: FUNCTION_CALL: [optional <think>...</think>] {JSON}
    match = re.match(
        r"FUNCTION_CALL:\s*"
        r"((?:<think>.*?</think>\s*)?)"   # optional think block
        r"(\{.*\})",                       # JSON object
        value,
        re.DOTALL,
    )
    if not match:
        return turn

    think_part = match.group(1).strip()
    json_part = match.group(2).strip()

    # Validate JSON
    try:
        json.loads(json_part)
    except json.JSONDecodeError:
        return turn  # leave as-is if JSON is invalid

    new_value = f"{think_part}\n{json_part}" if think_part else json_part
    return {"from": "function_call", "value": new_value.strip()}


def split_gpt_turn(turn: Dict[str, str]) -> List[Dict[str, str]]:
    """Split a gpt turn containing HUMAN: into separate gpt + human turns.

    Returns a list of 1 or 2 turns. If no HUMAN: found, returns the original turn.
    If HUMAN: found, returns [gpt_part, human_part] (either may be omitted if empty).
    """
    if turn["from"] != "gpt":
        return [turn]

    value = turn["value"]
    if "HUMAN:" not in value:
        return [turn]

    # Split on first occurrence of HUMAN:
    # The HUMAN: marker is typically directly appended (no newline separator)
    idx = value.index("HUMAN:")
    gpt_text = value[:idx].rstrip()
    human_text = value[idx + len("HUMAN:"):].strip()

    result = []
    if gpt_text:
        result.append({"from": "gpt", "value": gpt_text})
    if human_text:
        result.append({"from": "human", "value": human_text})

    # If both parts are empty (shouldn't happen), return original
    if not result:
        return [turn]

    return result


def process_conversation(conversations: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Process a single conversation: split HUMAN: text, fix FUNCTION_CALL roles."""
    result = []
    for turn in conversations:
        # First split any embedded HUMAN: text
        split_turns = split_gpt_turn(turn)
        # Then convert any FUNCTION_CALL: gpt turns to function_call role
        for t in split_turns:
            if t["from"] == "gpt" and t["value"].strip().startswith("FUNCTION_CALL:"):
                result.append(convert_gpt_function_call(t))
            else:
                result.append(t)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Split gpt turns with embedded HUMAN: text into separate turns"
    )
    parser.add_argument("--input", "-i", required=True, help="Input JSON file")
    parser.add_argument("--output", "-o", required=True, help="Output JSON file")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_splits = 0
    convs_modified = 0
    turns_before = 0
    turns_after = 0

    for item in data:
        convs = item["conversations"]
        turns_before += len(convs)
        processed = process_conversation(convs)
        turns_after += len(processed)

        if len(processed) != len(convs):
            convs_modified += 1
            total_splits += len(processed) - len(convs)

        item["conversations"] = processed

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Count FUNCTION_CALL conversions
    fc_converted = sum(
        1
        for item in data
        for t in item["conversations"]
        if t["from"] == "function_call"
    ) - sum(
        1
        for item in json.load(open(args.input))
        for t in item["conversations"]
        if t["from"] == "function_call"
    )

    print(f"Processed {len(data)} conversations")
    print(f"Modified {convs_modified} conversations ({convs_modified/len(data)*100:.1f}%)")
    print(f"Split {total_splits} embedded HUMAN: turns")
    print(f"Converted {fc_converted} FUNCTION_CALL: gpt turns to function_call role")
    print(f"Total turns: {turns_before} -> {turns_after}")
    print(f"Output: {args.output}")

    # Verify
    remaining_human = sum(
        1
        for item in data
        for t in item["conversations"]
        if t["from"] == "gpt" and "HUMAN:" in t["value"]
    )
    remaining_fc = sum(
        1
        for item in data
        for t in item["conversations"]
        if t["from"] == "gpt" and t["value"].strip().startswith("FUNCTION_CALL:")
    )
    print(f"Remaining gpt turns with HUMAN:: {remaining_human}")
    print(f"Remaining gpt turns with FUNCTION_CALL:: {remaining_fc}")


if __name__ == "__main__":
    main()
