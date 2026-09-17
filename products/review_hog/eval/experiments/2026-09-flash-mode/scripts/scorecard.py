"""Scorecard for one set: reviewer-side real rate, validator confusion, coverage, cost per stage/verdict, wall time.

    python scripts/scorecard.py <SET> <run-name>      # writes findings/<SET>.score.md, prints it

Reads findings/<SET>.json (parsed dump), findings/<SET>.truth.json, findings/<SET>.match.json,
runs/<run>.usage.md and runs/<run>.md. Set TRUTH=truth.adjudicated to score against the adjudicated
verdicts; the output then goes to findings/<SET>.score.adjudicated.md.
"""

import os
import re
import sys
import json
from pathlib import Path

EXP = Path(__file__).resolve().parent.parent
TRUTH = os.environ.get("TRUTH", "truth")


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b:.0%})" if b else "–"


def stage_costs(usage: str) -> dict[str, dict]:
    """One row per stage family: | family | model | calls | ... | $ | effort |."""
    costs = {}
    for line in usage.splitlines():
        m = re.match(
            r"\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*([\d,]+)\s*\|(?:\s*[\d,]+\s*\|){4}\s*\$([\d.]+)\s*\|\s*(\S+)\s*\|",
            line,
        )
        if not m or m.group(1) in ("stage", "---", "capture-probe"):
            continue
        family, model, calls, dollars, effort = m.groups()
        costs[family] = {"model": model, "calls": int(calls.replace(",", "")), "usd": float(dollars), "effort": effort}
    return costs


def summary_rows(name: str, run: str, findings: list, truth: dict, match: dict, dump: str, cost: dict) -> list[tuple]:
    wall = re.search(r"Wall-clock:\*\* (\d+)s \(([\d.]+) min\)", dump)
    funnel = re.search(
        r"\|\s*chunks\s*\|\s*review units\s*\|\s*raw issues\s*\|\s*after dedup\s*\|\s*passed validator\s*\|\n\|[-| ]+\|\n"
        r"\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|",
        dump,
    )
    chunks, units, raw, dedup, passed = funnel.groups() if funnel else ("?",) * 5

    kept_real = kept_not = dropped_real = dropped_not = 0
    unscored, real_ids, new_real = [], [], []
    real_clusters = set()
    for f in findings:
        t = truth.get(f["id"])
        if not t:
            unscored.append(f["id"])
            continue
        real, kept = bool(t["is_real"]), bool(f["is_valid"])
        kept_real += kept and real
        kept_not += kept and not real
        dropped_real += (not kept) and real
        dropped_not += (not kept) and not real
        if not real:
            continue
        real_ids.append(f["id"])
        cluster = (match.get(f["id"]) or {}).get("cluster")
        if cluster is None:
            new_real.append(f["id"])
        else:
            real_clusters.add(cluster)

    total_usd = sum(v["usd"] for v in cost.values())
    review = cost.get("review", {})
    blind = cost.get("blind-spot", {})
    review_usd = review.get("usd", 0.0) + blind.get("usd", 0.0)
    review_calls = review.get("calls", 0) + blind.get("calls", 0)
    validation = cost.get("validation", {"calls": 0, "usd": 0.0, "model": "?"})
    one_shots = sum(v["usd"] for k, v in cost.items() if k in ("perspective_selection", "dedup"))
    verdicts = sum(1 for f in findings if f.get("validator"))
    scored = len(findings) - len(unscored)

    return [
        ("run", run),
        ("wall-clock", f"{wall.group(1)}s ({wall.group(2)} min)" if wall else "?"),
        ("chunks / review units", f"{chunks} / {units}"),
        ("raw → dedup → kept (validator)", f"{raw} → {dedup} → {passed}"),
        ("findings judged (post-dedup)", f"{len(findings)} ({len(unscored)} unscored)"),
        ("real findings (reviewer side)", pct(len(real_ids), scored)),
        ("real clusters found", f"{len(real_clusters)} {sorted(real_clusters)}"),
        ("new real issues (not in registry)", f"{len(new_real)} {new_real}"),
        ("kept that were real (precision)", pct(kept_real, kept_real + kept_not)),
        ("real findings kept (recall)", pct(kept_real, kept_real + dropped_real)),
        ("not-real findings dropped", pct(dropped_not, kept_not + dropped_not)),
        ("findings with NO verdict", f"{len(findings) - verdicts}"),
        (
            "review + blind-spot cost",
            f"${review_usd:.2f} ({review_calls} calls, {review.get('model', '?')} @ {review.get('effort', '?')})",
        ),
        ("validation cost", f"${validation['usd']:.2f} ({validation['calls']} calls, {validation.get('model', '?')})"),
        ("cost per verdict", f"${validation['usd'] / verdicts:.3f}" if verdicts else "–"),
        ("one-shots (selection + dedup, Sonnet)", f"${one_shots:.2f}"),
        ("TOTAL gateway cost", f"${total_usd:.2f}"),
    ]


def main() -> None:
    name, run = sys.argv[1], sys.argv[2]
    findings = json.load(open(EXP / "findings" / f"{name}.json"))
    truth = json.load(open(EXP / "findings" / f"{name}.{TRUTH}.json"))
    match = json.load(open(EXP / "findings" / f"{name}.match.json"))
    dump = (EXP / "runs" / f"{run}.md").read_text()
    cost = stage_costs((EXP / "runs" / f"{run}.usage.md").read_text())

    md = [
        f"# {name} scorecard — {run} (frozen PR 75215, clean room, inline skills)",
        "",
        "| | " + name + " |",
        "| --- | --- |",
    ]
    md += [f"| {k} | {v} |" for k, v in summary_rows(name, run, findings, truth, match, dump, cost)]
    md += [
        "",
        "## Per-finding",
        "",
        "| id | cluster | real | kept | severity (truth) | prio (validator→) | title |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for f in findings:
        t = truth.get(f["id"]) or {}
        cluster = (match.get(f["id"]) or {}).get("cluster")
        real = "yes" if t.get("is_real") else ("no" if t else "?")
        priority = f.get("validator_priority") or f["priority"]
        title = f["title"][:90].replace("|", "/")
        md.append(
            f"| {f['id']} | {cluster if cluster is not None else '–'} | {real} | {'yes' if f['is_valid'] else 'no'} "
            f"| {t.get('severity') or '–'} | {priority} | {title} |"
        )

    text = "\n".join(md) + "\n"
    suffix = "score" if TRUTH == "truth" else "score.adjudicated"
    (EXP / "findings" / f"{name}.{suffix}.md").write_text(text)
    print(text)


main()
