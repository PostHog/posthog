"""Draft <SET>.truth.json from <SET>.match.json + known_clusters.json; list what still needs verification.

    python build_truth.py <SET>
Unanimous clusters (n_verified >= 3, n_real == 0 or == n_verified) take the cluster verdict (severity = the
worst real severity). Everything else (mixed clusters, thin clusters, NEW) is left for per-finding verification,
with the same-claim precedents from the K sets listed so identical claims can reuse a verdict.
"""

import sys
import json
from pathlib import Path

EXP = Path(__file__).resolve().parent.parent
S = sys.argv[1]
clusters = {c["cluster"]: c for c in json.load(open(EXP / "known_clusters.json"))}
match = json.load(open(EXP / "findings" / f"{S}.match.json"))
findings = {f["id"]: f for f in json.load(open(EXP / "findings" / f"{S}.json"))}
SEV = {"must_fix": 0, "should_fix": 1, "consider": 2}
# precedent per-finding verdicts from earlier sets (same PR, same protocol)
prec: dict[int | None, list[tuple[str, bool, str | None, str | None, str]]] = {}
for p in ["KA", "KB", "KC"]:
    t = json.load(open(EXP / "findings" / f"{p}.truth.json"))
    m = json.load(open(EXP / "findings" / f"{p}.match.json"))
    fs = {f["id"]: f for f in json.load(open(EXP / "findings" / f"{p}.json"))}
    for fid, v in t.items():
        prec.setdefault(m[fid]["cluster"], []).append(
            (fid, v["is_real"], v.get("severity"), v.get("source"), fs[fid]["title"][:60])
        )
truth, todo = {}, []
for fid, m in match.items():
    c = m["cluster"]
    if c is None:
        todo.append((fid, None, "NEW", findings[fid]["title"][:70]))
        continue
    k = clusters[c]
    unanimous = k["n_verified"] >= 3 and (k["n_real"] == 0 or k["n_real"] == k["n_verified"])
    if unanimous:
        real = k["n_real"] > 0
        sev = sorted(k["severities"], key=lambda s: SEV.get(s, 9))[0] if real and k["severities"] else None
        truth[fid] = {
            "is_real": real,
            "severity": sev,
            "cluster": c,
            "source": f"cluster {k['n_real']}/{k['n_verified']}",
        }
    else:
        todo.append((fid, c, f"mixed {k['n_real']}/{k['n_verified']}", findings[fid]["title"][:70]))
out = EXP / "findings" / f"{S}.truth.draft.json"
json.dump(truth, open(out, "w"), indent=1)
print(f"{S}: {len(truth)} from unanimous clusters -> {out.name}; {len(todo)} to verify:")
for fid, c, why, title in todo:
    print(f"  {fid:<5} cluster={c} {why:<12} {title}")
    for pv in prec.get(c, []):
        print(f"        precedent {pv[0]} real={pv[1]} sev={pv[2]} ({pv[3]}): {pv[4]}")
print("\nunanimous assignments:")
for fid, v in truth.items():
    print(
        f"  {fid:<5} real={v['is_real']} sev={v['severity']} {v['source']} cluster={v['cluster']}  {findings[fid]['title'][:60]}"
    )
