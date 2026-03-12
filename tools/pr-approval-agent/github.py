"""GitHub data fetching via gh CLI + local git.

File stats come from the local checkout (git diff --numstat), everything
else (PR metadata, reviews, comments, check runs) from the GitHub API.
Also handles team membership checks for the ownership gate.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


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

    @property
    def has_new_files(self) -> bool:
        return any(f.get("status") == "A" for f in self.files)


def _gh_api(endpoint: str, *, paginate: bool = False) -> dict | list:
    cmd = ["gh", "api", endpoint]
    if paginate:
        cmd.append("--paginate")
    else:
        sep = "&" if "?" in endpoint else "?"
        cmd[2] = f"{endpoint}{sep}per_page=100"
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"gh api {endpoint} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _git_diff_files(base_sha: str, head_sha: str, repo_root: Path) -> list[dict]:
    """Get changed files with line counts and status from the local checkout."""
    diff_range = f"{base_sha}...{head_sha}"
    run_opts = {"capture_output": True, "text": True, "timeout": 30, "cwd": repo_root}

    numstat = subprocess.run(["git", "diff", "--numstat", diff_range], **run_opts)
    if numstat.returncode != 0:
        raise RuntimeError(f"git diff --numstat failed: {numstat.stderr.strip()}")

    name_status = subprocess.run(["git", "diff", "--name-status", diff_range], **run_opts)
    status_map: dict[str, str] = {}
    for line in name_status.stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            status_map[parts[1]] = parts[0]

    files = []
    for line in numstat.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        added, deleted, filename = parts
        is_binary = added == "-"
        files.append(
            {
                "filename": filename,
                "additions": int(added) if not is_binary else 0,
                "deletions": int(deleted) if not is_binary else 0,
                "binary": is_binary,
                "status": status_map.get(filename, "M"),
            }
        )
    return files


def ensure_commits(pr_number: int, head_sha: str, repo_root: Path) -> None:
    """Fetch PR commits if not available locally."""
    result = subprocess.run(
        ["git", "cat-file", "-t", head_sha],
        cwd=repo_root,
        capture_output=True,
        timeout=5,
    )
    if result.returncode == 0:
        return
    subprocess.run(
        ["git", "fetch", "origin", f"pull/{pr_number}/head"],
        cwd=repo_root,
        capture_output=True,
        timeout=30,
    )


def fetch_pr(pr_number: int, repo: str, repo_root: Path | None = None) -> PRData:
    """Fetch PR data: metadata from API, file stats from local git."""
    pr = _gh_api(f"repos/{repo}/pulls/{pr_number}")
    reviews_raw = _gh_api(f"repos/{repo}/pulls/{pr_number}/reviews", paginate=True)
    comments_raw = _gh_api(f"repos/{repo}/pulls/{pr_number}/comments", paginate=True)

    base_sha = pr["base"]["sha"]
    head_sha = pr["head"]["sha"]
    check_runs_resp = _gh_api(f"repos/{repo}/commits/{head_sha}/check-runs")

    git_root = repo_root or Path.cwd()
    ensure_commits(pr_number, head_sha, git_root)
    files = _git_diff_files(base_sha, head_sha, git_root)

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
        files=files,
        reviews=[
            {
                "user": r["user"]["login"],
                "state": r["state"],
                "body": r.get("body", ""),
            }
            for r in reviews_raw
            if r.get("author_association") in ("MEMBER", "OWNER", "COLLABORATOR", "BOT")
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
            if c.get("author_association") in ("MEMBER", "OWNER", "COLLABORATOR", "BOT")
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
