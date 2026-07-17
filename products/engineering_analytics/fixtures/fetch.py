#!/usr/bin/env python3
"""Snapshot a bounded subset of a GitHub repo into the engineering analytics fixture.

Fetches recent pull requests and workflow runs via the `gh` CLI (uses your
existing `gh auth` token) and writes them, trimmed to the fields the curated
warehouse views read, to JSON files next to this script:

- github_pull_requests.json
- github_workflow_runs.json

Load the result into a local PostHog stack with:

    python manage.py seed_engineering_analytics --team-id <id>

Usage:
    python products/engineering_analytics/fixtures/fetch.py
    python products/engineering_analytics/fixtures/fetch.py --repo PostHog/posthog --days 30 --max-prs 300
"""

import sys
import json
import argparse
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).parent

# Only the fields the curated query builders in backend/logic/views read.
PR_FIELDS = ("id", "number", "title", "state", "draft", "created_at", "updated_at", "merged_at", "closed_at")
RUN_FIELDS = (
    "id",
    "name",
    "head_sha",
    "head_branch",
    "status",
    "conclusion",
    "created_at",
    "run_started_at",
    "updated_at",
    "run_attempt",
)


def log(message: str) -> None:
    print(message, file=sys.stderr)  # noqa: T201 — CLI progress output


def write_records(path: Path, records: list[dict[str, Any]]) -> None:
    lines = ",\n".join(json.dumps(record, separators=(",", ":")) for record in records)
    path.write_text(f"[\n{lines}\n]\n")


def gh_api(path: str) -> Any:
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def trim_pr(pr: dict[str, Any]) -> dict[str, Any]:
    trimmed: dict[str, Any] = {field: pr[field] for field in PR_FIELDS}
    trimmed["user"] = {"login": pr["user"]["login"], "avatar_url": pr["user"]["avatar_url"]}
    trimmed["head"] = {"sha": pr["head"]["sha"]}
    trimmed["base"] = {"repo": {"full_name": pr["base"]["repo"]["full_name"]}}
    trimmed["labels"] = [{"name": label["name"]} for label in pr["labels"]]
    return trimmed


def trim_run(run: dict[str, Any]) -> dict[str, Any]:
    trimmed: dict[str, Any] = {field: run[field] for field in RUN_FIELDS}
    trimmed["repository"] = {"full_name": run["repository"]["full_name"]}
    # The PR-list push / re-run rollup attributes runs to a PR via this association.
    trimmed["pull_requests"] = [{"number": pr["number"]} for pr in (run.get("pull_requests") or [])]
    return trimmed


def fetch_pull_requests(repo: str, cutoff: datetime, max_prs: int) -> list[dict[str, Any]]:
    prs: list[dict[str, Any]] = []
    for page in range(1, (max_prs // 100) + 2):
        batch = gh_api(f"repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=100&page={page}")
        if not batch:
            break
        for pr in batch:
            if datetime.fromisoformat(pr["updated_at"]) < cutoff:
                return prs
            prs.append(trim_pr(pr))
            if len(prs) >= max_prs:
                return prs
    return prs


def fetch_window_runs(repo: str, cutoff: datetime, max_runs: int) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    created = cutoff.strftime("%Y-%m-%d")
    for page in range(1, (max_runs // 100) + 2):
        batch = gh_api(f"repos/{repo}/actions/runs?created=>{created}&per_page=100&page={page}")["workflow_runs"]
        if not batch:
            break
        runs.extend(trim_run(run) for run in batch)
        if len(runs) >= max_runs:
            return runs[:max_runs]
    return runs


def fetch_head_sha_runs(repo: str, prs: list[dict[str, Any]], max_lookups: int) -> list[dict[str, Any]]:
    # The PR list joins CI status by head SHA, so open PRs need their head runs
    # even when those fall outside the windowed fetch.
    runs: list[dict[str, Any]] = []
    open_shas = [pr["head"]["sha"] for pr in prs if pr["state"] == "open"][:max_lookups]
    for index, sha in enumerate(open_shas, start=1):
        batch = gh_api(f"repos/{repo}/actions/runs?head_sha={sha}&per_page=50")["workflow_runs"]
        runs.extend(trim_run(run) for run in batch)
        if index % 25 == 0:
            log(f"  head-sha runs: {index}/{len(open_shas)} PRs")
    return runs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default="PostHog/posthog", help="owner/name repo to snapshot (default: %(default)s)")
    parser.add_argument("--days", type=int, default=30, help="recency window in days (default: %(default)s)")
    parser.add_argument("--max-prs", type=int, default=300, help="cap on pull requests (default: %(default)s)")
    parser.add_argument(
        "--max-runs", type=int, default=1000, help="cap on windowed workflow runs (default: %(default)s)"
    )
    parser.add_argument(
        "--max-sha-lookups",
        type=int,
        default=150,
        help="cap on per-open-PR head-sha run lookups (default: %(default)s)",
    )
    args = parser.parse_args()

    cutoff = datetime.now(UTC) - timedelta(days=args.days)

    log(f"Fetching PRs for {args.repo} updated since {cutoff:%Y-%m-%d} (max {args.max_prs})...")
    prs = fetch_pull_requests(args.repo, cutoff, args.max_prs)
    log(f"  {len(prs)} PRs")

    log(f"Fetching workflow runs created since {cutoff:%Y-%m-%d} (max {args.max_runs})...")
    runs = fetch_window_runs(args.repo, cutoff, args.max_runs)
    log(f"  {len(runs)} windowed runs")

    log("Fetching head-sha runs for open PRs...")
    sha_runs = fetch_head_sha_runs(args.repo, prs, args.max_sha_lookups)
    by_id = {run["id"]: run for run in [*runs, *sha_runs]}
    log(f"  {len(by_id)} runs after dedup")

    # One record per line: compact but still diff-able on refresh.
    write_records(FIXTURE_DIR / "github_pull_requests.json", prs)
    write_records(FIXTURE_DIR / "github_workflow_runs.json", sorted(by_id.values(), key=lambda r: r["id"]))
    log(f"Wrote {len(prs)} PRs and {len(by_id)} runs to {FIXTURE_DIR}")


if __name__ == "__main__":
    main()
