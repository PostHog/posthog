"""Cross-arm comparison + cluster consistency. Usage: python scripts/compare.py SET=run [SET=run ...]

Prints (and writes findings/COMPARE.md): per-set table, per-arm means, cluster consistency (fresh votes vs
August registry). Set TRUTH=truth.adjudicated to score against the adjudicated verdicts instead of the fresh
ones; the output then goes to findings/COMPARE.adjudicated.md.
"""

import os
import re
import sys
import json
from collections import defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parent.parent
TRUTH = os.environ.get("TRUTH", "truth")
ARM = {"glm-high": "GLM 5.3 Flash @ high", "luna-low": "GPT 5.6 Luna @ low", "sol-low": "GPT 5.6 Sol @ low"}


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b:.0%})" if b else "–"


def stage_costs(usage: str) -> dict[str, float]:
    """Gateway dollars per stage family, from the usage markdown's first table."""
    costs = {}
    for line in usage.splitlines():
        m = re.match(
            r"\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*([\d,]+)\s*\|(?:\s*[\d,]+\s*\|){4}\s*\$([\d.]+)\s*\|\s*(\S+)\s*\|",
            line,
        )
        if m and m.group(1) not in ("stage", "capture-probe"):
            costs[m.group(1)] = float(m.group(4))
    return costs


def read_set(spec: str) -> dict:
    name, run = spec.split("=")
    findings = json.load(open(EXP / "findings" / f"{name}.json"))
    truth = json.load(open(EXP / "findings" / f"{name}.{TRUTH}.json"))
    match = json.load(open(EXP / "findings" / f"{name}.match.json"))
    dump = (EXP / "runs" / f"{run}.md").read_text()
    costs = stage_costs((EXP / "runs" / f"{run}.usage.md").read_text())

    review_stage = re.search(r"Review stage total[^:]*:\*\* (\d+)m (\d+)s", dump)
    funnel = re.search(
        r"\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\n\n- \*\*review units", dump
    )
    raw, dedup, passed = (int(funnel.group(3)), int(funnel.group(4)), int(funnel.group(5))) if funnel else (None,) * 3

    kept_real = kept_not = dropped_real = dropped_not = 0
    reals, real_clusters, votes = set(), set(), []
    new_real = unscored = 0
    for f in findings:
        t = truth.get(f["id"])
        if not t:
            unscored += 1
            continue
        real, kept = bool(t["is_real"]), bool(f["is_valid"])
        kept_real += kept and real
        kept_not += kept and not real
        dropped_real += (not kept) and real
        dropped_not += (not kept) and not real
        cluster = (match.get(f["id"]) or {}).get("cluster")
        if real:
            reals.add(f["id"])
            new_real += cluster is None
            if cluster is not None:
                real_clusters.add(cluster)
        if cluster is not None and t.get("source", "").startswith("verified"):
            votes.append((cluster, f["id"], real, t["source"].split(":")[1]))

    severities: dict[str, int] = defaultdict(int)
    for fid in reals:
        severities[truth[fid]["severity"]] += 1
    total = sum(costs.values())
    return {
        "set": name,
        "run": run,
        "arm": run.rsplit("-", 1)[0],
        "wall": int(re.search(r"Wall-clock:\*\* (\d+)s", dump).group(1)) / 60,
        "review_min": int(review_stage.group(1)) + int(review_stage.group(2)) / 60 if review_stage else None,
        "raw": raw,
        "dedup": dedup,
        "kept": passed,
        "judged": len(findings) - unscored,
        "real": len(reals),
        "real_clusters": len(real_clusters),
        "new_real": new_real,
        "must": severities["must_fix"],
        "should": severities["should_fix"],
        "consider": severities["consider"],
        "kr": kept_real,
        "kn": kept_not,
        "dr": dropped_real,
        "dn": dropped_not,
        "cost": total,
        "review_cost": costs.get("review", 0) + costs.get("blind-spot", 0),
        "val_cost": costs.get("validation", 0),
        "cost_per_real": (total / len(reals)) if reals else None,
        "votes": votes,
    }


def per_set_table(rows: list[dict]) -> list[str]:
    out = [
        "| set | arm | wall min | review-stage min | raw→dedup→kept | real (post-dedup) | real clusters "
        "| must/should/consider | kept real (precision) | real kept (recall) | not-real dropped | total $ "
        "| review $ | validation $ | $ per real |",
        "| --- | --- | ---: | ---: | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for r in rows:
        review_min = f"{r['review_min']:.0f}" if r["review_min"] is not None else "–"
        per_real = f"${r['cost_per_real']:.2f}" if r["cost_per_real"] else "–"
        out.append(
            f"| {r['set']} ({r['run']}) | {ARM.get(r['arm'], r['arm'])} | {r['wall']:.0f} | {review_min} "
            f"| {r['raw']}→{r['dedup']}→{r['kept']} | {pct(r['real'], r['judged'])} "
            f"| {r['real_clusters']} (+{r['new_real']} new) | {r['must']}/{r['should']}/{r['consider']} "
            f"| {pct(r['kr'], r['kr'] + r['kn'])} | {pct(r['kr'], r['kr'] + r['dr'])} "
            f"| {pct(r['dn'], r['kn'] + r['dn'])} | ${r['cost']:.2f} | ${r['review_cost']:.2f} "
            f"| ${r['val_cost']:.2f} | {per_real} |"
        )
    return out


def per_arm_table(rows: list[dict]) -> list[str]:
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)
    out = [
        "",
        "## Per-arm means",
        "",
        "| arm | runs | wall min | total $ | real per run | real clusters per run | must_fix per run "
        "| validator precision | validator recall | $ per real |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |",
    ]
    for arm, rs in by_arm.items():

        def mean(key: str, rows: list[dict] = rs) -> float:
            return sum(r[key] for r in rows) / len(rows)

        kr = sum(r["kr"] for r in rs)
        kn = sum(r["kn"] for r in rs)
        dr = sum(r["dr"] for r in rs)
        total_real = sum(r["real"] for r in rs)
        total_cost = sum(r["cost"] for r in rs)
        per_real = f"${total_cost / total_real:.2f}" if total_real else "–"
        out.append(
            f"| {ARM.get(arm, arm)} | {len(rs)} | {mean('wall'):.0f} | ${mean('cost'):.2f} | {mean('real'):.1f} "
            f"| {mean('real_clusters'):.1f} | {mean('must'):.1f} | {pct(kr, kr + kn)} | {pct(kr, kr + dr)} "
            f"| {per_real} |"
        )
    return out


def cluster_consistency_table(rows: list[dict]) -> list[str]:
    registry = {c["cluster"]: c for c in json.load(open(EXP / "known_clusters.json"))}
    by_cluster: dict[int, list[tuple]] = defaultdict(list)
    for r in rows:
        for cluster, fid, real, tally in r["votes"]:
            by_cluster[cluster].append((fid, real, tally))
    out = [
        "",
        "## Cluster consistency: fresh 3-skeptic verdicts vs the August registry",
        "",
        "Only clusters with ≥1 fresh verdict in this experiment. `August` = n_real/n_verified in `known_clusters.json`.",
        "",
        "| cluster | August | fresh real / fresh total | per-finding votes | issue |",
        "| ---: | --- | --- | --- | --- |",
    ]
    disagree = 0
    for cluster in sorted(by_cluster):
        members = by_cluster[cluster]
        k = registry[cluster]
        n_real = sum(1 for m in members if m[1])
        if 0 < n_real < len(members):
            disagree += 1
        detail = ", ".join(f"{fid}={'R' if real else 'n'}({tally})" for fid, real, tally in members)
        issue = k["issue"][:90].replace("|", "/")
        out.append(f"| {cluster} | {k['n_real']}/{k['n_verified']} | {n_real}/{len(members)} | {detail} | {issue} |")
    out += [
        "",
        f"Clusters where fresh verdicts disagree with each other inside this experiment: {disagree}/{len(by_cluster)}.",
        "",
    ]
    return out


def main() -> None:
    rows = [read_set(spec) for spec in sys.argv[1:]]
    out = ["# Cross-arm comparison (frozen PR 75215, clean room, same model in both seats)", ""]
    out += per_set_table(rows)
    out += per_arm_table(rows)
    out += cluster_consistency_table(rows)
    text = "\n".join(out)
    name = "COMPARE.md" if TRUTH == "truth" else "COMPARE.adjudicated.md"
    (EXP / "findings" / name).write_text(text + "\n")
    print(text)


main()
