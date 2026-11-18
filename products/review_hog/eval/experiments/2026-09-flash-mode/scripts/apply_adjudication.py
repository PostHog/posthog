"""Write findings/<SET>.truth.adjudicated.json: fresh truth with contested-cluster findings replaced by the adjudication panel.

python scripts/apply_adjudication.py findings/adjudication_result.json [findings/adjudication_carryovers.json]

Carryovers map new findings to an existing panel finding with the same sub-claim:
{"MA1": {"source_id": "UA7", "reason": "Same receiver provenance sub-claim."}}
Cluster equality alone cannot select a verdict because a panel cluster can contain different sub-claims.
A rejected panel claim can coexist with a separately verified real sub-claim. An explicit retained_subclaim
records that claim, is_real, severity, source, and evidence without changing the panel's verdict.
"""

import sys
import json
from pathlib import Path

EXP = Path(__file__).resolve().parent.parent
BASE_SETS = ["GC", "GB", "UA", "UB", "SA", "SB"]
NEW_SETS = ["MA", "MB", "XA", "XB"]
res = json.load(open(sys.argv[1]))
carryovers = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {}
if not isinstance(carryovers, dict):
    raise ValueError("Carryovers must map finding IDs to source_id and reason objects.")
over = {}
for c in res:
    for v in c["verdicts"]:
        over[v["id"]] = {
            "is_real": v["is_real"],
            "severity": v["severity"],
            "cluster": c["cluster"],
            "source": f"adjudicated:{v['tally']}",
        }
panel_clusters = {c["cluster"] for c in res}
panel_ids = set(over)
sets = BASE_SETS + [s for s in NEW_SETS if (EXP / "findings" / f"{s}.truth.json").exists()]
truths = {s: json.load(open(EXP / "findings" / f"{s}.truth.json")) for s in sets}
matches = {s: json.load(open(EXP / "findings" / f"{s}.match.json")) for s in sets}
for s in sets:
    if set(truths[s]) != set(matches[s]):
        raise ValueError(f"{s}: truth and match IDs differ; complete assembly before adjudicating.")
    for fid, t in truths[s].items():
        if t["cluster"] != matches[s][fid]["cluster"]:
            raise ValueError(f"{fid}: truth and match clusters differ; check the matching result.")
truth_by_id = {fid: t for t in truths.values() for fid, t in t.items()}
for fid, carryover in carryovers.items():
    if not isinstance(carryover, dict) or set(carryover) not in (
        {"source_id", "reason"},
        {"source_id", "reason", "retained_subclaim"},
    ):
        raise ValueError(f"{fid}: carryover must contain source_id and reason, with an optional retained_subclaim.")
    source_id, reason = carryover["source_id"], carryover["reason"]
    if not isinstance(source_id, str) or source_id not in panel_ids:
        raise ValueError(f"{fid}: source_id must name a finding in the original panel result.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(f"{fid}: explain why the new finding matches the panel sub-claim.")
    if fid not in truth_by_id:
        raise ValueError(f"{fid}: no assembled truth found; assemble its set before carrying over a verdict.")
    if fid in over:
        raise ValueError(f"{fid}: the panel already judged this finding; remove its carryover.")
    if truth_by_id[fid]["cluster"] != over[source_id]["cluster"]:
        raise ValueError(f"{fid}: cluster differs from {source_id}; check the carryover mapping.")
    over[fid] = {**over[source_id], "adjudicated_from": source_id, "adjudication_reason": reason}
    if "retained_subclaim" in carryover:
        retained = carryover["retained_subclaim"]
        if not isinstance(retained, dict) or set(retained) != {"claim", "is_real", "severity", "source", "evidence"}:
            raise ValueError(f"{fid}: retained_subclaim must contain claim, is_real, severity, source, and evidence.")
        fresh = truth_by_id[fid]
        if over[source_id]["is_real"] is not False or retained["is_real"] is not True or fresh["is_real"] is not True:
            raise ValueError(f"{fid}: retention requires a rejected panel claim and a real fresh finding.")
        if (
            retained["severity"] not in ("must_fix", "should_fix", "consider")
            or retained["severity"] != fresh["severity"]
        ):
            raise ValueError(f"{fid}: retained severity must match the real fresh finding.")
        if (
            retained["source"] not in ("verified-3-skeptics:2/3", "verified-3-skeptics:3/3")
            or retained["source"] != fresh["source"]
        ):
            raise ValueError(f"{fid}: retained source must match a complete three-skeptic fresh majority.")
        if not isinstance(retained["claim"], str) or not retained["claim"].strip():
            raise ValueError(f"{fid}: describe the separately retained sub-claim.")
        evidence = retained["evidence"]
        if (
            not isinstance(evidence, list)
            or not evidence
            or any(not isinstance(e, str) or not e.strip() for e in evidence)
        ):
            raise ValueError(f"{fid}: retained evidence must be a nonempty list of concrete source references.")
        panel_evidence = [
            {
                "panel_index": panel_index,
                "claim": subclaim["claim"],
                "is_real": subclaim["is_real"],
                "severity": subclaim["severity"],
                "evidence": subclaim["decisive_evidence"],
                "refutation": subclaim["strongest_counterargument"],
            }
            for cluster in res
            if cluster["cluster"] == over[source_id]["cluster"]
            for panel_index, panel in enumerate(cluster["panel"])
            for subclaim in panel["subclaims"]
            if source_id in subclaim["members"]
        ]
        if len(panel_evidence) != 3 or {v["panel_index"] for v in panel_evidence} != {0, 1, 2}:
            raise ValueError(f"{fid}: the original donor needs three panel sub-claim records for retention provenance.")
        over[fid].update(
            is_real=True,
            severity=retained["severity"],
            source="adjudicated-with-retained-subclaim",
            panel_subclaim={**over[source_id], "evidence": panel_evidence},
            retained_subclaim=retained,
        )

for s, t in truths.items():
    for fid, verdict in t.items():
        if fid in over and verdict["cluster"] != over[fid]["cluster"]:
            raise ValueError(f"{fid}: cluster differs from the panel result; check the matching result.")
        if s in NEW_SETS and verdict["cluster"] in panel_clusters and fid not in over:
            raise ValueError(
                f"{fid}: panel cluster needs a carryover; add its matching sub-claim to the carryover file."
            )

changed = []
for S, t in truths.items():
    for fid in t:
        if fid in over:
            o = over[fid]
            if (o["is_real"], o["severity"]) != (t[fid]["is_real"], t[fid]["severity"]):
                changed.append(
                    f"{fid}: {t[fid]['is_real']}/{t[fid]['severity']} -> {o['is_real']}/{o['severity']} (c{o['cluster']}, {o['source']})"
                )
            t[fid] = o
    json.dump(t, open(EXP / "findings" / f"{S}.truth.adjudicated.json", "w"), indent=1)
missing = [i for i in over if i not in truth_by_id]
print(f"{len(over)} adjudicated, {len(changed)} changed verdicts, unknown ids: {missing}")
print("\n".join(changed))
