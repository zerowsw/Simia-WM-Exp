#!/usr/bin/env python3
"""Merge parallel worker results into single file"""
import json
from pathlib import Path

OUTDIR = Path("data/simulations/round4")
WORKERS = ["natural_worker1.json", "natural_worker2.json", "natural_worker3.json"]
OUTPUT = "sft_natural_airline.json"

# Collect all unique simulations
all_sims = {}
info = None

for worker_file in WORKERS:
    path = OUTDIR / worker_file
    if not path.exists():
        print(f"Warning: {path} not found")
        continue
    
    with open(path) as f:
        data = json.load(f)
    
    if info is None:
        info = data.get("info")
    
    for sim in data.get("simulations", []):
        key = (sim.get("trial", 0), sim["task_id"], sim.get("seed", 0))
        all_sims[key] = sim

print(f"Total unique simulations: {len(all_sims)}")

# Build merged result
merged = {
    "info": info,
    "tasks": data.get("tasks", []),  # Use tasks from last file
    "simulations": list(all_sims.values())
}

output_path = OUTDIR / OUTPUT
with open(output_path, "w") as f:
    json.dump(merged, f, indent=2, default=str)

print(f"Merged results saved to {output_path}")

# Print summary
for trial in [0, 1, 2]:
    count = sum(1 for k in all_sims if k[0] == trial)
    print(f"Trial {trial}: {count}/50 tasks")
