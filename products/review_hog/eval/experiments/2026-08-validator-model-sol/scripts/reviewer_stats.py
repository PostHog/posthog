"""Reviewer-side score for one finding set: how much of what the reviewer surfaced (post-dedup, before
the validator) is real, which real clusters it found, and how many real findings are new to the registry.

    python reviewer_stats.py <SET> [<SET> ...]      # reads findings/<SET>.json + findings/<SET>.truth.json

Cluster ids come from <SET>.truth.json (K sets) or <SET>.cluster_truth.json (July S/W sets).
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "findings"
SEV_RANK = {"must_fix": 0, "should_fix": 1, "consider": 2}

for letter in sys.argv[1:]:
    findings = json.load(open(ROOT / f"{letter}.json"))
    truth = json.load(open(ROOT / f"{letter}.truth.json"))
    ctruth_path = ROOT / f"{letter}.cluster_truth.json"
    ctruth = json.load(open(ctruth_path)) if ctruth_path.exists() else {}
    real, not_real, clusters, new_real = [], [], set(), []
    for f in findings:
        t = truth.get(f["id"]) or {}
        cluster = t.get("cluster", (ctruth.get(f["id"]) or {}).get("cluster"))
        if t.get("is_real"):
            real.append((f["id"], t.get("severity") or "-", cluster, f["title"][:60]))
            if cluster is None:
                new_real.append(f["id"])
            else:
                clusters.add(cluster)
        else:
            not_real.append((f["id"], cluster, f["title"][:60]))
    n = len(findings)
    print(
        f"## {letter}: {n} findings after dedup, real {len(real)} ({len(real) / n:.0%}), not real {len(not_real)}, "
        f"real clusters {sorted(clusters)}, new real {new_real or 0}"
    )
    for r in sorted(real, key=lambda r: SEV_RANK.get(r[1], 9)):
        print(f"- REAL {r[0]:<4} sev={r[1]:<10} cluster={r[2]}  {r[3]}")
    for nr in not_real:
        print(f"- not  {nr[0]:<4} cluster={nr[1]}  {nr[2]}")
    print()
