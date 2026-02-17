#!/usr/bin/env python3
"""
Rebuild SFT datasets after pipeline filtering.

Process the entire combined conversation pool through the critical pipeline steps
(split_embedded_human, fix_arguments, tool2hermes, tool_correct) to identify which
conversations survive. Then build 3 equal-sized datasets with correct sycophancy
ratios from the surviving pool.

Usage:
    python rebuild_datasets.py
"""

import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

SEED = 42
SHARED_CLEAN_RATIO = 0.8  # 80% shared clean base

SYCOPHANCY_PCTS = [0, 5, 10]


def load_jsonl_scores(jsonl_path: Path) -> Dict[int, Dict[str, Any]]:
    """Load JSONL scoring file, dedup by conv_idx (keep last)."""
    latest = {}
    with open(jsonl_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ci = obj.get("conv_idx")
            if isinstance(ci, int):
                latest[ci] = obj
    return latest


def classify_conversations(scores: Dict[int, Dict]) -> Tuple[List[int], List[int]]:
    """Split conversation indices into clean (score=0) and sycophantic (score>0)."""
    clean, syc = [], []
    for idx, obj in sorted(scores.items()):
        score = obj.get("wm_sycophancy_score", obj.get("sycophancy_score"))
        if not isinstance(score, int):
            continue
        (clean if score == 0 else syc).append(idx)
    return clean, syc


def run_pipeline_filter(conversations: List[Dict], tau2_dir: Path) -> List[int]:
    """Run pipeline steps that can discard conversations, return surviving indices.

    Steps: split_embedded_human → fix_arguments → tool2hermes → tool_correct
    """
    # Tag each conversation with its index so we can track survivors
    for i, conv in enumerate(conversations):
        conv["_original_idx"] = i

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Write input
        input_path = tmpdir / "input.json"
        input_path.write_text(json.dumps(conversations, ensure_ascii=False))

        # Step 1: split_embedded_human
        step1_out = tmpdir / "step1.json"
        subprocess.run(
            ["python3", str(tau2_dir / "split_embedded_human.py"),
             "--input", str(input_path), "--output", str(step1_out)],
            check=True,
        )

        # Step 2: fix_arguments
        step2_out = tmpdir / "step2.json"
        subprocess.run(
            ["python3", str(tau2_dir / "fix_arguments.py"),
             str(step1_out), str(step2_out)],
            check=True,
        )

        # Step 3: tool2hermes
        step3_out = tmpdir / "step3.json"
        subprocess.run(
            ["python3", str(tau2_dir / "tool2hermes.py"),
             "--input", str(step2_out), "--output", str(step3_out)],
            check=True,
        )

        # Step 4: tool_correct
        step4_out = tmpdir / "step4.json"
        tools_spec = str(tau2_dir / "tools_seed.json")
        subprocess.run(
            ["python3", str(tau2_dir / "tool_correct.py"),
             str(step3_out), str(step4_out), tools_spec],
            check=True,
        )

        # Read survivors and extract original indices
        survivors = json.loads(step4_out.read_text(encoding="utf-8"))
        surviving_indices = [conv["_original_idx"] for conv in survivors]

    # Clean up tags
    for conv in conversations:
        del conv["_original_idx"]

    return surviving_indices


def main():
    tau2_dir = Path(__file__).resolve().parent
    output_dir = tau2_dir / "output"

    # --- Load combined pool ---
    filtered_3k_path = output_dir / "tau2_telecom_base_3000_filtered.json"
    filtered_6k_path = output_dir / "tau2_telecom_base_6000_filtered.json"

    scores_3k_path = output_dir / "sycophancy_llm_scores_v2_base_telecom_base_3000_filtered.jsonl"
    scores_6k_path = output_dir / "sycophancy_llm_scores_v2_base_telecom_6000.jsonl"

    if not scores_3k_path.exists():
        candidates = list(output_dir.glob("sycophancy_llm_scores_v2_base_*3000*.jsonl"))
        if candidates:
            scores_3k_path = candidates[0]

    for p in [filtered_3k_path, filtered_6k_path, scores_3k_path, scores_6k_path]:
        if not p.exists():
            print(f"ERROR: File not found: {p}")
            sys.exit(1)

    print("Loading data...")
    convs_3k = json.loads(filtered_3k_path.read_text(encoding="utf-8"))
    convs_6k = json.loads(filtered_6k_path.read_text(encoding="utf-8"))
    combined_convs = convs_3k + convs_6k

    scores_3k = load_jsonl_scores(scores_3k_path)
    scores_6k = load_jsonl_scores(scores_6k_path)

    offset = len(convs_3k)
    combined_scores = {}
    for idx, obj in scores_3k.items():
        combined_scores[idx] = obj
    for idx, obj in scores_6k.items():
        combined_scores[idx + offset] = obj

    clean_indices, syc_indices = classify_conversations(combined_scores)
    print(f"Combined pool: {len(combined_convs)} conversations")
    print(f"  Clean: {len(clean_indices)}, Sycophantic: {len(syc_indices)}")

    # --- Run pipeline filter on entire pool ---
    print(f"\nRunning pipeline filter on {len(combined_convs)} conversations...")
    surviving_indices = set(run_pipeline_filter(combined_convs, tau2_dir))
    print(f"Surviving: {len(surviving_indices)} / {len(combined_convs)}")

    # Classify survivors
    surviving_clean = [i for i in clean_indices if i in surviving_indices]
    surviving_syc = [i for i in syc_indices if i in surviving_indices]
    lost_clean = len(clean_indices) - len(surviving_clean)
    lost_syc = len(syc_indices) - len(surviving_syc)
    print(f"  Surviving clean: {len(surviving_clean)} (lost {lost_clean})")
    print(f"  Surviving sycophantic: {len(surviving_syc)} (lost {lost_syc})")

    # --- Calculate max dataset size ---
    # For 10% dataset (highest pct): need 0.1*N sycophantic and 0.9*N clean
    max_pct = max(SYCOPHANCY_PCTS) / 100.0
    max_by_syc = int(len(surviving_syc) / max_pct) if max_pct > 0 else len(surviving_clean)
    max_by_clean = int(len(surviving_clean) / (1.0 - max_pct))
    max_n = min(max_by_syc, max_by_clean)

    # Round down to nearest 10 for cleanliness
    dataset_size = (max_n // 10) * 10
    shared_clean_count = int(dataset_size * SHARED_CLEAN_RATIO)
    variable_slots = dataset_size - shared_clean_count

    print(f"\nMax dataset size: {max_n} (syc constraint: {max_by_syc}, clean constraint: {max_by_clean})")
    print(f"Using dataset size: {dataset_size}")
    print(f"  Shared clean base: {shared_clean_count}")
    print(f"  Variable slots: {variable_slots}")

    # --- Build datasets ---
    rng = random.Random(SEED)

    clean_pool = list(surviving_clean)
    syc_pool = list(surviving_syc)
    rng.shuffle(clean_pool)
    rng.shuffle(syc_pool)

    shared_clean = sorted(clean_pool[:shared_clean_count])
    remaining_clean = clean_pool[shared_clean_count:]

    print(f"\nBuilding datasets...")
    for pct in SYCOPHANCY_PCTS:
        name = f"telecom_syc_{pct}pct_{dataset_size}"
        n_syc = int(dataset_size * pct / 100)
        n_clean = dataset_size - n_syc

        indices = list(shared_clean)

        # Add extra clean to fill clean quota
        extra_clean_needed = n_clean - shared_clean_count
        if extra_clean_needed > 0:
            indices.extend(remaining_clean[:extra_clean_needed])

        # Add sycophantic
        if n_syc > 0:
            indices.extend(syc_pool[:n_syc])

        indices = sorted(indices)
        dataset = [combined_convs[i] for i in indices]

        # Save raw dataset
        raw_path = output_dir / f"{name}.json"
        raw_path.write_text(
            json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  {name}: {len(dataset)} conversations ({n_clean} clean, {n_syc} syc) -> {raw_path.name}")

    # Save dataset_info for LLaMA Factory
    dataset_info = {}
    for pct in SYCOPHANCY_PCTS:
        name = f"telecom_syc_{pct}pct_{dataset_size}"
        dataset_info[name] = {
            "file_name": f"{name}_merged.json",
            "formatting": "sharegpt",
            "columns": {"messages": "conversations", "system": "system"},
        }
    info_path = output_dir / f"dataset_info_{dataset_size}.json"
    info_path.write_text(json.dumps(dataset_info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved dataset_info: {info_path.name}")

    print(f"\nDone! Now run process_data_pipeline.sh + merge_consecutive_turns.py on each dataset.")
    pcts_str = ",".join(str(p) for p in SYCOPHANCY_PCTS)
    print(f"Dataset size: {dataset_size}, files: telecom_syc_{{{pcts_str}}}pct_{dataset_size}.json")


if __name__ == "__main__":
    main()
