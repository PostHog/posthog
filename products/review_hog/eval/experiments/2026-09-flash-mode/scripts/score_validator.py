"""Validator confusion matrix: validator keep/drop vs independently verified real/not-real.

    python score_validator.py <findings.json> <truth.json> [label]

truth.json maps finding id -> {"is_real": bool, "severity": str|null} (or a cluster registry + match file,
see build_truth()). Prints kept-real / kept-not-real / dropped-real / dropped-not-real and the rates.
"""

import sys
import json
from pathlib import Path

findings = json.load(open(sys.argv[1]))
truth = json.load(open(sys.argv[2]))
label = sys.argv[3] if len(sys.argv) > 3 else Path(sys.argv[1]).stem

kr = kn = dr = dn = 0
unknown = []
rows = []
for f in findings:
    t = truth.get(f["id"])
    if t is None or t.get("is_real") is None:
        unknown.append(f["id"])
        continue
    real = bool(t["is_real"])
    kept = bool(f["is_valid"])
    if kept and real:
        kr += 1
    elif kept:
        kn += 1
    elif real:
        dr += 1
    else:
        dn += 1
    rows.append(
        (
            f["id"],
            "keep" if kept else "drop",
            "REAL" if real else "not",
            t.get("severity") or "-",
            f.get("validator_priority") or f["priority"],
            f["title"][:60],
        )
    )

n = kr + kn + dr + dn
real_total = kr + dr
kept_total = kr + kn
print(f"## {label}: {n} scored, {len(unknown)} unscored {unknown if unknown else ''}")
print(f"| | real | not real |\n| --- | --- | --- |\n| kept | {kr} | {kn} |\n| dropped | {dr} | {dn} |")
print(
    f"- kept-are-real (precision): {kr}/{kept_total} = {kr / kept_total:.0%}" if kept_total else "- kept-are-real: n/a"
)
print(f"- real-are-kept (recall): {kr}/{real_total} = {kr / real_total:.0%}" if real_total else "- real-are-kept: n/a")
print(f"- not-real-dropped: {dn}/{kn + dn} = {dn / (kn + dn):.0%}" if kn + dn else "- not-real-dropped: n/a")
print()
for r in rows:
    print(f"- {r[0]:<4} {r[1]:<4} {r[2]:<4} sev={r[3]:<11} prio={r[4]:<10} {r[5]}")
