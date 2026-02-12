#!/usr/bin/env python3
"""
Analyze LLM-scored sycophancy findings: schema-level vs surviving findings.

Schema-level findings (type == "schema_forgiveness") would be caught by tool_correct.py.
Surviving findings (all other types) escape the pipeline.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────
BASE = Path("/Volumes/workplace/Simia-WM-Exp/Simia_SFT/Tau2/output")

FILES = {
    ("telecom", "base"):        BASE / "sycophancy_llm_scores_v2_base_telecom_200.jsonl",
    ("telecom", "strict"):      BASE / "sycophancy_llm_scores_v2_strict_telecom_200.jsonl",
    ("telecom", "sycophantic"): BASE / "sycophancy_llm_scores_v2_sycophantic_telecom_200.jsonl",
    ("airline_retail", "base"):        BASE / "sycophancy_llm_scores_v2_base_hardcase_200_sonnet.jsonl",
    ("airline_retail", "strict"):      BASE / "sycophancy_llm_scores_v2_strict_hardcase_200_sonnet.jsonl",
    ("airline_retail", "sycophantic"): BASE / "sycophancy_llm_scores_v2_sycophantic_hardcase_200_sonnet.jsonl",
}

SCHEMA_TYPE = "schema_forgiveness"
SURVIVING_TYPES = {"policy_forgiveness", "hidden_repair", "id_inconsistency",
                   "semantic_tool_misuse", "other"}

DOMAINS = ["telecom", "airline_retail"]
MODES = ["base", "strict", "sycophantic"]
SEVERITIES = ["low", "medium", "high"]


# ── Load & classify ───────────────────────────────────────────────────────
def load_and_classify(path):
    """Return list of per-conversation dicts with classification info."""
    records = []
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            findings = rec.get("findings", [])
            schema_findings = [fd for fd in findings if fd["type"] == SCHEMA_TYPE]
            surviving_findings = [fd for fd in findings if fd["type"] in SURVIVING_TYPES]

            records.append({
                "conv_idx": rec["conv_idx"],
                "wm_sycophancy_score": rec["wm_sycophancy_score"],
                "procedure_noncompliance_score": rec.get("procedure_noncompliance_score", 0),
                "has_any_finding": len(findings) > 0,
                "has_only_schema": len(findings) > 0 and len(surviving_findings) == 0,
                "has_surviving": len(surviving_findings) > 0,
                "n_schema": len(schema_findings),
                "n_surviving": len(surviving_findings),
                "surviving_types": list({fd["type"] for fd in surviving_findings}),
                "surviving_severities": [fd.get("severity", "unknown") for fd in surviving_findings],
                "max_severity_surviving": max(
                    (SEVERITIES.index(fd.get("severity", "low")) for fd in surviving_findings),
                    default=-1
                ),
            })
    return records


all_data = {}
for (domain, mode), path in FILES.items():
    all_data[(domain, mode)] = load_and_classify(path)


# ── Helpers ────────────────────────────────────────────────────────────────
def fmt_pct(n, total):
    return f"{n:>4d} / {total:<4d}  ({100*n/total:5.1f}%)" if total > 0 else "   0 / 0     (  N/A)"

SEP = "=" * 110
THIN = "-" * 110


# ── Table 1: Main breakdown per domain x mode ─────────────────────────────
print(SEP)
print("TABLE 1 : Finding Classification — Schema-Level vs Surviving")
print(SEP)

header = f"{'Domain':<16} {'Mode':<14} {'Total':>5} {'AnyFinding':>18} {'SchemaOnly':>18} {'Surviving':>18} {'Surv%':>7}"
print(header)
print(THIN)

for domain in DOMAINS:
    for mode in MODES:
        recs = all_data[(domain, mode)]
        total = len(recs)
        any_f = sum(1 for r in recs if r["has_any_finding"])
        schema_only = sum(1 for r in recs if r["has_only_schema"])
        surviving = sum(1 for r in recs if r["has_surviving"])
        pct = f"{100*surviving/total:.1f}%" if total > 0 else "N/A"
        print(f"{domain:<16} {mode:<14} {total:>5} {any_f:>18} {schema_only:>18} {surviving:>18} {pct:>7}")
    print(THIN)


# ── Table 2: Finding counts ───────────────────────────────────────────────
print()
print(SEP)
print("TABLE 2 : Finding Counts — Total Schema vs Total Surviving")
print(SEP)

header2 = f"{'Domain':<16} {'Mode':<14} {'#Schema':>8} {'#Surviving':>11} {'#Total':>8}"
print(header2)
print(THIN)

for domain in DOMAINS:
    for mode in MODES:
        recs = all_data[(domain, mode)]
        n_schema = sum(r["n_schema"] for r in recs)
        n_surv = sum(r["n_surviving"] for r in recs)
        print(f"{domain:<16} {mode:<14} {n_schema:>8} {n_surv:>11} {n_schema+n_surv:>8}")
    print(THIN)


# ── Table 3: Surviving findings by type ───────────────────────────────────
print()
print(SEP)
print("TABLE 3 : Surviving Findings Breakdown by Type")
print(SEP)

type_labels = sorted(SURVIVING_TYPES)
header3 = f"{'Domain':<16} {'Mode':<14}" + "".join(f" {t:>22}" for t in type_labels)
print(header3)
print(THIN)

for domain in DOMAINS:
    for mode in MODES:
        recs = all_data[(domain, mode)]
        type_counts = Counter()
        for r in recs:
            for t in r["surviving_types"]:
                # count actual findings, not unique per conv
                pass
        # recount properly
        type_counts = Counter()
        for r in recs:
            for r2 in all_data[(domain, mode)]:
                pass  # wrong approach
        # redo: iterate findings directly
        type_counts = Counter()
        for r in recs:
            # surviving_types is unique set; let's use surviving_severities indirectly
            # Actually let's just re-parse from the raw data for type counts
            pass

        # Simpler: count from raw surviving types across all findings
        type_counts = Counter()
        with open(FILES[(domain, mode)]) as f:
            for line in f:
                rec = json.loads(line)
                for fd in rec.get("findings", []):
                    if fd["type"] in SURVIVING_TYPES:
                        type_counts[fd["type"]] += 1

        row = f"{domain:<16} {mode:<14}"
        for t in type_labels:
            row += f" {type_counts.get(t, 0):>22}"
        print(row)
    print(THIN)


# ── Table 4: Surviving findings by severity ───────────────────────────────
print()
print(SEP)
print("TABLE 4 : Surviving Findings Breakdown by Severity")
print(SEP)

header4 = f"{'Domain':<16} {'Mode':<14}" + "".join(f" {s:>10}" for s in SEVERITIES)
print(header4)
print(THIN)

for domain in DOMAINS:
    for mode in MODES:
        recs = all_data[(domain, mode)]
        sev_counts = Counter()
        for r in recs:
            for s in r["surviving_severities"]:
                sev_counts[s] += 1
        row = f"{domain:<16} {mode:<14}"
        for s in SEVERITIES:
            row += f" {sev_counts.get(s, 0):>10}"
        print(row)
    print(THIN)


# ── Table 5: Among convs with score > 0, schema-only vs surviving ────────
print()
print(SEP)
print("TABLE 5 : Conversations with wm_sycophancy_score > 0 — Schema-Only vs Surviving")
print(SEP)

header5 = (f"{'Domain':<16} {'Mode':<14} {'Score>0':>8} {'SchemaOnly':>12} {'Surviving':>12} "
           f"{'NoFindings':>12} {'SurvRate':>10}")
print(header5)
print(THIN)

for domain in DOMAINS:
    for mode in MODES:
        recs = all_data[(domain, mode)]
        scored = [r for r in recs if r["wm_sycophancy_score"] > 0]
        n_scored = len(scored)
        n_schema_only = sum(1 for r in scored if r["has_only_schema"])
        n_surviving = sum(1 for r in scored if r["has_surviving"])
        n_no_findings = sum(1 for r in scored if not r["has_any_finding"])
        surv_rate = f"{100*n_surviving/n_scored:.1f}%" if n_scored > 0 else "N/A"
        print(f"{domain:<16} {mode:<14} {n_scored:>8} {n_schema_only:>12} {n_surviving:>12} "
              f"{n_no_findings:>12} {surv_rate:>10}")
    print(THIN)


# ── Table 6: Effective sycophancy scores ──────────────────────────────────
print()
print(SEP)
print("TABLE 6 : Sycophancy Scores — Original vs Effective (surviving-only)")
print(SEP)
print("Effective score: keep original score if conv has surviving finding(s); set to 0 if schema-only or no findings.")
print()

header6 = (f"{'Domain':<16} {'Mode':<14} {'OrigMean':>10} {'EffMean':>10} {'Reduction':>10} "
           f"{'Orig>0':>8} {'Eff>0':>8}")
print(header6)
print(THIN)

for domain in DOMAINS:
    for mode in MODES:
        recs = all_data[(domain, mode)]
        total = len(recs)

        orig_scores = [r["wm_sycophancy_score"] for r in recs]
        eff_scores = [
            r["wm_sycophancy_score"] if r["has_surviving"] else 0
            for r in recs
        ]

        orig_mean = sum(orig_scores) / total if total > 0 else 0
        eff_mean = sum(eff_scores) / total if total > 0 else 0
        reduction = orig_mean - eff_mean

        orig_gt0 = sum(1 for s in orig_scores if s > 0)
        eff_gt0 = sum(1 for s in eff_scores if s > 0)

        print(f"{domain:<16} {mode:<14} {orig_mean:>10.2f} {eff_mean:>10.2f} {reduction:>10.2f} "
              f"{orig_gt0:>8} {eff_gt0:>8}")
    print(THIN)


# ── Table 7: Summary comparison table ─────────────────────────────────────
print()
print(SEP)
print("TABLE 7 : Side-by-Side Summary — Telecom vs Airline/Retail")
print(SEP)

metrics = [
    ("Convs with ANY finding",      lambda recs: sum(1 for r in recs if r["has_any_finding"])),
    ("Convs SCHEMA-ONLY",           lambda recs: sum(1 for r in recs if r["has_only_schema"])),
    ("Convs with SURVIVING",        lambda recs: sum(1 for r in recs if r["has_surviving"])),
    ("Surviving rate (%)",           lambda recs: f"{100*sum(1 for r in recs if r['has_surviving'])/len(recs):.1f}" if recs else "N/A"),
    ("Total surviving findings",    lambda recs: sum(r["n_surviving"] for r in recs)),
    ("Orig mean syco score",        lambda recs: f"{sum(r['wm_sycophancy_score'] for r in recs)/len(recs):.2f}" if recs else "N/A"),
    ("Eff mean syco score",         lambda recs: f"{sum(r['wm_sycophancy_score'] if r['has_surviving'] else 0 for r in recs)/len(recs):.2f}" if recs else "N/A"),
]

# Print header
row_h = f"{'Metric':<30}"
for domain in DOMAINS:
    for mode in MODES:
        row_h += f" {domain[:6]+'/'+mode[:5]:>14}"
print(row_h)
print(THIN)

for metric_name, metric_fn in metrics:
    row = f"{metric_name:<30}"
    for domain in DOMAINS:
        for mode in MODES:
            val = metric_fn(all_data[(domain, mode)])
            if isinstance(val, float):
                row += f" {val:>14.1f}"
            else:
                row += f" {str(val):>14}"
    print(row)
print(THIN)


# ── Extra: detailed look at score>0 + no-findings cases ──────────────────
print()
print(SEP)
print("DETAIL : Conversations with score > 0 but NO findings (LLM scored sycophancy with no cited evidence)")
print(SEP)

for domain in DOMAINS:
    for mode in MODES:
        recs = all_data[(domain, mode)]
        anomalies = [r for r in recs if r["wm_sycophancy_score"] > 0 and not r["has_any_finding"]]
        if anomalies:
            scores = [r["wm_sycophancy_score"] for r in anomalies]
            print(f"  {domain}/{mode}: {len(anomalies)} convs, scores = {sorted(scores)}")
        else:
            print(f"  {domain}/{mode}: 0 convs")

print()
print("Done.")
