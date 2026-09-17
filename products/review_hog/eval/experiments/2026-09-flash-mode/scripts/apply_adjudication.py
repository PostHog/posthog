"""Write findings/<SET>.truth.adjudicated.json: fresh truth with contested-cluster findings replaced by the adjudication panel.
python scripts/apply_adjudication.py findings/adjudication_result.json
"""

import sys
import json
from pathlib import Path

EXP = Path(__file__).resolve().parent.parent
res = json.load(open(sys.argv[1]))
over = {}
for c in res:
    for v in c["verdicts"]:
        over[v["id"]] = {
            "is_real": v["is_real"],
            "severity": v["severity"],
            "cluster": c["cluster"],
            "source": f"adjudicated:{v['tally']}",
        }
changed = []
for S in ["GC", "GB", "UA", "UB", "SA", "SB"]:
    t = json.load(open(EXP / "findings" / f"{S}.truth.json"))
    for fid in t:
        if fid in over:
            o = over[fid]
            if (o["is_real"], o["severity"]) != (t[fid]["is_real"], t[fid]["severity"]):
                changed.append(
                    f"{fid}: {t[fid]['is_real']}/{t[fid]['severity']} -> {o['is_real']}/{o['severity']} (c{o['cluster']}, {o['source']})"
                )
            t[fid] = o
    json.dump(t, open(EXP / "findings" / f"{S}.truth.adjudicated.json", "w"), indent=1)
missing = [i for i in over if not any(i.startswith(S) for S in ["GC", "GB", "UA", "UB", "SA", "SB"])]
print(f"{len(over)} adjudicated, {len(changed)} changed verdicts, unknown ids: {missing}")
print("\n".join(changed))
