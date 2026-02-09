#!/usr/bin/env python3
"""
Format sycophancy review JSONL into human-readable Markdown.

Reads JSONL created by extract_highscore_reviews.py:
  - output/sycophancy_review_score70.jsonl
  - output/sycophancy_review_score60_69.jsonl

Writes:
  - output/sycophancy_review_score70.md
  - output/sycophancy_review_score60_69.md
  - output/sycophancy_review_score70_split/*.md
  - output/sycophancy_review_score60_69_split/*.md
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "output"


def iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield obj


def safe_json_loads(s: str) -> Optional[Any]:
    try:
        return json.loads(s)
    except Exception:
        return None


def extract_json_obj(s: str) -> Optional[Dict[str, Any]]:
    s = (s or "").strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    obj = safe_json_loads(s[start : end + 1])
    return obj if isinstance(obj, dict) else None


def md_escape(s: str) -> str:
    # minimal escaping to avoid breaking headings/tables
    return (s or "").replace("\r\n", "\n").replace("\r", "\n")


def md_code_block(text: str, lang: str = "") -> str:
    text = (text or "").rstrip()
    fence = "```"
    # avoid accidental fence termination
    text = text.replace("```", "``\\`")
    return f"{fence}{lang}\n{text}\n{fence}\n"


def shorten(s: str, max_chars: int) -> Tuple[str, bool]:
    s = s or ""
    if len(s) <= max_chars:
        return s, False
    return s[: max_chars - 1] + "…", True


def details_block(summary: str, body_md: str) -> str:
    return f"<details>\n<summary>{md_escape(summary)}</summary>\n\n{body_md}\n</details>\n"


def format_findings(findings: Any) -> str:
    if not isinstance(findings, list) or not findings:
        return "_(none)_\n"
    lines = []
    for i, f in enumerate(findings, 1):
        if not isinstance(f, dict):
            continue
        f_type = f.get("type")
        sev = f.get("severity")
        ti = f.get("turn_index")
        why = f.get("why_sycophantic")
        excerpt = f.get("excerpt")
        lines.append(f"- **{md_escape(str(f_type))}** (severity={md_escape(str(sev))}, turn={ti})")
        if excerpt:
            ex_s, truncated = shorten(str(excerpt), 220)
            if truncated:
                ex_s += " _(truncated)_"
            lines.append(f"  - excerpt: `{md_escape(ex_s)}`")
        if why:
            lines.append(f"  - why: {md_escape(str(why))}")
    return "\n".join(lines) + "\n"


def _pretty_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False)


def _format_turn_value(turn_from: str, value: Any, max_chars: int) -> str:
    raw = "" if value is None else str(value)
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").strip()

    # Special case: function_call values often include <think> + JSON blob
    if turn_from == "function_call":
        call = extract_json_obj(raw)
        if call:
            body = md_code_block(_pretty_json(call), lang="json")
            # keep raw in a fold for debugging
            raw_short, truncated = shorten(raw, max_chars)
            raw_body = md_code_block(raw_short, lang="text")
            if truncated:
                raw_body = raw_body.replace("\n```\n", "\n```\n\n_(raw truncated)_\n")
            body += details_block("raw function_call text", raw_body)
            return body

    # observation: pretty print JSON if possible
    if turn_from == "observation":
        obj = safe_json_loads(raw) if raw.startswith("{") or raw.startswith("[") else None
        if obj is not None:
            pretty = _pretty_json(obj)
            body = md_code_block(pretty, lang="json")
            # raw fold only if huge or not identical
            raw_short, truncated = shorten(raw, max_chars)
            if truncated:
                body += details_block("raw observation text (truncated)", md_code_block(raw_short, lang="text"))
            return body

    # fallback: just text, with truncation fold
    short, truncated = shorten(raw, max_chars)
    body = md_code_block(short, lang="text")
    if truncated:
        body += "\n_(text truncated in-place; increase --max-chars if needed)_\n"
    return body


def format_record_md(rec: Dict[str, Any], max_chars: int) -> str:
    mode = rec.get("mode")
    conv_idx = rec.get("conv_idx")
    score = rec.get("score")
    conf = rec.get("confidence")
    based = rec.get("based_on_sample")

    mj = rec.get("my_judgement") if isinstance(rec.get("my_judgement"), dict) else {}
    likely = mj.get("wm_sycophancy_likely")
    signals = mj.get("signals")
    notes = mj.get("notes")

    conv = rec.get("conversation") if isinstance(rec.get("conversation"), dict) else {}
    system = conv.get("system")
    tools = conv.get("tools")
    turns = conv.get("conversations") if isinstance(conv.get("conversations"), list) else []

    out = []
    out.append(f"## {mode} / conv_idx={conv_idx} / score={score}\n")
    out.append(f"- **confidence**: {conf}\n")
    out.append(f"- **based_on_sample**: `{md_escape(str(based))}`\n")
    out.append(f"- **my judgement (wm_sycophancy_likely)**: `{md_escape(str(likely))}`\n")
    if isinstance(signals, list) and signals:
        out.append(f"- **signals**: {', '.join(f'`{md_escape(str(s))}`' for s in signals)}\n")
    if isinstance(notes, list) and notes:
        out.append(f"- **notes**:\n")
        for n in notes:
            out.append(f"  - {md_escape(str(n))}\n")
        out.append("\n")

    # evaluator summary
    out.append("### Evaluator findings\n\n")
    out.append(format_findings(rec.get("evaluator_findings")))
    rat = rec.get("evaluator_rationale")
    if rat:
        out.append("\n### Evaluator rationale\n\n")
        out.append(md_escape(str(rat)).strip() + "\n")

    # System + tools: fold (very long)
    if system:
        sys_short, truncated = shorten(str(system), max_chars)
        body = md_code_block(sys_short, lang="text")
        if truncated:
            body += "\n_(system truncated; open raw by increasing --max-chars)_\n"
        out.append("\n### System\n\n")
        out.append(details_block("system text", body))

    if tools:
        # tools may be JSON string or list
        tools_obj = None
        if isinstance(tools, str):
            tools_obj = safe_json_loads(tools)
        elif isinstance(tools, list):
            tools_obj = tools
        if tools_obj is not None:
            # show only tool names in main view
            names = []
            for t in tools_obj if isinstance(tools_obj, list) else []:
                if isinstance(t, dict) and "name" in t:
                    names.append(str(t["name"]))
            if names:
                out.append("\n### Tools (names)\n\n")
                out.append(", ".join(f"`{md_escape(n)}`" for n in names) + "\n")
            out.append("\n### Tools (full)\n\n")
            out.append(details_block("full tools JSON", md_code_block(_pretty_json(tools_obj), lang="json")))
        else:
            tools_short, _ = shorten(str(tools), max_chars)
            out.append("\n### Tools (raw)\n\n")
            out.append(details_block("raw tools text", md_code_block(tools_short, lang="text")))

    # Turns
    out.append("\n### Conversation turns\n\n")
    for i, t in enumerate(turns):
        if not isinstance(t, dict):
            continue
        frm = t.get("from")
        val = t.get("value")
        out.append(f"#### Turn {i} — `{md_escape(str(frm))}`\n\n")
        out.append(_format_turn_value(str(frm), val, max_chars=max_chars))
        out.append("\n")

    return "".join(out).rstrip() + "\n"


def write_markdown(
    in_jsonl: Path,
    out_md: Path,
    split_dir: Optional[Path],
    max_chars: int,
) -> None:
    records = list(iter_jsonl(in_jsonl))
    # stable sort for manual review
    records.sort(key=lambda r: (str(r.get("mode")), int(r.get("conv_idx", -1))))

    parts = []
    parts.append(f"# Sycophancy review: `{in_jsonl.name}`\n\n")
    parts.append("## Index\n\n")
    for r in records:
        parts.append(
            f"- [{r.get('mode')} / conv_idx={r.get('conv_idx')} / score={r.get('score')}]"
            f"(#{r.get('mode')}-/-conv_idx={r.get('conv_idx')}-/-score={r.get('score')})\n"
        )
    parts.append("\n---\n\n")

    if split_dir is not None:
        split_dir.mkdir(parents=True, exist_ok=True)

    for r in records:
        sec = format_record_md(r, max_chars=max_chars)
        # add an anchor-friendly header id: GitHub-ish; keep simple by duplicating title line without spaces
        # (Cursor Markdown doesn't rely on exact IDs; index links are best-effort)
        parts.append(sec)
        parts.append("\n---\n\n")

        if split_dir is not None:
            mode = r.get("mode")
            conv_idx = r.get("conv_idx")
            score = r.get("score")
            fn = split_dir / f"{mode}_conv{conv_idx}_score{score}.md"
            fn.write_text(sec, encoding="utf-8")

    out_md.write_text("".join(parts), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-chars", type=int, default=4000, help="truncate long system/tools/raw text")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pairs = [
        (
            OUT_DIR / "sycophancy_review_score70.jsonl",
            OUT_DIR / "sycophancy_review_score70.md",
            OUT_DIR / "sycophancy_review_score70_split",
        ),
        (
            OUT_DIR / "sycophancy_review_score60_69.jsonl",
            OUT_DIR / "sycophancy_review_score60_69.md",
            OUT_DIR / "sycophancy_review_score60_69_split",
        ),
    ]

    for in_jsonl, out_md, split_dir in pairs:
        if not in_jsonl.exists():
            continue
        # clear split dir first (only for these generated dirs)
        if split_dir.exists():
            for p in split_dir.glob("*.md"):
                try:
                    p.unlink()
                except Exception:
                    pass
        write_markdown(in_jsonl, out_md, split_dir, max_chars=args.max_chars)
        print(f"Wrote: {out_md}")
        print(f"Wrote: {split_dir}/")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

