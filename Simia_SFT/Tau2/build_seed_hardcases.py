#!/usr/bin/env python3
"""
Build an expanded "hardcase" seed subset from the full APIGen/Tau2 seed dataset.

Motivation
----------
Our earlier seed subset (APIGen_error_samples.json) was selected by the presence of
error-like observations. That increases error density, but can still miss many
*semantic* edge cases where:
  - policy forbids an action (e.g., basic economy cannot change flights),
  - or the user requests an out-of-scope/cross-user action,
  - or the agent makes a tool-call mistake (schema invalid / wrong tool).

This script scores each seed conversation by a set of heuristics and selects the top-N.
It also writes per-item tags and scores for traceability.

Output schema
-------------
Each selected item keeps the original fields (conversations/tools/system/...) and adds:
  - source_index: index in the original dataset
  - hardcase_score: integer score
  - hardcase_tags: list[str] indicating why it was selected

Usage
-----
  python3 build_seed_hardcases.py --input APIGen_5k_preprocessed.json --output APIGen_hardcase_samples.json --max 2000
  python3 build_seed_hardcases.py --input APIGen_5k_preprocessed.json --output APIGen_hardcase_samples.json --min-score 3
"""

from __future__ import annotations

import argparse
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ERROR_KEYWORDS = [
    "error",
    "invalid",
    "missing",
    "required",
    "not found",
    "unauthorized",
    "forbidden",
    "exception",
    "refused",
    "cannot",
    "unable",
    "denied",
    "fail",
    "failed",
]

CROSS_USER_PHRASES = [
    "someone else",
    "other user",
    "my friend",
    "friend of mine",
    "my brother",
    "my sister",
    "my wife",
    "my husband",
    "for my friend",
    "for my brother",
    "for my sister",
]


def _safe_json_loads(s: str) -> Optional[Any]:
    try:
        return json.loads(s)
    except Exception:
        return None


def extract_json_object(s: str) -> Optional[Dict[str, Any]]:
    """Extract a JSON object from a string that may include <think> blocks."""
    s = (s or "").strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = s[start : end + 1]
    obj = _safe_json_loads(candidate)
    if isinstance(obj, dict):
        return obj
    m = re.search(r"(\{.*\})", s, flags=re.DOTALL)
    if not m:
        return None
    obj2 = _safe_json_loads(m.group(1))
    return obj2 if isinstance(obj2, dict) else None


def load_tools(tools_field: Any) -> Dict[str, Dict[str, Any]]:
    """Return mapping tool_name -> tool_spec."""
    tools_list: List[Dict[str, Any]] = []
    if isinstance(tools_field, str):
        parsed = _safe_json_loads(tools_field)
        if isinstance(parsed, list):
            tools_list = [t for t in parsed if isinstance(t, dict)]
    elif isinstance(tools_field, list):
        tools_list = [t for t in tools_field if isinstance(t, dict)]
    out: Dict[str, Dict[str, Any]] = {}
    for t in tools_list:
        name = t.get("name")
        if isinstance(name, str) and name:
            out[name] = t
    return out


def is_error_like(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in ERROR_KEYWORDS)


def extract_declared_tool_name_from_think(text: str) -> Optional[str]:
    # only capture tool-like tokens
    m = re.search(r"I will call the function\s+([a-zA-Z][a-zA-Z0-9_]{2,})\b", text or "")
    return m.group(1) if m else None


def _type_ok(expected: str, val: Any) -> bool:
    if expected == "string":
        return isinstance(val, str)
    if expected == "number":
        return isinstance(val, (int, float)) and not isinstance(val, bool)
    if expected == "integer":
        return isinstance(val, int) and not isinstance(val, bool)
    if expected == "boolean":
        return isinstance(val, bool)
    if expected == "array":
        return isinstance(val, list)
    if expected == "object":
        return isinstance(val, dict)
    return True


def validate_tool_call_schema(
    call: Dict[str, Any],
    tools: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Return schema problems for call. Empty list means valid."""
    problems: List[str] = []
    name = call.get("name")
    args = call.get("arguments")
    if not isinstance(name, str) or not name:
        return ["missing tool name"]
    if name not in tools:
        return [f"unknown tool: {name}"]
    spec = tools[name].get("parameters") or {}
    required = spec.get("required") or []
    properties = spec.get("properties") or {}
    if not isinstance(args, dict):
        problems.append("arguments is not an object")
        args = {}
    if isinstance(required, list):
        for r in required:
            if r not in args:
                problems.append(f"missing required arg: {r}")
    for k, v in args.items():
        prop = properties.get(k)
        if isinstance(prop, dict) and isinstance(prop.get("type"), str):
            expected = prop["type"]
            if not _type_ok(expected, v):
                problems.append(
                    f"type mismatch for {k}: expected {expected}, got {type(v).__name__}"
                )
    return problems


def find_extra_arg_keys(call: Dict[str, Any], tools: Dict[str, Dict[str, Any]]) -> List[str]:
    name = call.get("name")
    args = call.get("arguments")
    if not isinstance(name, str) or name not in tools or not isinstance(args, dict):
        return []
    props = (tools[name].get("parameters") or {}).get("properties") or {}
    if not isinstance(props, dict):
        return []
    return [k for k in args.keys() if k not in props]


def _concat_turn_text(turns: List[Dict[str, Any]], include_observations: bool = True) -> str:
    parts: List[str] = []
    for t in turns:
        frm = str(t.get("from", ""))
        if not include_observations and frm == "observation":
            continue
        parts.append(f"{frm}: {t.get('value','')}")
    return "\n".join(parts)


def _policy_has(system_text: str, needle: str) -> bool:
    return needle.lower() in (system_text or "").lower()


def _text_has_any(text: str, needles: List[str]) -> bool:
    low = (text or "").lower()
    return any(n.lower() in low for n in needles)


def extract_airline_reservation_cabin(turns: List[Dict[str, Any]]) -> Optional[str]:
    """Best-effort: cabin from get_reservation_details observation JSON."""
    for i, t in enumerate(turns):
        if t.get("from") != "function_call":
            continue
        call = extract_json_object(str(t.get("value", "")))
        if not call or call.get("name") != "get_reservation_details":
            continue
        if i + 1 < len(turns) and turns[i + 1].get("from") == "observation":
            obs = str(turns[i + 1].get("value", ""))
            obj = extract_json_object(obs) or _safe_json_loads(obs)
            if isinstance(obj, dict) and isinstance(obj.get("cabin"), str):
                return obj["cabin"]
    return None


def score_seed_item(item: Dict[str, Any]) -> Tuple[int, List[str]]:
    """
    Score a seed conversation. Higher score = more error-prone / constraint-heavy.
    Returns (score, tags).
    """
    score = 0
    tags: List[str] = []

    system = item.get("system") if isinstance(item.get("system"), str) else ""
    turns = item.get("conversations") if isinstance(item.get("conversations"), list) else []
    tools = load_tools(item.get("tools"))

    full_text = (system or "") + "\n" + _concat_turn_text(turns, include_observations=True)
    non_obs_text = (system or "") + "\n" + _concat_turn_text(turns, include_observations=False)

    # 1) Existing error-like observation tokens (strong signal)
    # We count once per conversation, not per token.
    has_error = False
    for t in turns:
        if t.get("from") == "observation" and is_error_like(str(t.get("value", ""))):
            has_error = True
            break
    if has_error:
        score += 3
        tags.append("has_error_like_observation")

    # 2) Tool-call schema issues (missing required args / unknown tool / type mismatch)
    schema_invalid_calls = 0
    extra_keys_calls = 0
    declared_mismatch = 0
    for t in turns:
        if t.get("from") != "function_call":
            continue
        raw = str(t.get("value", ""))
        call = extract_json_object(raw)
        if not isinstance(call, dict):
            continue

        probs = validate_tool_call_schema(call, tools)
        if probs:
            schema_invalid_calls += 1

        extra = find_extra_arg_keys(call, tools)
        if extra:
            extra_keys_calls += 1

        declared = extract_declared_tool_name_from_think(raw)
        actual = call.get("name")
        if declared and (not isinstance(actual, str) or declared != actual or declared not in tools):
            declared_mismatch += 1

    if schema_invalid_calls:
        score += 2 + min(3, schema_invalid_calls)  # cap contribution
        tags.append(f"schema_invalid_calls={schema_invalid_calls}")
    if extra_keys_calls:
        score += 1 + min(2, extra_keys_calls)
        tags.append(f"extra_arg_keys_calls={extra_keys_calls}")
    if declared_mismatch:
        score += 2
        tags.append(f"declared_tool_mismatch_calls={declared_mismatch}")

    # 3) Cross-user requests (semantic hardcase)
    if _text_has_any(non_obs_text, CROSS_USER_PHRASES):
        score += 2
        tags.append("cross_user_phrase")

    # 4) Airline policy hardcases: basic economy change, add insurance after booking, cancel after flown/landed.
    if _policy_has(system, "# Airline Agent Policy") or _policy_has(system, "There are three cabin classes"):
        cabin = extract_airline_reservation_cabin(turns)
        if isinstance(cabin, str) and "basic" in cabin.lower():
            # any request to change flights in text makes it a hardcase
            if re.search(r"\b(change|modify|update)\b.*\b(flight|reservation)\b", non_obs_text, flags=re.I):
                score += 3
                tags.append("airline_basic_economy_change_request_or_context")

        # Explicit policy clause exists in most airline prompts; trigger when user asks forbidden action.
        if _policy_has(system, "Basic economy flights cannot be modified") and "basic economy" in non_obs_text.lower():
            if re.search(r"\b(change|modify|update)\b.*\b(flight|reservation)\b", non_obs_text, flags=re.I):
                score += 3
                tags.append("airline_policy_basic_economy_no_modify_trigger")

        if _policy_has(system, "cannot add insurance after initial booking"):
            if re.search(r"\b(add|purchase|buy)\b.*\b(insurance|travel insurance)\b", non_obs_text, flags=re.I):
                score += 2
                tags.append("airline_policy_no_add_insurance_trigger")

        if _policy_has(system, "If any portion of the flight has already been flown"):
            if re.search(r"\b(already|has)\b.*\b(flown|landed|departed|took off)\b", non_obs_text, flags=re.I):
                score += 3
                tags.append("airline_cancel_after_flown_phrase")

    # 5) Retail policy hardcases: cancel delivered, refund to disallowed method, etc. (lightweight)
    if _policy_has(system, "# Retail agent policy"):
        if re.search(r"\bcancel\b.*\border\b", non_obs_text, flags=re.I) and re.search(
            r"status\\s*[:=]\\s*\"delivered\"|status\\s+is\\s+delivered|already\\s+delivered",
            full_text,
            flags=re.I,
        ):
            score += 2
            tags.append("retail_cancel_delivered_phrase_or_status")

        if _text_has_any(non_obs_text, ["refund to a different card", "refund to a new card", "refund to another card"]):
            score += 1
            tags.append("retail_refund_to_new_payment_request")

    return score, tags


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=str,
        default="APIGen_5k_preprocessed.json",
        help="Path to full seed dataset JSON.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="APIGen_hardcase_samples.json",
        help="Output path for selected hardcase seeds.",
    )
    parser.add_argument("--max", type=int, default=2000, help="Max number of seeds to output.")
    parser.add_argument("--min-score", type=int, default=0, help="Only include seeds with score >= this.")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for tie-breaking.")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    data = json.loads(in_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected list JSON in {in_path}, got {type(data).__name__}")

    scored: List[Tuple[int, int, List[str]]] = []  # (score, index, tags)
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        s, tags = score_seed_item(item)
        if s >= args.min_score:
            scored.append((s, idx, tags))

    # sort by score desc, then stable by index, but randomize within equal score for diversity
    rng = random.Random(args.seed)
    by_score: Dict[int, List[Tuple[int, List[str]]]] = {}
    for s, idx, tags in scored:
        by_score.setdefault(s, []).append((idx, tags))
    ordered_scores = sorted(by_score.keys(), reverse=True)

    selected: List[Dict[str, Any]] = []
    selected_meta: List[Tuple[int, int, List[str]]] = []
    for s in ordered_scores:
        bucket = by_score[s]
        rng.shuffle(bucket)
        for idx, tags in bucket:
            if len(selected) >= args.max:
                break
            item = data[idx]
            if not isinstance(item, dict):
                continue
            out_item = dict(item)
            out_item["source_index"] = idx
            out_item["hardcase_score"] = s
            out_item["hardcase_tags"] = tags
            selected.append(out_item)
            selected_meta.append((s, idx, tags))
        if len(selected) >= args.max:
            break

    out_path.write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")

    # Print a compact report
    print(f"Loaded seeds: {len(data)}")
    print(f"Eligible (score >= {args.min_score}): {len(scored)}")
    print(f"Selected: {len(selected)} -> {out_path}")

    # Tag frequency among selected
    tag_counts: Dict[str, int] = {}
    for s, idx, tags in selected_meta:
        for t in tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    top = sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:25]
    print("Top tags in selected:")
    for k, v in top:
        print(f"  {k}: {v}")

    # Score histogram (selected)
    hist: Dict[int, int] = {}
    for s, _, _ in selected_meta:
        hist[s] = hist.get(s, 0) + 1
    print("Score histogram (selected):")
    for s in sorted(hist.keys(), reverse=True)[:15]:
        print(f"  score {s}: {hist[s]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

