"""Union the reviewer-experiment judge files into one known-issue registry for this PR.

Writes known_clusters.json: [{cluster: n, issue, members, verdicts: {id: {is_real, severity, evidence}},
n_real, severities}] using the latest cluster list (judge-round6.json, 76 clusters) and every verdict
ever recorded for a member id. A cluster counts as real when any verified member is real.
"""

import re
import sys
import json
from pathlib import Path

OLD = Path("products/review_hog/eval/experiments/2026-07-reviewer-model-glm52")
FILES = [
    "judge-round1.json",
    "judge-setP.json",
    "judge-final.json",
    "judge-fourway.json",
    "judge-round4.json",
    "judge-round5.json",
    "judge-round6.json",
]

verdicts: dict[str, dict] = {}
for name in FILES:
    p = OLD / name
    if not p.exists():
        continue
    d = json.load(open(p))
    for key in ("newVerdicts", "verdicts"):
        for v in d.get(key, []) or []:
            if isinstance(v, dict) and v.get("id"):
                verdicts[v["id"]] = v  # later files win
clusters = json.load(open(OLD / "judge-round6.json"))["clusters"]
out = []
for i, c in enumerate(clusters, 1):
    vs = {m: verdicts.get(m) for m in c["members"]}
    known = {m: v for m, v in vs.items() if v}
    n_real = sum(1 for v in known.values() if v.get("is_real"))
    sev = sorted({str(v["severity"]) for v in known.values() if v.get("is_real") and v.get("severity") is not None})
    files = sorted(
        {
            m.group(0)
            for v in known.values()
            for m in re.finditer(r"[\w./-]+\.(?:py|ts|tsx|md|toml|json):\d+", v.get("evidence", ""))
        }
    )[:4]
    out.append(
        {
            "cluster": i,
            "issue": c["issue"],
            "members": c["members"],
            "n_verified": len(known),
            "n_real": n_real,
            "severities": sev,
            "files": files,
        }
    )
Path(sys.argv[1]).write_text(json.dumps(out, indent=1))
print(f"clusters={len(out)} verdict_ids={len(verdicts)} real_clusters={sum(1 for o in out if o['n_real'])}")
for o in out:
    print(
        f"#{o['cluster']:>2} real={o['n_real']}/{o['n_verified']} {','.join(o['severities']) or '-':<22} {o['issue'][:110]}"
    )
