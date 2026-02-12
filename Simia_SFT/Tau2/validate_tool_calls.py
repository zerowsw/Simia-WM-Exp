#!/usr/bin/env python3
"""
Validate tool call quality in APIGen seed data (airline + retail).
For each function_call turn, checks:
  1. Is the tool name known (present in the tools schema)?
  2. Are all required parameters present?
  3. Are there extra parameters not defined in the schema?

Also checks the hardcase subset separately for comparison.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BASE_DIR = Path("/Volumes/workplace/Simia-WM-Exp/Simia_SFT/Tau2")


def build_tool_registry(tools_json_str):
    """Parse tools JSON string and build a lookup: name -> {properties, required}."""
    tools = json.loads(tools_json_str) if isinstance(tools_json_str, str) else tools_json_str
    registry = {}
    for tool in tools:
        name = tool["name"]
        params = tool.get("parameters", {})
        properties = set(params.get("properties", {}).keys())
        required = set(params.get("required", []))
        registry[name] = {
            "properties": properties,
            "required": required,
        }
    return registry


def validate_function_calls(data, label="dataset"):
    """Validate all function_call turns in a dataset. Return detailed results."""
    total_conversations = len(data)
    total_fc = 0
    violations = []
    violation_counter = Counter()
    conversations_with_violations = 0

    # Per-domain tracking
    domain_stats = defaultdict(lambda: {"total_fc": 0, "violations": 0})

    for conv_idx, item in enumerate(data):
        tools_str = item["tools"]
        registry = build_tool_registry(tools_str)

        # Determine domain by checking tool names
        tool_names = set(registry.keys())
        if "book_reservation" in tool_names:
            domain = "airline"
        elif "cancel_pending_order" in tool_names:
            domain = "retail"
        else:
            domain = "unknown"

        conv_has_violation = False

        for turn in item["conversations"]:
            role = turn.get("from", turn.get("role", ""))
            if role != "function_call":
                continue

            total_fc += 1
            domain_stats[domain]["total_fc"] += 1

            content = turn.get("value", turn.get("content", ""))
            try:
                fc = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError:
                violations.append({
                    "conv_idx": conv_idx,
                    "domain": domain,
                    "type": "invalid_json",
                    "detail": f"Cannot parse function_call content: {content[:100]}",
                })
                violation_counter["invalid_json"] += 1
                conv_has_violation = True
                domain_stats[domain]["violations"] += 1
                continue

            fc_name = fc.get("name", "")
            fc_args = fc.get("arguments", {})

            # Check 1: Unknown tool name
            if fc_name not in registry:
                violations.append({
                    "conv_idx": conv_idx,
                    "domain": domain,
                    "type": "unknown_tool",
                    "detail": f"Tool '{fc_name}' not in schema. Available: {sorted(registry.keys())}",
                })
                violation_counter["unknown_tool"] += 1
                conv_has_violation = True
                domain_stats[domain]["violations"] += 1
                continue  # Can't check params if tool is unknown

            tool_schema = registry[fc_name]
            schema_props = tool_schema["properties"]
            required_props = tool_schema["required"]
            provided_args = set(fc_args.keys()) if isinstance(fc_args, dict) else set()

            # Check 2: Missing required parameters
            missing = required_props - provided_args
            if missing:
                violations.append({
                    "conv_idx": conv_idx,
                    "domain": domain,
                    "type": "missing_required",
                    "detail": f"Tool '{fc_name}' missing required params: {sorted(missing)}",
                    "tool": fc_name,
                    "missing_params": sorted(missing),
                })
                violation_counter["missing_required"] += 1
                for p in missing:
                    violation_counter[f"missing_required:{fc_name}.{p}"] += 1
                conv_has_violation = True
                domain_stats[domain]["violations"] += 1

            # Check 3: Extra parameters not in schema
            extra = provided_args - schema_props
            if extra:
                violations.append({
                    "conv_idx": conv_idx,
                    "domain": domain,
                    "type": "extra_params",
                    "detail": f"Tool '{fc_name}' has extra params: {sorted(extra)}",
                    "tool": fc_name,
                    "extra_params": sorted(extra),
                })
                violation_counter["extra_params"] += 1
                for p in extra:
                    violation_counter[f"extra_params:{fc_name}.{p}"] += 1
                conv_has_violation = True
                domain_stats[domain]["violations"] += 1

        if conv_has_violation:
            conversations_with_violations += 1

    # ---- Print report ----
    print(f"\n{'='*70}")
    print(f"  TOOL CALL VALIDATION: {label}")
    print(f"{'='*70}")
    print(f"  Total conversations:          {total_conversations}")
    print(f"  Total function_call turns:    {total_fc}")
    print(f"  Total violations:             {len(violations)}")
    fc_with_violations = len(violations)
    pct = (fc_with_violations / total_fc * 100) if total_fc > 0 else 0
    print(f"  Function calls with issues:   {fc_with_violations} ({pct:.1f}% of all function_calls)")
    conv_pct = (conversations_with_violations / total_conversations * 100) if total_conversations > 0 else 0
    print(f"  Conversations with issues:    {conversations_with_violations} ({conv_pct:.1f}% of conversations)")

    print(f"\n  --- By violation type ---")
    for vtype in ["unknown_tool", "missing_required", "extra_params", "invalid_json"]:
        cnt = violation_counter[vtype]
        vpct = (cnt / total_fc * 100) if total_fc > 0 else 0
        print(f"    {vtype:25s}: {cnt:5d} ({vpct:.1f}%)")

    print(f"\n  --- By domain ---")
    for domain in sorted(domain_stats.keys()):
        ds = domain_stats[domain]
        dpct = (ds["violations"] / ds["total_fc"] * 100) if ds["total_fc"] > 0 else 0
        print(f"    {domain:10s}: {ds['total_fc']:5d} function_calls, {ds['violations']:5d} violations ({dpct:.1f}%)")

    # Most common specific violations
    specific = {k: v for k, v in violation_counter.items() if ":" in k}
    if specific:
        print(f"\n  --- Top 15 specific violations ---")
        for k, v in sorted(specific.items(), key=lambda x: -x[1])[:15]:
            print(f"    {k:50s}: {v:5d}")

    # Print some example violations
    if violations:
        print(f"\n  --- Example violations (first 10) ---")
        for v in violations[:10]:
            print(f"    [conv {v['conv_idx']:4d}] [{v['domain']:8s}] {v['type']:20s} | {v['detail'][:100]}")

    print(f"{'='*70}\n")
    return {
        "total_fc": total_fc,
        "violations": violations,
        "violation_counter": violation_counter,
        "domain_stats": domain_stats,
    }


def main():
    # --- 1. Main 5k preprocessed dataset (airline + retail) ---
    main_file = BASE_DIR / "APIGen_5k_preprocessed.json"
    print(f"Loading {main_file} ...")
    with open(main_file) as f:
        main_data = json.load(f)
    main_results = validate_function_calls(main_data, label="APIGen_5k_preprocessed (airline+retail)")

    # --- 2. Hardcase subset ---
    hardcase_file = BASE_DIR / "APIGen_hardcase_samples.json"
    print(f"Loading {hardcase_file} ...")
    with open(hardcase_file) as f:
        hardcase_data = json.load(f)
    hardcase_results = validate_function_calls(hardcase_data, label="APIGen_hardcase_samples")

    # --- 3. Telecom seeds for comparison ---
    telecom_file = BASE_DIR / "APIGen_telecom_seeds.json"
    if telecom_file.exists():
        print(f"Loading {telecom_file} ...")
        with open(telecom_file) as f:
            telecom_data = json.load(f)
        telecom_results = validate_function_calls(telecom_data, label="APIGen_telecom_seeds (telecom)")
    else:
        print(f"(Telecom file not found at {telecom_file}, skipping)")
        telecom_results = None

    # --- Summary comparison ---
    print(f"\n{'='*70}")
    print(f"  CROSS-DATASET COMPARISON")
    print(f"{'='*70}")
    datasets = [
        ("airline+retail (5k)", main_results),
        ("hardcase subset", hardcase_results),
    ]
    if telecom_results is not None:
        datasets.append(("telecom seeds", telecom_results))

    print(f"  {'Dataset':30s} | {'FC calls':>10s} | {'Violations':>12s} | {'Rate':>8s}")
    print(f"  {'-'*30}-+-{'-'*10}-+-{'-'*12}-+-{'-'*8}")
    for name, res in datasets:
        total = res["total_fc"]
        viols = len(res["violations"])
        rate = (viols / total * 100) if total > 0 else 0
        print(f"  {name:30s} | {total:10d} | {viols:12d} | {rate:7.1f}%")
    print()


if __name__ == "__main__":
    main()
