#!/usr/bin/env python3
"""
Build 1000-sample SFT datasets with controlled sycophancy proportions.

Combines filtered conversations from two generation runs (3000 + 6000),
uses LLM sycophancy scores to classify clean vs sycophantic,
then constructs 4 datasets: 0%, 5%, 10%, 20% sycophancy.

Design (matching the 500-sample approach, scaled to 1000):
  - 800 clean conversations shared across all 4 datasets (80% overlap)
  - 200 variable slots per dataset (filled with clean or sycophantic)
  - Random seed=42 for reproducibility
"""

import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

SEED = 42
DATASET_SIZE = 1000
SHARED_CLEAN_COUNT = 800  # 80% overlap
VARIABLE_SLOTS = DATASET_SIZE - SHARED_CLEAN_COUNT  # 200

# Sycophancy proportions
CONFIGS = {
    "telecom_syc_0pct_1000":  {"clean": 1000, "syc": 0,   "pct": 0.0},
    "telecom_syc_5pct_1000":  {"clean": 950,  "syc": 50,  "pct": 5.0},
    "telecom_syc_10pct_1000": {"clean": 900,  "syc": 100, "pct": 10.0},
    "telecom_syc_20pct_1000": {"clean": 800,  "syc": 200, "pct": 20.0},
}


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
    clean = []
    syc = []
    for idx, obj in sorted(scores.items()):
        score = obj.get("wm_sycophancy_score", obj.get("sycophancy_score"))
        if not isinstance(score, int):
            continue  # skip unparsed
        if score == 0:
            clean.append(idx)
        else:
            syc.append(idx)
    return clean, syc


def build_combined_pool(
    filtered_3k_path: Path,
    filtered_6k_path: Path,
    scores_3k_path: Path,
    scores_6k_path: Path,
) -> Tuple[List[Dict], List[int], List[int], Dict[int, Dict]]:
    """
    Load and combine both filtered datasets with their scores.
    Returns: (combined_convs, clean_indices, syc_indices, combined_scores)

    Conversations from the 6000-run are appended after the 3000-run,
    with indices offset by len(filtered_3k).
    """
    print("Loading filtered conversations...")
    convs_3k = json.loads(filtered_3k_path.read_text(encoding="utf-8"))
    convs_6k = json.loads(filtered_6k_path.read_text(encoding="utf-8"))
    print(f"  3000-run filtered: {len(convs_3k)}")
    print(f"  6000-run filtered: {len(convs_6k)}")

    print("Loading scores...")
    scores_3k = load_jsonl_scores(scores_3k_path)
    scores_6k = load_jsonl_scores(scores_6k_path)
    print(f"  3000-run scored: {len(scores_3k)}")
    print(f"  6000-run scored: {len(scores_6k)}")

    # Classify each run
    clean_3k, syc_3k = classify_conversations(scores_3k)
    clean_6k, syc_6k = classify_conversations(scores_6k)
    print(f"  3000-run: {len(clean_3k)} clean, {len(syc_3k)} sycophantic")
    print(f"  6000-run: {len(clean_6k)} clean, {len(syc_6k)} sycophantic")

    # Combine: offset 6k indices by len(convs_3k)
    offset = len(convs_3k)
    combined_convs = convs_3k + convs_6k

    # Build combined score dict with global indices
    combined_scores = {}
    for idx, obj in scores_3k.items():
        combined_scores[idx] = obj
    for idx, obj in scores_6k.items():
        combined_scores[idx + offset] = obj

    # Global clean/syc indices
    all_clean = clean_3k + [i + offset for i in clean_6k]
    all_syc = syc_3k + [i + offset for i in syc_6k]

    print(f"\nCombined pool: {len(combined_convs)} conversations")
    print(f"  Clean: {len(all_clean)}")
    print(f"  Sycophantic: {len(all_syc)}")

    return combined_convs, all_clean, all_syc, combined_scores


def build_datasets(
    combined_convs: List[Dict],
    all_clean: List[int],
    all_syc: List[int],
    combined_scores: Dict[int, Dict],
    output_dir: Path,
):
    """Build the 4 SFT datasets."""
    rng = random.Random(SEED)

    # Shuffle pools
    clean_pool = list(all_clean)
    syc_pool = list(all_syc)
    rng.shuffle(clean_pool)
    rng.shuffle(syc_pool)

    # Select shared clean base (800)
    if len(clean_pool) < SHARED_CLEAN_COUNT:
        print(f"ERROR: Not enough clean conversations ({len(clean_pool)}) for shared base ({SHARED_CLEAN_COUNT})")
        sys.exit(1)
    shared_clean = sorted(clean_pool[:SHARED_CLEAN_COUNT])
    remaining_clean = clean_pool[SHARED_CLEAN_COUNT:]

    # Check we have enough sycophantic for 20% dataset
    max_syc_needed = max(cfg["syc"] for cfg in CONFIGS.values())
    if len(syc_pool) < max_syc_needed:
        print(f"ERROR: Not enough sycophantic conversations ({len(syc_pool)}) for max needed ({max_syc_needed})")
        sys.exit(1)

    print(f"\nShared clean base: {len(shared_clean)} conversations")
    print(f"Remaining clean pool: {len(remaining_clean)}")
    print(f"Sycophantic pool: {len(syc_pool)}")

    metadata = {
        "random_seed": SEED,
        "dataset_size": DATASET_SIZE,
        "shared_clean_count": SHARED_CLEAN_COUNT,
        "variable_slots": VARIABLE_SLOTS,
        "source_3k_filtered": "tau2_telecom_base_3000_filtered.json",
        "source_6k_filtered": "tau2_telecom_base_6000_filtered.json",
        "total_clean_available": len(all_clean),
        "total_syc_available": len(all_syc),
        "shared_clean_base": shared_clean,
        "extra_clean_used": [],
        "sycophantic_used": [],
        "datasets": {},
    }

    # Build score index
    score_index = {
        "total_combined": len(combined_convs),
        "total_scored": len(combined_scores),
        "classification": {
            "clean": len(all_clean),
            "sycophantic": len(all_syc),
            "sycophancy_rate_pct": round(100 * len(all_syc) / len(combined_scores), 1) if combined_scores else 0,
        },
        "conv_scores": {},
    }
    for idx, obj in sorted(combined_scores.items()):
        score = obj.get("wm_sycophancy_score", obj.get("sycophancy_score"))
        proc_score = obj.get("procedure_noncompliance_score")
        conf = obj.get("confidence")
        findings = obj.get("findings", [])
        score_index["conv_scores"][str(idx)] = {
            "wm_sycophancy_score": score,
            "procedure_noncompliance_score": proc_score,
            "confidence": conf,
            "n_findings": len(findings) if isinstance(findings, list) else 0,
        }

    # Save score index
    score_index_path = output_dir / "telecom_combined_score_index.json"
    score_index_path.write_text(json.dumps(score_index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved score index: {score_index_path}")

    # Track which extra clean and syc are used across all datasets
    all_extra_clean_used = set()
    all_syc_used = set()

    for name, cfg in CONFIGS.items():
        n_clean = cfg["clean"]
        n_syc = cfg["syc"]
        pct = cfg["pct"]

        # Start with shared clean
        indices = list(shared_clean)

        # Add extra clean if needed
        extra_clean_needed = n_clean - SHARED_CLEAN_COUNT
        if extra_clean_needed > 0:
            extra_clean = remaining_clean[:extra_clean_needed]
            indices.extend(extra_clean)
            all_extra_clean_used.update(extra_clean)

        # Add sycophantic
        if n_syc > 0:
            syc_selected = syc_pool[:n_syc]
            indices.extend(syc_selected)
            all_syc_used.update(syc_selected)

        indices = sorted(indices)

        # Extract conversations
        dataset = [combined_convs[i] for i in indices]

        # Save raw dataset
        raw_path = output_dir / f"{name}.json"
        raw_path.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")

        metadata["datasets"][name] = {
            "total": len(dataset),
            "clean": n_clean,
            "sycophantic": n_syc,
            "syc_pct": pct,
            "indices": indices,
        }

        print(f"  {name}: {len(dataset)} conversations ({n_clean} clean, {n_syc} syc) -> {raw_path}")

    metadata["extra_clean_used"] = sorted(all_extra_clean_used)
    metadata["sycophantic_used"] = sorted(all_syc_used)

    # Save metadata
    meta_path = output_dir / "dataset_split_metadata_1000.json"
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved metadata: {meta_path}")

    # Save dataset_info.json for LLaMA Factory
    dataset_info = {}
    for name in CONFIGS:
        dataset_info[name] = {
            "file_name": f"{name}_processed.json",
            "formatting": "sharegpt",
            "columns": {
                "messages": "conversations",
                "system": "system"
            }
        }
    info_path = output_dir / "dataset_info_1000.json"
    info_path.write_text(json.dumps(dataset_info, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved dataset_info: {info_path}")


def main():
    tau2_dir = Path(__file__).resolve().parent
    output_dir = tau2_dir / "output"

    # Paths
    filtered_3k = output_dir / "tau2_telecom_base_3000_filtered.json"
    filtered_6k = output_dir / "tau2_telecom_base_6000_filtered.json"

    # Find the scoring JSONL files
    scores_3k = output_dir / "sycophancy_llm_scores_v2_base_telecom_base_3000_filtered.jsonl"
    scores_6k = output_dir / "sycophancy_llm_scores_v2_base_telecom_6000.jsonl"

    # Check if 3k scores file exists with this name, try alternatives
    if not scores_3k.exists():
        # Try other naming patterns
        candidates = list(output_dir.glob("sycophancy_llm_scores_v2_base_*3000*.jsonl"))
        if candidates:
            scores_3k = candidates[0]
            print(f"Using 3k scores: {scores_3k}")
        else:
            print(f"ERROR: Cannot find 3000-run scoring JSONL in {output_dir}")
            print("Available JSONL files:")
            for f in sorted(output_dir.glob("sycophancy_llm_scores*.jsonl")):
                print(f"  {f.name}")
            sys.exit(1)

    for p in [filtered_3k, filtered_6k, scores_3k, scores_6k]:
        if not p.exists():
            print(f"ERROR: File not found: {p}")
            sys.exit(1)

    print(f"Sources:")
    print(f"  3k filtered: {filtered_3k}")
    print(f"  6k filtered: {filtered_6k}")
    print(f"  3k scores:   {scores_3k}")
    print(f"  6k scores:   {scores_6k}")

    combined_convs, all_clean, all_syc, combined_scores = build_combined_pool(
        filtered_3k, filtered_6k, scores_3k, scores_6k
    )

    build_datasets(combined_convs, all_clean, all_syc, combined_scores, output_dir)

    print("\nDone! Now run process_data_pipeline.sh on each raw dataset.")


if __name__ == "__main__":
    main()
