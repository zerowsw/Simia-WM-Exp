#!/usr/bin/env python3
"""
Analyze "sycophancy" / leniency artifacts in Tau2 SFT generated data.

Primary high-confidence signal:
  - A tool call is invalid per its JSON schema (unknown tool, missing required args,
    wrong arg types, non-object arguments), BUT the next OBSERVATION is not error-like.

Additional (best-effort) checks:
  - Extra/unknown argument keys in tool calls (args not present in schema properties)
  - Pending/delivered status-gating violations (retail-policy hard constraints)
  - Cross-user scope violations (retail-policy hard constraints)
  - Mismatch between <think> declared tool name and actual tool name (data quality)

Usage:
  python3 analyze_sycophancy.py --input output/tau2_sycophantic_error_80.json
  python3 analyze_sycophancy.py --input output/tau2_sycophantic_error_80.json --output findings.json

Compare multiple files:
  python3 analyze_sycophancy.py --inputs output/tau2_base_error_80.json output/tau2_strict_error_80.json output/tau2_sycophantic_error_80.json
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
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
]

SUCCESS_KEYWORDS = [
    "success",
    "successful",
    "successfully",
    "completed",
    "confirmed",
    "approved",
    "created",
    "updated",
    "booked",
    "transferred",
    "processed",
    "done",
]

def _lower_list(xs: Any) -> List[str]:
    if not isinstance(xs, list):
        return []
    out: List[str] = []
    for x in xs:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out


def _contains_any(haystack: str, needles: List[str]) -> bool:
    low = haystack.lower()
    for n in needles:
        if n.lower() in low:
            return True
    return False


def _regex_any(text: str, patterns: List[str]) -> bool:
    for p in patterns:
        try:
            if re.search(p, text, flags=re.IGNORECASE | re.DOTALL):
                return True
        except re.error:
            # Invalid regex: ignore this pattern
            continue
    return False


def load_rule_packs(rule_paths: List[str]) -> Dict[str, Any]:
    """
    Load and merge one or more rule pack JSON files.

    Rule pack format (version 1, minimal):
      {
        "version": 1,
        "error_keywords": [... optional ...],
        "success_keywords": [... optional ...],
        "rules": [
          {
            "id": "basic_economy_refund_denied",
            "enabled": true,                          # IMPORTANT: default is disabled unless explicitly true
            "apply_if": {
              "domain_in": ["airline"],                   # optional
              "policy_contains_any": ["Basic Economy"]    # optional (matches conv.system)
            },
            "when": {
              "tool_name_in": ["refund_ticket"],          # optional
              "context_contains_any": ["refund"],         # optional (matches context turns)
              "context_regex_any": ["refun(d|ding)"],     # optional
              "call_regex_any": ["\\\"cabin\\\"\\s*:\\s*\\\"basic\\\""]  # optional (matches raw function_call)
            },
            "require_success_like_observation": true      # optional, default false
          }
        ]
      }
    """
    merged: Dict[str, Any] = {"version": 1, "rules": []}
    for rp in rule_paths:
        p = Path(rp)
        if not p.exists():
            continue
        obj = _safe_json_loads(p.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            continue
        # override keywords if provided (last one wins)
        if isinstance(obj.get("error_keywords"), list):
            merged["error_keywords"] = _lower_list(obj.get("error_keywords"))
        if isinstance(obj.get("success_keywords"), list):
            merged["success_keywords"] = _lower_list(obj.get("success_keywords"))
        if isinstance(obj.get("rules"), list):
            merged["rules"].extend([r for r in obj["rules"] if isinstance(r, dict)])
    return merged

PENDING_ONLY_TOOLS = {
    "cancel_pending_order",
    "modify_pending_order_address",
    "modify_pending_order_payment",
    "modify_pending_order_items",
}
DELIVERED_ONLY_TOOLS = {
    "return_delivered_order_items",
    "exchange_delivered_order_items",
}


@dataclass
class Finding:
    kind: str
    input_path: str
    conv_idx: int
    based_on_sample: Optional[str]
    domain: Optional[str]
    simulator_mode: Optional[str]
    turn_idx: int
    tool_name: Optional[str]
    problems: List[str]
    function_call_raw: str
    function_call_parsed: Optional[Dict[str, Any]]
    observation_raw: Optional[str]
    observation_is_error_like: Optional[bool]
    observation_is_success_like: Optional[bool]
    context_turns: List[Dict[str, str]]  # [{"from":..., "value":...}, ...]


def _safe_json_loads(s: str) -> Optional[Any]:
    try:
        return json.loads(s)
    except Exception:
        return None


def extract_json_object(s: str) -> Optional[Dict[str, Any]]:
    """Extract a JSON object from a string that may contain <think> blocks."""
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


def is_error_like_observation(obs_val: Optional[str]) -> bool:
    s = (obs_val or "").strip()
    low = s.lower()
    if any(k in low for k in ERROR_KEYWORDS):
        return True
    if s.startswith("{") and s.endswith("}"):
        obj = _safe_json_loads(s)
        if isinstance(obj, dict):
            if any(k in obj for k in ("error", "errors", "exception", "traceback")):
                return True
            msg = obj.get("message") or obj.get("detail") or obj.get("details")
            if isinstance(msg, str) and any(k in msg.lower() for k in ERROR_KEYWORDS):
                return True
    return False


def is_success_like_observation(obs_val: Optional[str]) -> bool:
    """
    Heuristic success detector.
    - Keyword match in raw text
    - Common JSON patterns: {"result":"success"}, {"status":"success"}, {"ok":true}
    """
    s = (obs_val or "").strip()
    low = s.lower()
    if any(k in low for k in SUCCESS_KEYWORDS):
        return True
    if s.startswith("{") and s.endswith("}"):
        obj = _safe_json_loads(s)
        if isinstance(obj, dict):
            for k in ("result", "status", "outcome"):
                v = obj.get(k)
                if isinstance(v, str) and v.lower() in ("success", "ok", "passed", "done"):
                    return True
            ok = obj.get("ok") or obj.get("success")
            if ok is True:
                return True
            msg = obj.get("message")
            if isinstance(msg, str) and any(k in msg.lower() for k in SUCCESS_KEYWORDS):
                return True
    return False


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
) -> Tuple[Optional[str], List[str]]:
    """Return (tool_name, problems). Empty problems means schema-valid."""
    problems: List[str] = []
    name = call.get("name")
    args = call.get("arguments")

    if not isinstance(name, str) or not name:
        return None, ["missing tool name"]
    if name not in tools:
        return name, [f"unknown tool: {name}"]

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

    return name, problems


def find_extra_arg_keys(
    call: Dict[str, Any],
    tools: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[str], List[str]]:
    """Return (tool_name, extra_keys[]) where extra_keys are args not in schema properties."""
    name = call.get("name")
    args = call.get("arguments")
    if not isinstance(name, str) or not name:
        return None, []
    if name not in tools:
        return name, []
    if not isinstance(args, dict):
        return name, []
    props = (tools[name].get("parameters") or {}).get("properties") or {}
    if not isinstance(props, dict):
        return name, []
    extra = [k for k in args.keys() if k not in props]
    return name, extra


def extract_declared_tool_name_from_think(text: str) -> Optional[str]:
    """
    Extract declared tool name from <think> text.
    We intentionally require a tool-like token (underscored / >=3 chars) to avoid
    false captures like 'to'.
    """
    m = re.search(r"I will call the function\s+([a-zA-Z][a-zA-Z0-9_]{2,})\b", text or "")
    return m.group(1) if m else None


def _context_slice(turns: List[Dict[str, Any]], center: int, radius: int) -> List[Dict[str, str]]:
    lo = max(0, center - radius)
    hi = min(len(turns), center + radius + 1)
    return [{"from": str(t.get("from", "")), "value": str(t.get("value", ""))} for t in turns[lo:hi]]


def analyze_file(
    input_path: Path,
    *,
    context_radius: int = 2,
    max_findings_per_kind: int = 0,
    rule_pack: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, int], List[Finding]]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected top-level JSON list, got {type(data).__name__}")

    counters: Dict[str, int] = {
        "conversations": len(data),
        "function_calls": 0,
        "observations": 0,
        "error_like_observations": 0,
        "success_like_observations": 0,
        "schema_invalid_calls": 0,
        "schema_invalid_but_non_error_obs": 0,
        "extra_arg_keys_calls": 0,
        "extra_arg_keys_but_non_error_obs": 0,
        "pending_delivered_violations_non_error_obs": 0,
        "cross_user_violations_non_error_obs": 0,
        "think_actual_tool_mismatch": 0,
        "declared_tool_unknown_or_diff": 0,
        "rule_violations_non_error_obs": 0,
    }

    findings: List[Finding] = []
    per_kind_seen: Dict[str, int] = {}
    rule_counts: Dict[str, int] = {}

    # allow keyword override via rule pack (last-wins semantics)
    global ERROR_KEYWORDS, SUCCESS_KEYWORDS
    if rule_pack and isinstance(rule_pack.get("error_keywords"), list) and rule_pack["error_keywords"]:
        ERROR_KEYWORDS = list(rule_pack["error_keywords"])
    if rule_pack and isinstance(rule_pack.get("success_keywords"), list) and rule_pack["success_keywords"]:
        SUCCESS_KEYWORDS = list(rule_pack["success_keywords"])

    def maybe_add(f: Finding) -> None:
        if max_findings_per_kind and max_findings_per_kind > 0:
            seen = per_kind_seen.get(f.kind, 0)
            if seen >= max_findings_per_kind:
                return
            per_kind_seen[f.kind] = seen + 1
        findings.append(f)

    for conv_idx, conv in enumerate(data):
        turns = conv.get("conversations") or []
        if not isinstance(turns, list):
            continue

        tools = load_tools(conv.get("tools"))
        based_on_sample = conv.get("based_on_sample") if isinstance(conv.get("based_on_sample"), str) else None
        domain = conv.get("domain") if isinstance(conv.get("domain"), str) else None
        simulator_mode = conv.get("simulator_mode") if isinstance(conv.get("simulator_mode"), str) else None
        system_policy_text = conv.get("system") if isinstance(conv.get("system"), str) else ""

        last_order_status: Dict[str, str] = {}
        authed_user: Optional[str] = None

        for turn_idx, turn in enumerate(turns):
            frm = turn.get("from")
            val = turn.get("value", "")

            if frm == "observation":
                counters["observations"] += 1
                if is_error_like_observation(str(val)):
                    counters["error_like_observations"] += 1
                if is_success_like_observation(str(val)):
                    counters["success_like_observations"] += 1

            if frm != "function_call":
                continue

            counters["function_calls"] += 1

            call_raw = str(val)
            call = extract_json_object(call_raw)
            if not isinstance(call, dict):
                continue

            # Declared vs actual mismatch (data quality)
            declared = extract_declared_tool_name_from_think(call_raw)
            actual = call.get("name")
            if declared:
                # semantic mismatch: declared tool differs from actual, OR declared tool not in tool list
                if not isinstance(actual, str) or declared != actual or declared not in tools:
                    counters["declared_tool_unknown_or_diff"] += 1
                    maybe_add(
                        Finding(
                            kind="declared_tool_unknown_or_diff",
                            input_path=str(input_path),
                            conv_idx=conv_idx,
                            based_on_sample=based_on_sample,
                            domain=domain,
                            simulator_mode=simulator_mode,
                            turn_idx=turn_idx,
                            tool_name=str(actual) if isinstance(actual, str) else None,
                            problems=[
                                f"declared={declared}",
                                f"actual={actual}",
                                f"declared_in_tool_list={declared in tools}",
                            ],
                            function_call_raw=call_raw,
                            function_call_parsed=call,
                            observation_raw=(
                                str(turns[turn_idx + 1].get("value"))
                                if turn_idx + 1 < len(turns)
                                and turns[turn_idx + 1].get("from") == "observation"
                                else None
                            ),
                            observation_is_error_like=None,
                            observation_is_success_like=None,
                            context_turns=_context_slice(turns, turn_idx, context_radius),
                        )
                    )

            if declared and isinstance(actual, str) and declared != actual:
                counters["think_actual_tool_mismatch"] += 1
                maybe_add(
                    Finding(
                        kind="think_actual_tool_mismatch",
                        input_path=str(input_path),
                        conv_idx=conv_idx,
                        based_on_sample=based_on_sample,
                        domain=domain,
                        simulator_mode=simulator_mode,
                        turn_idx=turn_idx,
                        tool_name=actual,
                        problems=[f"declared={declared}", f"actual={actual}"],
                        function_call_raw=call_raw,
                        function_call_parsed=call,
                        observation_raw=(
                            str(turns[turn_idx + 1].get("value"))
                            if turn_idx + 1 < len(turns) and turns[turn_idx + 1].get("from") == "observation"
                            else None
                        ),
                        observation_is_error_like=None,
                        observation_is_success_like=None,
                        context_turns=_context_slice(turns, turn_idx, context_radius),
                    )
                )

            # Next observation (if any)
            next_obs_val: Optional[str] = None
            if turn_idx + 1 < len(turns) and turns[turn_idx + 1].get("from") == "observation":
                next_obs_val = str(turns[turn_idx + 1].get("value", ""))
            next_obs_is_error = (
                is_error_like_observation(next_obs_val) if next_obs_val is not None else None
            )
            next_obs_is_success = (
                is_success_like_observation(next_obs_val) if next_obs_val is not None else None
            )

            # 0) Optional rule-pack checks (stateless heuristics over context/call/policy)
            if rule_pack and isinstance(rule_pack.get("rules"), list) and next_obs_val is not None:
                # Build a small context text window for matching
                ctx_turns = _context_slice(turns, turn_idx, context_radius)
                ctx_text = "\n".join([f"{t.get('from')}: {t.get('value')}" for t in ctx_turns])

                for rule in rule_pack["rules"]:
                    if not isinstance(rule, dict):
                        continue
                    rule_id = rule.get("id")
                    if not isinstance(rule_id, str) or not rule_id:
                        continue
                    # Default-disable: only run rules explicitly enabled.
                    if rule.get("enabled") is not True:
                        continue

                    apply_if = rule.get("apply_if") if isinstance(rule.get("apply_if"), dict) else {}
                    when = rule.get("when") if isinstance(rule.get("when"), dict) else {}

                    domain_in = _lower_list(apply_if.get("domain_in"))
                    if domain_in and (domain or "") not in domain_in:
                        continue

                    policy_contains_any = _lower_list(apply_if.get("policy_contains_any"))
                    if policy_contains_any and not _contains_any(system_policy_text or "", policy_contains_any):
                        continue

                    tool_name_in = _lower_list(when.get("tool_name_in"))
                    if tool_name_in:
                        actual_tool = call.get("name")
                        if not isinstance(actual_tool, str) or actual_tool not in tool_name_in:
                            continue

                    context_contains_any = _lower_list(when.get("context_contains_any"))
                    if context_contains_any and not _contains_any(ctx_text, context_contains_any):
                        continue

                    context_regex_any = _lower_list(when.get("context_regex_any"))
                    if context_regex_any and not _regex_any(ctx_text, context_regex_any):
                        continue

                    call_regex_any = _lower_list(when.get("call_regex_any"))
                    if call_regex_any and not _regex_any(call_raw, call_regex_any):
                        continue

                    require_success_like = bool(rule.get("require_success_like_observation", False))
                    if require_success_like and next_obs_is_success is not True:
                        continue

                    # Violation definition for these rules: observation is NOT error-like
                    if next_obs_is_error is False:
                        counters["rule_violations_non_error_obs"] += 1
                        rule_counts[rule_id] = rule_counts.get(rule_id, 0) + 1
                        maybe_add(
                            Finding(
                                kind="rule_violation_but_non_error_observation",
                                input_path=str(input_path),
                                conv_idx=conv_idx,
                                based_on_sample=based_on_sample,
                                domain=domain,
                                simulator_mode=simulator_mode,
                                turn_idx=turn_idx,
                                tool_name=str(call.get("name")) if isinstance(call.get("name"), str) else None,
                                problems=[f"rule_id={rule_id}", f"rule={rule.get('description','')}".strip()],
                                function_call_raw=call_raw,
                                function_call_parsed=call,
                                observation_raw=next_obs_val,
                                observation_is_error_like=next_obs_is_error,
                                observation_is_success_like=next_obs_is_success,
                                context_turns=ctx_turns,
                            )
                        )

            # 1) Schema invalid call with non-error observation (high-confidence sycophancy)
            tool_name, schema_problems = validate_tool_call_schema(call, tools)
            if schema_problems:
                counters["schema_invalid_calls"] += 1
                if next_obs_val is not None and next_obs_is_error is False:
                    counters["schema_invalid_but_non_error_obs"] += 1
                    maybe_add(
                        Finding(
                            kind="schema_invalid_but_non_error_observation",
                            input_path=str(input_path),
                            conv_idx=conv_idx,
                            based_on_sample=based_on_sample,
                            domain=domain,
                            simulator_mode=simulator_mode,
                            turn_idx=turn_idx,
                            tool_name=tool_name,
                            problems=schema_problems,
                            function_call_raw=call_raw,
                            function_call_parsed=call,
                            observation_raw=next_obs_val,
                            observation_is_error_like=next_obs_is_error,
                            observation_is_success_like=next_obs_is_success,
                            context_turns=_context_slice(turns, turn_idx, context_radius),
                        )
                    )

            # 2) Extra arg keys with non-error observation (also high-confidence)
            tool_name2, extra_keys = find_extra_arg_keys(call, tools)
            if extra_keys:
                counters["extra_arg_keys_calls"] += 1
                if next_obs_val is not None and next_obs_is_error is False:
                    counters["extra_arg_keys_but_non_error_obs"] += 1
                    maybe_add(
                        Finding(
                            kind="extra_arg_keys_but_non_error_observation",
                            input_path=str(input_path),
                            conv_idx=conv_idx,
                            based_on_sample=based_on_sample,
                            domain=domain,
                            simulator_mode=simulator_mode,
                            turn_idx=turn_idx,
                            tool_name=tool_name2,
                            problems=[f"extra_arg_keys={extra_keys}"],
                            function_call_raw=call_raw,
                            function_call_parsed=call,
                            observation_raw=next_obs_val,
                            observation_is_error_like=next_obs_is_error,
                            observation_is_success_like=next_obs_is_success,
                            context_turns=_context_slice(turns, turn_idx, context_radius),
                        )
                    )

            # Track authentication (best-effort)
            if call.get("name") in ("find_user_id_by_email", "find_user_id_by_name_zip"):
                if next_obs_val is not None:
                    parsed_obs = extract_json_object(next_obs_val) or _safe_json_loads(next_obs_val)
                    if isinstance(parsed_obs, dict) and isinstance(parsed_obs.get("user_id"), str):
                        authed_user = parsed_obs["user_id"]
                    elif next_obs_val and not next_obs_val.strip().startswith("{"):
                        authed_user = next_obs_val.strip().strip('"')

            # Track order status from get_order_details
            if call.get("name") == "get_order_details" and next_obs_val is not None:
                parsed = extract_json_object(next_obs_val) or _safe_json_loads(next_obs_val)
                if isinstance(parsed, dict):
                    oid = parsed.get("order_id")
                    st = parsed.get("status")
                    if isinstance(oid, str) and isinstance(st, str):
                        last_order_status[oid] = st

            # 3) Pending/delivered gating violations with non-error observation
            name = call.get("name")
            args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            order_id = args.get("order_id") if isinstance(args.get("order_id"), str) else None
            if isinstance(name, str) and order_id and order_id in last_order_status:
                known_status = last_order_status[order_id]
                required_status: Optional[str] = None
                if name in PENDING_ONLY_TOOLS:
                    required_status = "pending"
                elif name in DELIVERED_ONLY_TOOLS:
                    required_status = "delivered"
                if required_status and known_status != required_status:
                    if next_obs_val is not None and next_obs_is_error is False:
                        counters["pending_delivered_violations_non_error_obs"] += 1
                        maybe_add(
                            Finding(
                                kind="pending_delivered_violation_but_non_error_observation",
                                input_path=str(input_path),
                                conv_idx=conv_idx,
                                based_on_sample=based_on_sample,
                                domain=domain,
                                simulator_mode=simulator_mode,
                                turn_idx=turn_idx,
                                tool_name=name,
                                problems=[
                                    f"order_id={order_id}",
                                    f"known_status={known_status}",
                                    f"required_status={required_status}",
                                ],
                                function_call_raw=call_raw,
                                function_call_parsed=call,
                                observation_raw=next_obs_val,
                                observation_is_error_like=next_obs_is_error,
                                observation_is_success_like=next_obs_is_success,
                                context_turns=_context_slice(turns, turn_idx, context_radius),
                            )
                        )

            # 4) Cross-user violations with non-error observation
            if authed_user and isinstance(args, dict) and isinstance(name, str):
                if isinstance(args.get("user_id"), str) and args["user_id"] != authed_user:
                    if next_obs_val is not None and next_obs_is_error is False:
                        counters["cross_user_violations_non_error_obs"] += 1
                        maybe_add(
                            Finding(
                                kind="cross_user_violation_but_non_error_observation",
                                input_path=str(input_path),
                                conv_idx=conv_idx,
                                based_on_sample=based_on_sample,
                                domain=domain,
                                simulator_mode=simulator_mode,
                                turn_idx=turn_idx,
                                tool_name=name,
                                problems=[f"authed_user={authed_user}", f"called_user={args.get('user_id')}"],
                                function_call_raw=call_raw,
                                function_call_parsed=call,
                                observation_raw=next_obs_val,
                                observation_is_error_like=next_obs_is_error,
                                observation_is_success_like=next_obs_is_success,
                                context_turns=_context_slice(turns, turn_idx, context_radius),
                            )
                        )

    # Attach rule_counts into counters for JSON output consumers (kept out of the summary table)
    if rule_counts:
        counters["_rule_counts"] = len(rule_counts)
    return counters, findings, rule_counts


def _print_summary_table(rows: List[Tuple[str, Dict[str, int]]]) -> None:
    cols = [
        "conversations",
        "function_calls",
        "error_like_observations",
        "success_like_observations",
        "schema_invalid_calls",
        "schema_invalid_but_non_error_obs",
        "extra_arg_keys_calls",
        "extra_arg_keys_but_non_error_obs",
        "pending_delivered_violations_non_error_obs",
        "cross_user_violations_non_error_obs",
        "think_actual_tool_mismatch",
        "declared_tool_unknown_or_diff",
    ]
    widths = {c: max(len(c), 6) for c in cols}
    name_w = max(8, max(len(name) for name, _ in rows))
    header = " ".join([f"{'input':<{name_w}}"] + [f"{c:>{widths[c]}}" for c in cols])
    print(header)
    print("-" * len(header))
    for name, ctr in rows:
        parts = [f"{name:<{name_w}}"]
        for c in cols:
            parts.append(f"{ctr.get(c, 0):>{widths[c]}}")
        print(" ".join(parts))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str, default="", help="Single Tau2 output JSON path.")
    parser.add_argument("--inputs", nargs="+", help="Multiple Tau2 output JSON paths (compare).")
    parser.add_argument("--output", type=str, default="", help="Write findings JSON to this file.")
    parser.add_argument("--context-radius", type=int, default=2, help="Turns before/after to include.")
    parser.add_argument(
        "--rules",
        nargs="*",
        default=[],
        help="Optional rule pack JSON file(s) to enable additional policy/semantic checks.",
    )
    parser.add_argument(
        "--max-findings-per-kind",
        type=int,
        default=0,
        help="Cap findings per kind (0 = no cap).",
    )
    args = parser.parse_args()

    if args.inputs:
        paths = [Path(p) for p in args.inputs]
    elif args.input:
        paths = [Path(args.input)]
    else:
        parser.error("Provide --input or --inputs")

    rule_pack = load_rule_packs(args.rules) if args.rules else None

    summary_rows: List[Tuple[str, Dict[str, int]]] = []
    all_findings: List[Finding] = []
    rule_counts_by_input: Dict[str, Dict[str, int]] = {}

    for p in paths:
        ctr, findings, rule_counts = analyze_file(
            p,
            context_radius=args.context_radius,
            max_findings_per_kind=args.max_findings_per_kind,
            rule_pack=rule_pack,
        )
        summary_rows.append((p.name, ctr))
        all_findings.extend(findings)
        rule_counts_by_input[p.name] = rule_counts

    _print_summary_table(summary_rows)

    if args.output:
        out_path = Path(args.output)
        payload = {
            "inputs": [str(p) for p in paths],
            "rules_loaded": list(args.rules) if args.rules else [],
            "summary": {name: ctr for name, ctr in summary_rows},
            "rule_counts": rule_counts_by_input,
            "findings": [asdict(f) for f in all_findings],
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote findings JSON: {out_path}")
        print(f"Total findings: {len(all_findings)}")
    else:
        hi = [
            f
            for f in all_findings
            if f.kind
            in (
                "schema_invalid_but_non_error_observation",
                "extra_arg_keys_but_non_error_observation",
                "pending_delivered_violation_but_non_error_observation",
                "cross_user_violation_but_non_error_observation",
            )
        ]
        if hi:
            print("\nHigh-confidence sycophancy candidates (preview):")
            for f in hi[:10]:
                print("-" * 80)
                print(
                    f"{f.kind} | {Path(f.input_path).name} | conv={f.conv_idx} turn={f.turn_idx} tool={f.tool_name}"
                )
                if f.based_on_sample:
                    print(f"  based_on_sample={f.based_on_sample}")
                if f.problems:
                    print(f"  problems={f.problems}")
                if f.observation_raw is not None:
                    snip = f.observation_raw.replace("\\n", " ")[:220]
                    print(f"  observation_snip={snip}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

