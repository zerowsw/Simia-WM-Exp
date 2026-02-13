#!/usr/bin/env python3
"""
Merge consecutive same-role turns in ShareGPT format data.

LLaMA Factory's ShareGPT converter requires strictly alternating roles
(human/observation at odd positions, gpt/function_call at even positions).
The telecom data has consecutive gpt turns (text message followed by tool call),
which breaks this requirement. This script merges them into single turns.

Usage:
    python merge_consecutive_turns.py --input data.json --output data_merged.json
"""

import argparse
import json


def merge_consecutive_turns(conversations):
    """Merge consecutive same-role turns by concatenating their values."""
    if not conversations:
        return conversations

    merged = [conversations[0].copy()]
    for turn in conversations[1:]:
        if turn["from"] == merged[-1]["from"]:
            merged[-1]["value"] += "\n" + turn["value"]
        else:
            merged.append(turn.copy())
    return merged


def main():
    parser = argparse.ArgumentParser(
        description="Merge consecutive same-role turns in ShareGPT data"
    )
    parser.add_argument("--input", required=True, help="Input JSON file")
    parser.add_argument("--output", required=True, help="Output JSON file")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    total_before = 0
    total_after = 0
    merged_count = 0
    trimmed_count = 0

    for item in data:
        convs = item["conversations"]
        total_before += len(convs)
        merged = merge_consecutive_turns(convs)
        if len(merged) != len(convs):
            merged_count += 1
        # LLaMA Factory requires even turn count (ending with gpt).
        # Drop trailing human turn if present.
        if len(merged) % 2 != 0 and merged[-1]["from"] == "human":
            merged = merged[:-1]
            trimmed_count += 1
        total_after += len(merged)
        item["conversations"] = merged

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Processed {len(data)} conversations")
    print(f"Merged consecutive turns in {merged_count} conversations")
    print(f"Trimmed trailing human turn in {trimmed_count} conversations")
    print(f"Total turns: {total_before} -> {total_after} ({total_before - total_after} removed)")
    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
