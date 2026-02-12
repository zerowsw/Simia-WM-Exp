#!/usr/bin/env python3
"""
Extract representative sycophancy examples from telecom scoring data.

For each of 6 sycophancy categories, find one high-severity example,
join it with the full original conversation, and write to a JSON file.
"""

import json
import os
import re

BASE_DIR = "/Volumes/workplace/Simia-WM-Exp/Simia_SFT/Tau2"
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Scoring files (JSONL)
SCORE_FILES = {
    "base": os.path.join(OUTPUT_DIR, "sycophancy_llm_scores_v2_base_telecom_200.jsonl"),
    "strict": os.path.join(OUTPUT_DIR, "sycophancy_llm_scores_v2_strict_telecom_200.jsonl"),
    "sycophantic": os.path.join(OUTPUT_DIR, "sycophancy_llm_scores_v2_sycophantic_telecom_200.jsonl"),
}

# Data files (JSON arrays of conversations)
DATA_FILES = {
    "base": os.path.join(OUTPUT_DIR, "tau2_telecom_base_200.json"),
    "strict": os.path.join(OUTPUT_DIR, "tau2_telecom_strict_200.json"),
    "sycophantic": os.path.join(OUTPUT_DIR, "tau2_telecom_sycophantic_200.json"),
}

# Category definitions: name -> matching function over (finding, score_record)
# Each matcher returns True if the finding matches that category.

def match_missing_customer_id(finding, rec):
    """schema_forgiveness: missing_customer_id - agent omits customer_id from enable_roaming or refuel_data"""
    if finding.get("type") != "schema_forgiveness":
        return False
    why = finding["why_sycophantic"].lower()
    # Must mention missing customer_id, and specifically for enable_roaming or refuel_data
    if "customer_id" not in why:
        return False
    # Should be about missing param, not wrong param name
    if "wrong parameter" in why or "parameter name" in why:
        return False
    call = finding.get("excerpt_call", "").lower()
    if "enable_roaming" in call or "refuel_data" in call or "enable_roaming" in why or "refuel_data" in why:
        return True
    return False


def match_wrong_param_name(finding, rec):
    """schema_forgiveness: wrong_param_name - agent uses wrong parameter name like data_amount_gb"""
    if finding.get("type") != "schema_forgiveness":
        return False
    why = finding["why_sycophantic"].lower()
    # Look for wrong parameter name patterns
    wrong_names = ["data_amount_gb", "amount_gb", "refuel_amount_gb", "data_gb", "date_of_birth"]
    if any(name in why for name in wrong_names):
        return True
    if "wrong parameter name" in why or "parameter name mismatch" in why:
        return True
    return False


def match_nonexistent_tool(finding, rec):
    """schema_forgiveness: nonexistent_tool - agent calls make_payment (doesn't exist)"""
    if finding.get("type") != "schema_forgiveness":
        return False
    why = finding["why_sycophantic"].lower()
    # Must be about a nonexistent tool, and the simulator accepted it (not rejected)
    if ("non-existent" in why or "not exist" in why or "does not exist" in why
            or "not defined" in why or "not in the provided tool" in why
            or "doesn't exist" in why):
        # Exclude findings where the simulator correctly rejected
        if "correctly returned an error" in why or "proper error handling" in why or "proper constraint" in why:
            return False
        return True
    return False


def match_hidden_repair(finding, rec):
    """hidden_repair - simulator silently fixes something"""
    return finding.get("type") == "hidden_repair"


def match_policy_forgiveness(finding, rec):
    """policy_forgiveness - explicit policy violation forgiven"""
    return finding.get("type") == "policy_forgiveness"


def match_id_inconsistency(finding, rec):
    """id_inconsistency - agent guesses an ID, simulator accepts it"""
    if finding.get("type") != "id_inconsistency":
        return False
    why = finding["why_sycophantic"].lower()
    # Exclude findings where the system correctly returned an error
    if "correctly returned an error" in why or "proper error handling" in why:
        return False
    return True


CATEGORIES = [
    {
        "name": "schema_forgiveness_missing_param",
        "description": "Agent omits required customer_id from enable_roaming or refuel_data",
        "matcher": match_missing_customer_id,
    },
    {
        "name": "schema_forgiveness_wrong_param",
        "description": "Agent uses wrong parameter name (e.g., data_amount_gb instead of gb_amount)",
        "matcher": match_wrong_param_name,
    },
    {
        "name": "schema_forgiveness_nonexistent_tool",
        "description": "Agent calls nonexistent tool (e.g., make_payment) and simulator accepts it",
        "matcher": match_nonexistent_tool,
    },
    {
        "name": "hidden_repair",
        "description": "Simulator silently fixes something (e.g., bill status magically changes)",
        "matcher": match_hidden_repair,
    },
    {
        "name": "policy_forgiveness",
        "description": "Explicit policy violation forgiven (e.g., resume expired contract)",
        "matcher": match_policy_forgiveness,
    },
    {
        "name": "id_inconsistency",
        "description": "Agent guesses an ID never returned, simulator accepts it",
        "matcher": match_id_inconsistency,
    },
]


def load_scores():
    """Load all scoring JSONL files. Returns dict: mode -> list of records."""
    scores = {}
    for mode, path in SCORE_FILES.items():
        records = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        scores[mode] = records
        print(f"  Loaded {len(records)} scoring records from {os.path.basename(path)}")
    return scores


def load_data():
    """Load all conversation data files. Returns dict: mode -> list of conversations."""
    data = {}
    for mode, path in DATA_FILES.items():
        with open(path) as f:
            conversations = json.load(f)
        data[mode] = conversations
        print(f"  Loaded {len(conversations)} conversations from {os.path.basename(path)}")
    return data


def build_conv_index(data):
    """Build index: (mode, conv_idx) -> conversation object.

    The data files are lists; the scoring records reference conv_idx.
    We need to match them. The scoring record has 'conv_idx' and 'based_on_sample'.
    The data file items have 'based_on_sample'. We match on based_on_sample AND position.
    """
    index = {}
    for mode, conversations in data.items():
        # Build a lookup by based_on_sample for this mode
        by_sample = {}
        for i, conv in enumerate(conversations):
            sample_key = conv.get("based_on_sample", "")
            by_sample[sample_key] = conv
            # Also index by position
            index[(mode, i)] = conv
        # Store the by_sample lookup for this mode too
        index[f"{mode}_by_sample"] = by_sample
    return index


def find_conversation(conv_index, mode, score_rec, data_list):
    """Find the conversation matching a score record."""
    conv_idx = score_rec["conv_idx"]
    based_on = score_rec.get("based_on_sample", "")

    # First try: match by conv_idx directly
    if conv_idx < len(data_list):
        candidate = data_list[conv_idx]
        if candidate.get("based_on_sample") == based_on:
            return candidate

    # Fallback: match by based_on_sample AND simulator_mode
    for conv in data_list:
        if (conv.get("based_on_sample") == based_on
                and conv.get("simulator_mode") == score_rec.get("simulator_mode")):
            return conv

    # Last resort: match by conv_idx alone
    if conv_idx < len(data_list):
        return data_list[conv_idx]

    return None


def select_best_example(candidates):
    """From a list of (score_rec, finding, mode) tuples, select the best one.

    Prefer:
    1. wm_sycophancy_score >= 60
    2. severity == 'high'
    3. Highest score
    4. Clear why_sycophantic text (longer = more detailed)
    """
    # Separate high-score candidates
    high_score = [c for c in candidates if c[0]["wm_sycophancy_score"] >= 60]

    pool = high_score if high_score else candidates

    # Sort by: severity rank (high > medium > low), then score desc, then text length desc
    severity_rank = {"high": 3, "medium": 2, "low": 1}

    def sort_key(c):
        rec, finding, mode = c
        sev = severity_rank.get(finding.get("severity", "low"), 0)
        score = rec["wm_sycophancy_score"]
        text_len = len(finding.get("why_sycophantic", ""))
        return (sev, score, text_len)

    pool.sort(key=sort_key, reverse=True)
    return pool[0]


def main():
    print("Loading scoring files...")
    scores = load_scores()

    print("\nLoading data files...")
    data = load_data()

    print("\nSearching for representative examples...")
    results = []

    for cat in CATEGORIES:
        cat_name = cat["name"]
        matcher = cat["matcher"]
        print(f"\n--- Category: {cat_name} ---")
        print(f"    {cat['description']}")

        # Collect all matching (score_rec, finding, mode) tuples
        candidates = []
        for mode, records in scores.items():
            for rec in records:
                for finding in rec.get("findings", []):
                    if matcher(finding, rec):
                        candidates.append((rec, finding, mode))

        print(f"    Found {len(candidates)} matching findings across all modes")

        if not candidates:
            print(f"    WARNING: No examples found for {cat_name}!")
            continue

        # Select best example
        best_rec, best_finding, best_mode = select_best_example(candidates)
        conv_idx = best_rec["conv_idx"]
        score = best_rec["wm_sycophancy_score"]
        severity = best_finding.get("severity", "unknown")

        print(f"    Selected: mode={best_mode}, conv_idx={conv_idx}, "
              f"score={score}, severity={severity}")
        print(f"    Finding: {best_finding['why_sycophantic'][:150]}...")

        # Retrieve the full conversation
        conv = find_conversation(None, best_mode, best_rec, data[best_mode])
        if conv is None:
            print(f"    ERROR: Could not find matching conversation!")
            continue

        # Build the output record
        result = {
            "category": cat_name,
            "mode": best_mode,
            "conv_idx": conv_idx,
            "wm_sycophancy_score": score,
            "finding": best_finding,
            "evaluator_rationale": best_rec.get("rationale", ""),
            "conversation": {
                "system": conv.get("system", ""),
                "tools": conv.get("tools", ""),
                "conversations": conv.get("conversations", []),
            },
        }
        results.append(result)
        num_turns = len(conv.get("conversations", []))
        print(f"    Conversation has {num_turns} turns")

    # Write output
    output_path = os.path.join(OUTPUT_DIR, "sycophancy_samples_telecom.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n{'='*60}")
    print(f"Wrote {len(results)} examples to {output_path}")
    print(f"File size: {os.path.getsize(output_path):,} bytes")

    # Print summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for r in results:
        print(f"\n  Category: {r['category']}")
        print(f"  Mode: {r['mode']}")
        print(f"  Conv index: {r['conv_idx']}")
        print(f"  WM Sycophancy Score: {r['wm_sycophancy_score']}")
        print(f"  Severity: {r['finding'].get('severity', 'N/A')}")
        print(f"  Finding type: {r['finding'].get('type', 'N/A')}")
        print(f"  Why: {r['finding']['why_sycophantic'][:200]}")
        print(f"  Conversation turns: {len(r['conversation']['conversations'])}")


if __name__ == "__main__":
    main()
