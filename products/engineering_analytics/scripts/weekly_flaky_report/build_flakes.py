"""Join last-week CI failure evidence with code ownership into flakes.json."""

import os
import json
import subprocess
from collections import defaultdict
from pathlib import Path

DATA = Path(os.environ.get("FLAKES_DATA", "."))
REPO = Path(
    subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
)

owners = {}
for line in (DATA / "test_ownership.tsv").read_text().splitlines():
    path, owner = line.split("\t")
    owners[path] = owner

all_files = subprocess.run(
    ["git", "-C", str(REPO), "ls-files"], capture_output=True, text=True, check=True
).stdout.splitlines()
by_suffix = defaultdict(list)
for f in all_files:
    if f.endswith(".py"):
        by_suffix[f.split("/")[-1]].append(f)


def resolve_file(raw_path: str, job_hint: str) -> str | None:
    candidates = [raw_path]
    if not raw_path.endswith(".py"):
        candidates = [raw_path + ".py", "/".join(raw_path.split("/")[:-1]) + ".py"]
    for cand in candidates:
        if (REPO / cand).exists():
            return cand
        matches = [f for f in by_suffix.get(cand.split("/")[-1], []) if f.endswith("/" + cand) or f == cand]
        if len(matches) == 1:
            return matches[0]
        if matches and job_hint:
            hinted = [m for m in matches if m.startswith("products/") and m.split("/")[1].replace("_", "-") in job_hint]
            if len(hinted) == 1:
                return hinted[0]
        if matches:
            return matches[0]
    return None


def owner_for(path: str | None) -> str:
    if path is None:
        return "unresolved"
    if path in owners:
        return owners[path]
    out = subprocess.run(["hogli", "owners:resolve", "--json", path], capture_output=True, text=True)
    try:
        data = json.loads(out.stdout)
        team = (data[path].get("owners") or [None])[0]
        return team or "UNOWNED"
    except Exception:
        return "UNOWNED"


rerun = {}
for line in (DATA / "rerun_recovered.psv").read_text().splitlines()[1:]:
    tid, rp, rr = line.split("|")
    rerun[tid] = {"rerun_passed_failures": int(rp), "runs_recovered": int(rr)}

span_rerun = {}
for line in (DATA / "span_rerun_passed.psv").read_text().splitlines()[1:]:
    parts = line.split("|")
    span_rerun[parts[0]] = int(parts[1])

tests = []
lines = (DATA / "failures_export.psv").read_text().splitlines()
header = lines[0].split("|")
for line in lines[1:]:
    parts = line.split("|")
    row = dict(zip(header, parts))
    tid = row["test_id"]
    raw_path = tid.split("::")[0]
    job_hint = row.get("sample_jobs", "")
    path = resolve_file(raw_path, job_hint)
    failures = int(row["failures"])
    branches = int(row["branches"])
    master = int(row["master_failures"])
    rec = rerun.get(tid, {})
    # span nodeids join: convert file.py::Class::test -> file/Class::test form
    span_key = tid.replace(".py::", "/", 1).replace("::", "::", 1)
    span_rp = span_rerun.get(span_key, 0)
    confirmed = bool(rec) or span_rp > 0
    if confirmed:
        cls = "confirmed"
    elif master / failures >= 0.5 and branches <= 3:
        cls = "master_burst"
    elif branches >= 3:
        cls = "suspected"
    else:
        cls = "low_signal"
    tests.append(
        {
            "test_id": tid,
            "file": path,
            "team": owner_for(path),
            "failures": failures,
            "branches": branches,
            "runs": int(row["runs"]),
            "master_failures": master,
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "sample_run_id": int(row["sample_run_id"]),
            "rerun_recovered_failures": rec.get("rerun_passed_failures", 0) + span_rp,
            "runs_recovered": rec.get("runs_recovered", 0),
            "classification": cls,
        }
    )

# collapse mass co-failure clusters: >=5 suspected tests in one file
by_file = defaultdict(list)
for t in tests:
    if t["classification"] == "suspected":
        by_file[t["file"]].append(t)
clusters = []
for path, group in by_file.items():
    if len(group) >= 5:
        for t in group:
            t["classification"] = "cluster"
        clusters.append(
            {
                "file": path,
                "team": group[0]["team"],
                "tests": len(group),
                "failures": sum(t["failures"] for t in group),
                "branches": max(t["branches"] for t in group),
                "sample_run_id": group[0]["sample_run_id"],
            }
        )

team_agg = defaultdict(
    lambda: {"confirmed": 0, "suspected": 0, "clusters": 0, "failures": 0, "runs_recovered": 0, "tests": []}
)
for t in tests:
    if t["classification"] in ("confirmed", "suspected"):
        agg = team_agg[t["team"]]
        agg[t["classification"]] += 1
        agg["failures"] += t["failures"]
        agg["runs_recovered"] += t["runs_recovered"]
        agg["tests"].append(t["test_id"])
for c in clusters:
    agg = team_agg[c["team"]]
    agg["clusters"] += 1
    agg["failures"] += c["failures"]

out = {
    "window": {"from": "2026-07-16", "to": "2026-07-23"},
    "totals": {
        "failure_rows": 4213,
        "unique_failing_tests": 796,
        "rerun_jobs": 40084,
        "rerun_cost_usd": 775.86,
        "tests_analyzed": len(tests),
    },
    "teams": dict(sorted(team_agg.items(), key=lambda kv: -(kv[1]["confirmed"] * 3 + kv[1]["suspected"]))),
    "tests": tests,
    "clusters": clusters,
}
(DATA / "flakes.json").write_text(json.dumps(out, indent=1))

counts = defaultdict(int)
for t in tests:
    counts[t["classification"]] += 1
print("classifications:", dict(counts))  # noqa: T201
print("clusters:", len(clusters))  # noqa: T201
print("teams:")  # noqa: T201
for team, agg in out["teams"].items():
    print(  # noqa: T201
        f"  {team}: confirmed={agg['confirmed']} suspected={agg['suspected']} clusters={agg['clusters']} failures={agg['failures']} recovered={agg['runs_recovered']}"
    )
