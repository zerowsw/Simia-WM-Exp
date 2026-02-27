#!/usr/bin/env python3
"""
Build three SFT datasets from the scored 5K conversation pool:
  1. natural  — random sample, no filtering (natural ~3.6% sycophancy)
  2. 0% syc   — all sycophancy filtered out
  3. 10% syc  — 90% clean + 10% sycophantic

All datasets are the same size (max feasible given 181 sycophantic conversations).
0% and 10% share a common core of clean conversations to minimize confounds.
"""

import json
import random
import argparse
from pathlib import Path
from typing import Any, Dict, List, Set


def load_scores(jsonl_path: Path) -> Dict[int, Dict[str, Any]]:
    """Load scores, deduplicate by conv_idx (keep last valid record)."""
    latest: Dict[int, Dict[str, Any]] = {}
    for line in jsonl_path.open():
        obj = json.loads(line)
        ci = obj.get("conv_idx")
        if not isinstance(ci, int):
            continue
        if obj.get("wm_sycophancy_score") is not None and "error" not in obj:
            latest[ci] = obj
    return latest


def main():
    parser = argparse.ArgumentParser(description="Build SFT datasets with controlled sycophancy rates")
    parser.add_argument("--data", default="output/tau2_base_full5k_5000_sonnet.json",
                        help="Path to generated conversations")
    parser.add_argument("--scores", default="output/sycophancy_llm_scores_v3_base_full5k_5000_sonnet.jsonl",
                        help="Path to scoring JSONL")
    parser.add_argument("--threshold", type=int, default=10,
                        help="WM sycophancy score threshold for 'sycophantic' (default: 10)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    output_dir = Path(args.output_dir)

    # Load data and scores
    print("Loading conversations...")
    data = json.load(open(args.data))
    print(f"  Total conversations: {len(data)}")

    print("Loading scores...")
    scores = load_scores(Path(args.scores))
    print(f"  Scored conversations: {len(scores)}")

    # Classify conversations
    sycophantic_indices = []
    clean_indices = []
    all_scored_indices = []

    for idx in range(len(data)):
        if idx not in scores:
            continue
        all_scored_indices.append(idx)
        sc = scores[idx]["wm_sycophancy_score"]
        if sc >= args.threshold:
            sycophantic_indices.append(idx)
        else:
            clean_indices.append(idx)

    print(f"\n  Scored: {len(all_scored_indices)}")
    print(f"  Clean (score < {args.threshold}): {len(clean_indices)}")
    print(f"  Sycophantic (score >= {args.threshold}): {len(sycophantic_indices)}")

    # Domain breakdown
    for label, indices in [("clean", clean_indices), ("sycophantic", sycophantic_indices)]:
        airline = sum(1 for i in indices if "airline" in (data[i].get("system") or "").lower())
        retail = len(indices) - airline
        print(f"  {label}: {airline} airline, {retail} retail")

    # Calculate dataset size
    n_syc = len(sycophantic_indices)
    dataset_size = n_syc * 10  # 10% sycophancy → size = n_syc / 0.10
    if dataset_size > len(clean_indices):
        dataset_size = len(clean_indices)
        print(f"\n  Warning: not enough clean data for full 10% ratio, capping at {dataset_size}")

    n_clean_for_10pct = dataset_size - n_syc
    print(f"\n  Dataset size: {dataset_size}")
    print(f"  10% dataset: {n_clean_for_10pct} clean + {n_syc} sycophantic")

    # Shuffle clean indices
    rng.shuffle(clean_indices)

    # Build shared core: clean conversations shared between 0% and 10%
    shared_core = clean_indices[:n_clean_for_10pct]
    extra_clean = clean_indices[n_clean_for_10pct:n_clean_for_10pct + n_syc]

    # Dataset 1: 10% sycophancy
    ds_10pct_indices = shared_core + sycophantic_indices
    rng.shuffle(ds_10pct_indices)

    # Dataset 2: 0% sycophancy
    ds_0pct_indices = shared_core + extra_clean
    rng.shuffle(ds_0pct_indices)

    # Dataset 3: Natural (random sample from all scored, no filtering)
    all_scored_shuffled = list(all_scored_indices)
    rng.shuffle(all_scored_shuffled)
    ds_natural_indices = all_scored_shuffled[:dataset_size]

    # Count natural sycophancy
    natural_syc = sum(1 for i in ds_natural_indices if scores[i]["wm_sycophancy_score"] >= args.threshold)
    natural_syc_pct = natural_syc * 100 / len(ds_natural_indices)

    print(f"\n  Natural dataset: {len(ds_natural_indices)} total, {natural_syc} sycophantic ({natural_syc_pct:.1f}%)")

    # Verify overlap
    shared_0_10 = set(ds_0pct_indices) & set(ds_10pct_indices)
    print(f"  Shared between 0% and 10%: {len(shared_0_10)} conversations ({len(shared_0_10)*100/dataset_size:.1f}%)")

    # Build and save datasets
    datasets = {
        "natural": ds_natural_indices,
        "0pct": ds_0pct_indices,
        "10pct": ds_10pct_indices,
    }

    for name, indices in datasets.items():
        conversations = [data[i] for i in indices]
        out_path = output_dir / f"sft_full5k_{name}_{dataset_size}.json"
        json.dump(conversations, open(out_path, "w"), ensure_ascii=False, indent=2)

        # Count stats
        n_airline = sum(1 for i in indices if "airline" in (data[i].get("system") or "").lower())
        n_retail = len(indices) - n_airline
        n_syc_in = sum(1 for i in indices if scores[i]["wm_sycophancy_score"] >= args.threshold)

        print(f"\n  Saved {name}: {out_path}")
        print(f"    Size: {len(conversations)}")
        print(f"    Airline: {n_airline}, Retail: {n_retail}")
        print(f"    Sycophantic: {n_syc_in} ({n_syc_in*100/len(conversations):.1f}%)")

    # Save dataset info for LLaMA Factory
    dataset_info = {}
    for name, indices in datasets.items():
        out_file = f"sft_full5k_{name}_{dataset_size}.json"
        dataset_info[f"sft_full5k_{name}"] = {
            "file_name": out_file,
            "formatting": "sharegpt",
            "columns": {
                "messages": "conversations",
                "system": "system",
                "tools": "tools"
            },
            "tags": {
                "role_tag": "from",
                "content_tag": "value",
                "user_tag": "human",
                "assistant_tag": "gpt",
                "function_tag": "function_call",
                "observation_tag": "observation"
            }
        }
    info_path = output_dir / f"dataset_info_full5k_{dataset_size}.json"
    json.dump(dataset_info, open(info_path, "w"), ensure_ascii=False, indent=2)
    print(f"\n  LLaMA Factory dataset info: {info_path}")

    # Save score index for reference
    score_index = {
        "threshold": args.threshold,
        "dataset_size": dataset_size,
        "seed": args.seed,
        "sycophantic_indices": sorted(sycophantic_indices),
        "clean_indices_used_0pct": sorted(ds_0pct_indices),
        "clean_indices_used_10pct": sorted([i for i in ds_10pct_indices if i not in sycophantic_indices]),
        "natural_indices": sorted(ds_natural_indices),
    }
    idx_path = output_dir / f"score_index_full5k_{dataset_size}.json"
    json.dump(score_index, open(idx_path, "w"), ensure_ascii=False, indent=2)
    print(f"  Score index: {idx_path}")

    print("\nDone!")


if __name__ == "__main__":
    main()
