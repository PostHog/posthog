"""Truth-sensitivity of the arm ranking. Writes findings/SENSITIVITY.md.

A fresh     = per-finding 3-skeptic majority (as judged)
B pooled    = registry-matched findings take the majority of ALL fresh votes cast on their cluster in this experiment
C august    = clusters with >=2 August verdicts take August's majority (tie -> fresh); others fresh
D serious   = A, counting only must_fix / should_fix as real
E adjudicated = A with the 14 contested clusters replaced by the 3-adjudicator panel (findings/<S>.truth.adjudicated.json)
F adjudicated serious = E, counting only must_fix / should_fix as real
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .usage_costs import load_stage_costs
else:
    from usage_costs import load_stage_costs

EXP = Path(__file__).resolve().parent.parent
SETS = [
    ("GC", "glm-high-1bc"),
    ("GB", "glm-high-2"),
    ("UA", "luna-low-1"),
    ("UB", "luna-low-2"),
    ("SA", "sol-low-1"),
    ("SB", "sol-low-2"),
    ("MA", "luna-medium-1"),
    ("MB", "luna-medium-2"),
    ("XA", "luna-xhigh-1"),
    ("XB", "luna-xhigh-2"),
]
ARM = {
    "glm-high": "GLM 5.3 Flash @ high",
    "luna-low": "GPT 5.6 Luna @ low",
    "sol-low": "GPT 5.6 Sol @ low",
    "luna-medium": "GPT 5.6 Luna @ medium",
    "luna-xhigh": "GPT 5.6 Luna @ xhigh",
}
SERIOUS = ("must_fix", "should_fix")


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b:.0%})" if b else "–"


# Keep the archived CLI runnable without application imports.
@dataclass(frozen=True, kw_only=True, slots=True)
class SensitivityInputs:
    sets: dict
    adjudicated: dict
    pooled_votes: dict[int, list[int]]


def load() -> SensitivityInputs:
    """Per set: (run, findings, fresh truth, matches, gateway cost), the adjudicated truth, and pooled cluster votes."""
    data, adjudicated = {}, {}
    pool: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for name, run in SETS:
        findings = json.load(open(EXP / "findings" / f"{name}.json"))
        truth = json.load(open(EXP / "findings" / f"{name}.truth.json"))
        match = json.load(open(EXP / "findings" / f"{name}.match.json"))
        cost = sum(stage["usd"] for stage in load_stage_costs(EXP / "runs", run).values())
        data[name] = (run, findings, truth, match, cost)
        path = EXP / "findings" / f"{name}.truth.adjudicated.json"
        adjudicated[name] = json.load(open(path)) if path.exists() else None
        for f in findings:
            cluster = match[f["id"]]["cluster"]
            source = truth[f["id"]]["source"]
            if cluster is None or not source.startswith("verified"):
                continue
            real, total = map(int, source.split(":")[1].split("/"))
            pool[cluster][0] += real
            pool[cluster][1] += total
    return SensitivityInputs(sets=data, adjudicated=adjudicated, pooled_votes=pool)


INPUTS = load()
REGISTRY = {c["cluster"]: c for c in json.load(open(EXP / "known_clusters.json"))}


def is_real(mode: str, name: str, finding: dict) -> bool:
    _, _, truth, match, _ = INPUTS.sets[name]
    t = truth[finding["id"]]
    cluster = match[finding["id"]]["cluster"]
    if mode == "A":
        return t["is_real"]
    if mode == "D":
        return t["is_real"] and t["severity"] in SERIOUS
    if mode in ("E", "F"):
        a = INPUTS.adjudicated[name][finding["id"]]
        return a["is_real"] and (mode == "E" or a["severity"] in SERIOUS)
    if mode == "B":
        if cluster is None:
            return t["is_real"]
        real, total = INPUTS.pooled_votes[cluster]
        return real * 2 > total
    # mode C: August's majority where it verified the cluster at least twice and did not tie.
    k = REGISTRY.get(cluster) if cluster is not None else None
    if k and k["n_verified"] >= 2 and k["n_real"] * 2 != k["n_verified"]:
        return k["n_real"] * 2 > k["n_verified"]
    return t["is_real"]


def mode_table(mode: str) -> list[str]:
    out = [
        f"## {mode}",
        "",
        "| arm | real per run | posted real per run | posted noise per run | validator precision "
        "| validator recall | $ per real (reviewer side) | $ per posted real |",
        "| --- | ---: | ---: | ---: | --- | --- | ---: | ---: |",
    ]
    by_arm: dict[str, list[str]] = defaultdict(list)
    for name, run in SETS:
        by_arm[run.rsplit("-", 1)[0]].append(name)
    for arm, names in by_arm.items():
        real = kept_real = kept_not = dropped_real = 0
        cost = 0
        for name in names:
            _, findings, _, _, set_cost = INPUTS.sets[name]
            cost += set_cost
            for f in findings:
                r, kept = is_real(mode, name, f), f["is_valid"]
                real += r
                kept_real += r and kept
                kept_not += (not r) and kept
                dropped_real += r and not kept
        runs = len(names)
        per_real = f"${cost / real:.2f}" if real else "–"
        per_posted = f"${cost / kept_real:.2f}" if kept_real else "–"
        out.append(
            f"| {ARM[arm]} | {real / runs:.1f} | {kept_real / runs:.1f} | {kept_not / runs:.1f} "
            f"| {pct(kept_real, kept_real + kept_not)} | {pct(kept_real, kept_real + dropped_real)} "
            f"| {per_real} | {per_posted} |"
        )
    out.append("")
    return out


def main() -> None:
    legend = "  \n".join(line for line in __doc__.strip().splitlines() if line.strip())
    out = ["# Truth sensitivity of the arm ranking", "", legend, ""]
    for mode in "ABCDEF" if all(INPUTS.adjudicated.values()) else "ABCD":
        out += mode_table(mode)
    text = "\n".join(out)
    (EXP / "findings" / "SENSITIVITY.md").write_text(text + "\n")
    print(text)


main()
