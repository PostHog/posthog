"""GitHub data fetching via gh CLI.

Fetches PR metadata, files, reviews, comments, check runs, and diffs.
Also handles team membership checks for the ownership gate.
"""

import json
import subprocess
from dataclasses import dataclass


@dataclass
class PRData:
    """All GitHub data needed to evaluate a PR."""

    number: int
    repo: str
    title: str
    state: str
    draft: bool
    mergeable_state: str
    author: str
    labels: list[str]
    base_sha: str
    head_sha: str
    files: list[dict]
    reviews: list[dict]
    review_comments: list[dict]
    check_runs: list[dict]

    @property
    def file_paths(self) -> list[str]:
        return [f["filename"] for f in self.files]

    @property
    def lines_added(self) -> int:
        return sum(f["additions"] for f in self.files)

    @property
    def lines_deleted(self) -> int:
        return sum(f["deletions"] for f in self.files)

    @property
    def lines_total(self) -> int:
        return self.lines_added + self.lines_deleted


def _gh_api(endpoint: str, paginate: bool = False) -> dict | list:
    cmd = ["gh", "api", endpoint]
    if paginate:
        cmd.append("--paginate")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"gh api {endpoint} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def fetch_pr(pr_number: int, repo: str) -> PRData:
    """Fetch all PR data needed for review in parallel-ish gh api calls."""
    pr = _gh_api(f"repos/{repo}/pulls/{pr_number}")
    files_raw = _gh_api(f"repos/{repo}/pulls/{pr_number}/files")
    reviews_raw = _gh_api(f"repos/{repo}/pulls/{pr_number}/reviews")
    comments_raw = _gh_api(f"repos/{repo}/pulls/{pr_number}/comments")

    base_sha = pr["base"]["sha"]
    head_sha = pr["head"]["sha"]
    check_runs_resp = _gh_api(f"repos/{repo}/commits/{head_sha}/check-runs")

    return PRData(
        number=pr_number,
        repo=repo,
        title=pr["title"],
        state=pr["state"],
        draft=pr.get("draft", False),
        mergeable_state=pr.get("mergeable_state", "unknown"),
        author=pr["user"]["login"],
        labels=[label["name"] for label in pr.get("labels", [])],
        base_sha=base_sha,
        head_sha=head_sha,
        files=[
            {
                "filename": f["filename"],
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "status": f.get("status", ""),
                "patch": f.get("patch", ""),
            }
            for f in files_raw
        ],
        reviews=[
            {
                "user": r["user"]["login"],
                "state": r["state"],
                "body": r.get("body", ""),
            }
            for r in reviews_raw
        ],
        review_comments=[
            {
                "user": c["user"]["login"],
                "body": c.get("body", ""),
                "path": c.get("path", ""),
                "line": c.get("line"),
                "in_reply_to_id": c.get("in_reply_to_id"),
            }
            for c in comments_raw
        ],
        check_runs=check_runs_resp.get("check_runs", []),
    )


def check_team_membership(author: str, team_slug: str) -> bool:
    """Check if author is an active member of the given GitHub team."""
    try:
        result = subprocess.run(
            ["gh", "api", f"orgs/PostHog/teams/{team_slug}/memberships/{author}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return json.loads(result.stdout).get("state") == "active"
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return False
