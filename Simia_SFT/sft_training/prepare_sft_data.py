#!/usr/bin/env python3
"""
Prepare processed SFT data for LLaMA Factory training.

Takes the output of process_data_pipeline.sh (ShareGPT format JSON) and:
1. Validates the data format
2. Prints dataset statistics
3. Writes dataset_info.json for LLaMA Factory
"""

import argparse
import json
import os
import sys


def validate_data(data):
    """Validate ShareGPT format data for LLaMA Factory compatibility.

    Returns:
        tuple: (valid_count, errors_list)
    """
    # LLaMA Factory ShareGPT supports these roles natively:
    #   human, gpt (standard), function_call, observation (tool calling)
    valid_roles = {"human", "gpt", "function_call", "observation"}
    errors = []
    valid = 0

    for i, item in enumerate(data):
        if "conversations" not in item:
            errors.append(f"Item {i}: missing 'conversations' field")
            continue
        if "system" not in item:
            errors.append(f"Item {i}: missing 'system' field")
            continue

        convs = item["conversations"]
        if not isinstance(convs, list) or len(convs) == 0:
            errors.append(f"Item {i}: 'conversations' must be a non-empty list")
            continue

        if convs[0].get("from") != "human":
            errors.append(f"Item {i}: first turn must be from 'human', got '{convs[0].get('from')}'")
            continue

        bad = False
        for j, turn in enumerate(convs):
            role = turn.get("from")
            if role not in valid_roles:
                errors.append(f"Item {i} turn {j}: invalid role '{role}' (expected one of {valid_roles})")
                bad = True
                break
            if not turn.get("value", "").strip():
                errors.append(f"Item {i} turn {j}: empty value")
                bad = True
                break

        if not bad:
            valid += 1

    return valid, errors


def print_statistics(data):
    """Print dataset statistics."""
    total = len(data)
    conv_lengths = []
    domains = {}

    for item in data:
        convs = item.get("conversations", [])
        conv_lengths.append(len(convs))
        domain = item.get("domain", "unknown")
        domains[domain] = domains.get(domain, 0) + 1

    if conv_lengths:
        avg_len = sum(conv_lengths) / len(conv_lengths)
        min_len = min(conv_lengths)
        max_len = max(conv_lengths)
    else:
        avg_len = min_len = max_len = 0

    print(f"\n{'='*50}")
    print(f"Dataset Statistics")
    print(f"{'='*50}")
    print(f"Total samples:          {total}")
    print(f"Avg conversation turns: {avg_len:.1f}")
    print(f"Min conversation turns: {min_len}")
    print(f"Max conversation turns: {max_len}")

    if domains:
        print(f"\nDomain distribution:")
        for domain, count in sorted(domains.items(), key=lambda x: -x[1]):
            print(f"  {domain}: {count} ({100*count/total:.1f}%)")

    # Estimate token lengths (rough: 4 chars per token)
    total_chars = []
    for item in data:
        chars = sum(len(t.get("value", "")) for t in item.get("conversations", []))
        chars += len(item.get("system", ""))
        total_chars.append(chars)

    if total_chars:
        avg_chars = sum(total_chars) / len(total_chars)
        max_chars = max(total_chars)
        print(f"\nEstimated token lengths (approx):")
        print(f"  Avg: ~{int(avg_chars/4)} tokens")
        print(f"  Max: ~{int(max_chars/4)} tokens")
        if max_chars / 4 > 12000:
            print(f"  WARNING: Some samples may exceed cutoff_len=12000. Consider increasing it.")

    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Prepare processed SFT data for LLaMA Factory training"
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to processed JSON file (output of process_data_pipeline.sh)"
    )
    parser.add_argument(
        "--dataset-name", default="tau2_sft",
        help="Dataset name for LLaMA Factory (default: tau2_sft)"
    )
    parser.add_argument(
        "--output-dir", default=".",
        help="Directory to write dataset_info.json (default: current directory)"
    )
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)
    output_dir = os.path.abspath(args.output_dir)

    if not os.path.isfile(input_path):
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Load data
    print(f"Loading data from: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("Error: Expected a JSON array at top level", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(data)} samples")

    # Validate
    valid_count, errors = validate_data(data)
    print(f"Validation: {valid_count}/{len(data)} samples valid")

    if errors:
        print(f"\nValidation errors ({len(errors)}):")
        for err in errors[:20]:
            print(f"  - {err}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more errors")

    if valid_count == 0:
        print("Error: No valid samples found. Aborting.", file=sys.stderr)
        sys.exit(1)

    # Print statistics
    print_statistics(data)

    # Write dataset_info.json
    os.makedirs(output_dir, exist_ok=True)
    dataset_info = {
        args.dataset_name: {
            "file_name": input_path,
            "formatting": "sharegpt",
            "columns": {
                "messages": "conversations",
                "system": "system"
            }
        }
    }

    output_path = os.path.join(output_dir, "dataset_info.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dataset_info, f, indent=2, ensure_ascii=False)

    print(f"Written dataset_info.json to: {output_path}")
    print(f"Dataset name: {args.dataset_name}")
    print(f"Ready for LLaMA Factory training.")


if __name__ == "__main__":
    main()
