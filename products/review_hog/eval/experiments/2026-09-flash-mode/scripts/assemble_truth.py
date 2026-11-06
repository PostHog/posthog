"""Turn the judge workflow's return (JSON) into findings/<SET>.match.json, <SET>.truth.json and verify/<SET><id>.json.

    python scripts/assemble_truth.py <judge_result.json> [<verify_pending_result.json> ...]

Extra files are follow-up verification results ([{letter, verified:[...]}]) merged into the judge's verified lists.
Truth per finding: a fresh 3-skeptic majority when one was run; else the registry cluster's unanimous verdict
(n_verified >= 3 and n_real == 0 or == n_verified); else left for a follow-up verification (printed).
"""

import sys
import json
from pathlib import Path

EXP = Path(__file__).resolve().parent.parent
SEVERITY_RANK = {"must_fix": 0, "should_fix": 1, "consider": 2}
OUT_DIR = EXP / "findings"
REGISTRY = {c["cluster"]: c for c in json.load(open(EXP / "known_clusters.json"))}


def follow_up_verdicts(paths: list[str]) -> dict[str, list]:
    """Verdicts from follow-up verification runs, by set letter."""
    extra: dict[str, list] = {}
    for path in paths:
        for block in json.load(open(path)):
            extra.setdefault(block["letter"], []).extend(block["verified"])
    return extra


def registry_verdict(cluster: int | None) -> dict | None:
    """The registry's verdict for a cluster, only when every earlier verification agreed."""
    k = REGISTRY.get(cluster) if cluster is not None else None
    if not k or k["n_verified"] < 3 or 0 < k["n_real"] < k["n_verified"]:
        return None
    real = k["n_real"] > 0
    severity = sorted(k["severities"], key=lambda s: SEVERITY_RANK.get(s, 9))[0] if real and k["severities"] else None
    return {
        "is_real": real,
        "severity": severity,
        "cluster": cluster,
        "source": f"cluster {k['n_real']}/{k['n_verified']}",
    }


def write_set(block: dict, extra: dict[str, list]) -> None:
    letter = block["letter"]
    matches = block["matches"]
    verified = {v["id"]: v for v in list(block["verified"]) + extra.get(letter, [])}

    json.dump(
        {
            fid: {"cluster": m["cluster"], "confidence": m["confidence"], "reason": m["reason"]}
            for fid, m in matches.items()
        },
        open(OUT_DIR / f"{letter}.match.json", "w"),
        indent=1,
    )

    truth, pending = {}, []
    for fid, m in matches.items():
        cluster = m["cluster"]
        if fid in verified:
            v = verified[fid]
            reals = sum(1 for x in v["votes"] if x["is_real"])
            truth[fid] = {
                "is_real": v["is_real"],
                "severity": v["severity"],
                "cluster": cluster,
                "source": f"verified-3-skeptics:{reals}/{len(v['votes'])}",
            }
            json.dump(v, open(OUT_DIR / "verify" / f"{fid}.json", "w"), indent=1)
            continue
        from_registry = registry_verdict(cluster)
        if from_registry:
            truth[fid] = from_registry
        else:
            k = REGISTRY.get(cluster) if cluster is not None else None
            pending.append((fid, cluster, None if k is None else f"{k['n_real']}/{k['n_verified']}"))

    json.dump(truth, open(OUT_DIR / f"{letter}.truth.json", "w"), indent=1)
    print(
        f"{letter}: {len(matches)} matched, {len(verified)} verified fresh, {len(truth)} with truth, "
        f"{len(pending)} PENDING: {pending}"
    )


def main() -> None:
    (OUT_DIR / "verify").mkdir(parents=True, exist_ok=True)
    extra = follow_up_verdicts(sys.argv[2:])
    for block in json.load(open(sys.argv[1])):
        write_set(block, extra)


main()
