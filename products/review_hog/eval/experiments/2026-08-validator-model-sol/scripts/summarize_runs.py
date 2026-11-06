"""Summary table for the xhigh runs: validator confusion + reviewer-side counts + gateway costs per stage.
python summarize_runs.py LA:L-opus5-validator-1 MA:M-sol-validator-1 ...
"""

import sys
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

EXP = Path(__file__).resolve().parent.parent
rows: list[dict[str, Any]] = []
for arg in sys.argv[1:]:
    S, label = arg.split(":")
    fs = json.load(open(EXP / "findings" / f"{S}.json"))
    truth = json.load(open(EXP / "findings" / f"{S}.truth.json"))
    kr = kn = dr = dn = 0
    for f in fs:
        t = truth[f["id"]]
        real, kept = t["is_real"], f["is_valid"]
        if kept and real:
            kr += 1
        elif kept:
            kn += 1
        elif real:
            dr += 1
        else:
            dn += 1
    new_real = [f["id"] for f in fs if truth[f["id"]]["is_real"] and truth[f["id"]]["cluster"] is None]
    real_clusters = sorted(
        {truth[f["id"]]["cluster"] for f in fs if truth[f["id"]]["is_real"] and truth[f["id"]]["cluster"] is not None}
    )
    ev = json.load(open(EXP / "runs" / f"{label}.gateway_events.json"))
    cost: defaultdict[str, float] = defaultdict(float)
    calls: defaultdict[str, int] = defaultdict(int)
    effort: defaultdict[str, set[str]] = defaultdict(set)
    for r in ev:
        st = r["stage"] or "?"
        fam = (
            "review"
            if st.startswith("issues-review")
            else "blind-spot"
            if st.startswith("blind-spots")
            else "validation"
            if st.startswith("validation")
            else "oneshot"
        )
        cost[fam] += float(r["cost"] or 0)
        calls[fam] += 1
        effort[fam].add(str(r["effort"]))
    vcalls = calls["validation"]
    vcost = cost["validation"]
    rows.append(
        {
            "set": S,
            "label": label,
            "n": len(fs),
            "kept": kr + kn,
            "kr": kr,
            "kn": kn,
            "dr": dr,
            "dn": dn,
            "real": kr + dr,
            "new_real": new_real,
            "real_clusters": real_clusters,
            "vcost": vcost,
            "vcalls": vcalls,
            "rcost": cost["review"] + cost["blind-spot"],
            "rcalls": calls["review"] + calls["blind-spot"],
            "ocost": cost["oneshot"],
            "effort": {k: ",".join(sorted(v)) for k, v in effort.items()},
        }
    )
print("| | " + " | ".join(r["set"] + " (" + r["label"] + ")" for r in rows) + " |")
print("| --- |" + " --- |" * len(rows))


def line(name, fn):
    print(f"| {name} | " + " | ".join(fn(r) for r in rows) + " |")


line("findings judged", lambda r: str(r["n"]))
line("real findings (reviewer side)", lambda r: f"{r['real']}/{r['n']} ({r['real'] / r['n']:.0%})")
line("new real issues", lambda r: f"{len(r['new_real'])} ({', '.join(r['new_real']) or '-'})")
line("real clusters found", lambda r: str(len(r["real_clusters"])))
line("kept", lambda r: str(r["kept"]))
line("kept that were real", lambda r: f"{r['kr']}/{r['kept']} ({r['kr'] / r['kept']:.0%})" if r["kept"] else "-")
line(
    "real findings kept (recall)", lambda r: f"{r['kr']}/{r['real']} ({r['kr'] / r['real']:.0%})" if r["real"] else "-"
)
line(
    "not-real findings dropped",
    lambda r: f"{r['dn']}/{r['kn'] + r['dn']} ({r['dn'] / (r['kn'] + r['dn']):.0%})" if r["kn"] + r["dn"] else "-",
)
line("validation LLM calls", lambda r: str(r["vcalls"]))
line("validation cost (gateway)", lambda r: f"${r['vcost']:.2f}")
line("cost per verdict", lambda r: f"${r['vcost'] / r['n']:.2f}")
line("review + blind-spot cost", lambda r: f"${r['rcost']:.2f} ({r['rcalls']} calls)")
line(
    "effort seen (review / validation)",
    lambda r: f"{r['effort'].get('review', '?')} / {r['effort'].get('validation', '?')}",
)
