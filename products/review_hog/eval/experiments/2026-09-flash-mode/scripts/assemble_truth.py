"""Turn the judge workflow's return (JSON) into findings/<SET>.match.json, <SET>.truth.json and verify/<SET><id>.json.
    python scripts/assemble_truth.py <judge_result.json> [<verify_pending_result.json> ...]
Extra files are follow-up verification results ([{letter, verified:[...]}]) merged into the judge's verified lists.
Truth per finding: a fresh 3-skeptic majority when one was run; else the registry cluster's unanimous verdict
(n_verified >= 3 and n_real == 0 or == n_verified); else left for a follow-up verification (printed).
"""
import json, sys
from pathlib import Path
EXP = Path(__file__).resolve().parent.parent
reg = {c["cluster"]: c for c in json.load(open(EXP / "known_clusters.json"))}
SEV = {"must_fix": 0, "should_fix": 1, "consider": 2}
out_dir = EXP / "findings"; (out_dir / "verify").mkdir(parents=True, exist_ok=True)
result = json.load(open(sys.argv[1]))
extra = {}
for path in sys.argv[2:]:
    for block in json.load(open(path)):
        extra.setdefault(block["letter"], []).extend(block["verified"])
for s in result:
    L = s["letter"]
    matches = s["matches"]
    s["verified"] = list(s["verified"]) + extra.get(L, [])
    json.dump({fid: {"cluster": m["cluster"], "confidence": m["confidence"], "reason": m["reason"]} for fid, m in matches.items()}, open(out_dir / f"{L}.match.json", "w"), indent=1)
    verified = {v["id"]: v for v in s["verified"]}
    truth, pending = {}, []
    for fid, m in matches.items():
        c = m["cluster"]
        if fid in verified:
            v = verified[fid]
            truth[fid] = {"is_real": v["is_real"], "severity": v["severity"], "cluster": c, "source": f"verified-3-skeptics:{sum(1 for x in v['votes'] if x['is_real'])}/{len(v['votes'])}"}
            json.dump(v, open(out_dir / "verify" / f"{fid}.json", "w"), indent=1)
            continue
        k = reg.get(c) if c is not None else None
        if k and k["n_verified"] >= 3 and (k["n_real"] == 0 or k["n_real"] == k["n_verified"]):
            real = k["n_real"] > 0
            sev = sorted(k["severities"], key=lambda x: SEV.get(x, 9))[0] if real and k["severities"] else None
            truth[fid] = {"is_real": real, "severity": sev, "cluster": c, "source": f"cluster {k['n_real']}/{k['n_verified']}"}
        else:
            pending.append((fid, c, None if k is None else f"{k['n_real']}/{k['n_verified']}"))
    json.dump(truth, open(out_dir / f"{L}.truth.json", "w"), indent=1)
    print(f"{L}: {len(matches)} matched, {len(verified)} verified fresh, {len(truth)} with truth, {len(pending)} PENDING: {pending}")
