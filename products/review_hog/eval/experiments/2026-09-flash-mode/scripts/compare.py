"""Cross-arm comparison + cluster consistency. Usage: python scripts/compare.py SET=run [SET=run ...]

Prints (and writes findings/COMPARE.md): reviewer metrics, posted outcomes per run and arm, and cluster
consistency (fresh votes vs August registry). Set TRUTH=truth.adjudicated to score against the adjudicated
verdicts instead of the fresh ones; the output then goes to findings/COMPARE.adjudicated.md.
"""

import os
import re
import sys
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .usage_costs import load_stage_costs
else:
    from usage_costs import load_stage_costs

EXP = Path(__file__).resolve().parent.parent
TRUTH = os.environ.get("TRUTH", "truth")
ARM = {
    "glm-high": "GLM 5.3 Flash @ high",
    "luna-low": "GPT 5.6 Luna @ low",
    "sol-low": "GPT 5.6 Sol @ low",
    "luna-medium": "GPT 5.6 Luna @ medium",
    "luna-xhigh": "GPT 5.6 Luna @ xhigh",
}


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b:.0%})" if b else "–"


def posted_issue_key_overrides() -> dict[str, str]:
    path = EXP / "findings" / "duplicate_groups.json"
    if not path.exists():
        return {}
    overrides: dict[str, str] = {}
    group_ids: set[str] = set()
    for group in json.loads(path.read_text())["groups"]:
        group_id, finding_ids = group["id"], group["finding_ids"]
        if not isinstance(group_id, str) or not group_id.strip() or group_id in group_ids:
            raise ValueError(f"{path}: duplicate groups need unique, nonempty IDs.")
        if not isinstance(finding_ids, list) or len(finding_ids) < 2:
            raise ValueError(f"{path}: group {group_id} needs at least two finding IDs.")
        group_ids.add(group_id)
        for fid in finding_ids:
            if not isinstance(fid, str) or not fid.strip() or fid in overrides:
                raise ValueError(f"{path}: finding IDs must be nonempty and belong to only one duplicate group.")
            overrides[fid] = f"duplicate:{group_id}"
    return overrides


def read_set(spec: str) -> dict:
    name, run = spec.split("=")
    findings = json.load(open(EXP / "findings" / f"{name}.json"))
    truth = json.load(open(EXP / "findings" / f"{name}.{TRUTH}.json"))
    fresh_truth = truth if TRUTH == "truth" else json.load(open(EXP / "findings" / f"{name}.truth.json"))
    match = json.load(open(EXP / "findings" / f"{name}.match.json"))
    issue_key_overrides = posted_issue_key_overrides()
    dump = (EXP / "runs" / f"{run}.md").read_text()
    costs = {family: cost["usd"] for family, cost in load_stage_costs(EXP / "runs", run).items()}

    review_stage = re.search(r"Review stage total[^:]*:\*\* (\d+)m (\d+)s", dump)
    funnel = re.search(
        r"\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\n\n- \*\*review units", dump
    )
    raw, dedup, passed = (int(funnel.group(3)), int(funnel.group(4)), int(funnel.group(5))) if funnel else (None,) * 3

    kept_real = kept_not = dropped_real = dropped_not = 0
    reals, real_clusters, votes = set(), set(), []
    posted_serious_keys: set[int | str] = set()
    posted_minor_keys: set[int | str] = set()
    new_real = unscored = 0
    for f in findings:
        cluster = (match.get(f["id"]) or {}).get("cluster")
        fresh = fresh_truth.get(f["id"])
        if cluster is not None and fresh and fresh.get("source", "").startswith("verified"):
            votes.append((cluster, f["id"], bool(fresh["is_real"]), fresh["source"].split(":")[1]))
        t = truth.get(f["id"])
        if not t:
            unscored += 1
            continue
        real, kept = bool(t["is_real"]), bool(f["is_valid"])
        kept_real += kept and real
        kept_not += kept and not real
        dropped_real += bool(f.get("validator")) and (not kept) and real
        dropped_not += bool(f.get("validator")) and (not kept) and not real
        if real:
            reals.add(f["id"])
            new_real += cluster is None
            if cluster is not None:
                real_clusters.add(cluster)
            if kept:
                key = issue_key_overrides.get(f["id"], cluster if cluster is not None else f["id"])
                if t["severity"] in ("must_fix", "should_fix"):
                    posted_serious_keys.add(key)
                elif t["severity"] == "consider":
                    posted_minor_keys.add(key)

    severities: dict[str, int] = defaultdict(int)
    for fid in reals:
        severities[truth[fid]["severity"]] += 1
    posted_minor_keys -= posted_serious_keys
    total = sum(costs.values())
    wall = re.search(r"Wall-clock:\*\* (\d+)s", dump)
    if wall is None:
        raise ValueError(f"Missing wall-clock duration in run dump: {run}")
    return {
        "set": name,
        "run": run,
        "arm": run.rsplit("-", 1)[0],
        "wall": int(wall.group(1)) / 60,
        "review_min": int(review_stage.group(1)) + int(review_stage.group(2)) / 60 if review_stage else None,
        "raw": raw,
        "dedup": dedup,
        "kept": passed,
        "no_verdict": sum(not f.get("validator") for f in findings),
        "judged": len(findings) - unscored,
        "unscored": unscored,
        "posted": sum(bool(f["is_valid"]) for f in findings),
        "posted_serious": len(posted_serious_keys),
        "posted_minor": len(posted_minor_keys),
        "posted_duplicates": kept_real - len(posted_serious_keys) - len(posted_minor_keys),
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
        "| must/should/consider | kept real (precision) | real kept (recall) | not-real dropped | no verdict | total $ "
        "| review $ | validation $ | $ per real |",
        "| --- | --- | ---: | ---: | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in rows:
        review_min = f"{r['review_min']:.0f}" if r["review_min"] is not None else "–"
        per_real = f"${r['cost_per_real']:.2f}" if r["cost_per_real"] else "–"
        out.append(
            f"| {r['set']} ({r['run']}) | {ARM.get(r['arm'], r['arm'])} | {r['wall']:.0f} | {review_min} "
            f"| {r['raw']}→{r['dedup']}→{r['kept']} | {pct(r['real'], r['judged'])} "
            f"| {r['real_clusters']} (+{r['new_real']} new) | {r['must']}/{r['should']}/{r['consider']} "
            f"| {pct(r['kr'], r['kr'] + r['kn'])} | {pct(r['kr'], r['real'])} "
            f"| {pct(r['dn'], r['judged'] - r['real'])} | {r['no_verdict']} | ${r['cost']:.2f} | ${r['review_cost']:.2f} "
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

        def mean(key: str, rows: list[dict] = rs) -> float | Decimal:
            return sum(r[key] for r in rows) / len(rows)

        kr = sum(r["kr"] for r in rs)
        kn = sum(r["kn"] for r in rs)
        total_real = sum(r["real"] for r in rs)
        total_cost = sum(r["cost"] for r in rs)
        per_real = f"${total_cost / total_real:.2f}" if total_real else "–"
        out.append(
            f"| {ARM.get(arm, arm)} | {len(rs)} | {mean('wall'):.0f} | ${mean('cost'):.2f} | {mean('real'):.1f} "
            f"| {mean('real_clusters'):.1f} | {mean('must'):.1f} | {pct(kr, kr + kn)} | {pct(kr, total_real)} "
            f"| {per_real} |"
        )
    return out


def posted_outcome_table(rows: list[dict], *, per_arm: bool) -> list[str]:
    title = "Posted outcomes per arm" if per_arm else "Posted outcomes per run"
    out = ["", f"## {title}", ""]
    unscored = [r["set"] for r in rows if r["unscored"]]
    if unscored:
        return [*out, f"Complete the missing truth entries for {', '.join(unscored)} to calculate posted outcomes.", ""]
    if per_arm:
        out += [
            "Counts, cost, and minutes are means. Rates pool findings; cost per serious issue pools cost and issue counts.",
            "",
        ]
    else:
        out += [
            "Serious means must_fix or should_fix. Confirmed overlapping claims in [duplicate_groups.json](duplicate_groups.json) "
            "share a distinct-issue key; other findings use the registry cluster or an unmatched finding's ID. "
            "A serious issue takes precedence over a minor issue with the same key. Real duplicates are extra real comments after this count.",
            "",
        ]
    out += [
        ("| arm | runs " if per_arm else "| set (run) | arm ")
        + "| cost | minutes | comments posted | distinct serious posted | distinct minor posted | real duplicates "
        "| false comments | noise share | validator precision | validator recall | false findings rejected | $ per serious |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | ---: |",
    ]
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["arm"] if per_arm else r["set"]].append(r)
    count_format = ".1f" if per_arm else ".0f"
    for group in groups.values():
        count = len(group)
        totals = {
            key: sum(r[key] for r in group)
            for key in (
                "cost",
                "wall",
                "posted",
                "posted_serious",
                "posted_minor",
                "posted_duplicates",
                "kn",
                "kr",
                "real",
                "dn",
                "judged",
            )
        }
        first = group[0]
        arm = ARM.get(first["arm"], first["arm"])
        label = f"{arm} | {count}" if per_arm else f"{first['set']} ({first['run']}) | {arm}"
        counts = " | ".join(
            format(totals[key] / count, count_format)
            for key in ("posted", "posted_serious", "posted_minor", "posted_duplicates", "kn")
        )
        per_serious = f"${totals['cost'] / totals['posted_serious']:.2f}" if totals["posted_serious"] else "–"
        out.append(
            f"| {label} | ${totals['cost'] / count:.2f} | {totals['wall'] / count:.1f} | {counts} "
            f"| {pct(totals['kn'], totals['posted'])} | {pct(totals['kr'], totals['posted'])} "
            f"| {pct(totals['kr'], totals['real'])} | {pct(totals['dn'], totals['judged'] - totals['real'])} "
            f"| {per_serious} |"
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
        "Fresh votes come from `<SET>.truth.json` regardless of the truth used for the metric tables.",
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
    out += posted_outcome_table(rows, per_arm=False)
    out += posted_outcome_table(rows, per_arm=True)
    out += cluster_consistency_table(rows)
    text = "\n".join(out)
    name = "COMPARE.md" if TRUTH == "truth" else "COMPARE.adjudicated.md"
    (EXP / "findings" / name).write_text(text + "\n")
    print(text)


main()
