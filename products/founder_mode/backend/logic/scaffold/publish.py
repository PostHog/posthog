"""Push a generated file tree to a fresh GitHub repository.

Uses the GitHub Git Data API to commit the whole tree in three round trips (regardless of
how many files):

1. Create the repository under the authenticated user.
2. For each file, POST a blob → collect blob SHAs (one HTTP call per file, but small).
3. Build a single tree object referencing those blobs → create a commit referencing the
   tree → update `refs/heads/main` (or create it on an empty repo) to point at the commit.

Auth is a personal access token passed in the request body. We use it once, never persist
it. The token needs `repo` scope.
"""

import time
from typing import Any, cast

import requests

from .schemas import PagesLink, RepoLink

GITHUB_API = "https://api.github.com"
TIMEOUT_SECONDS = 60
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.5
DEFAULT_BRANCH = "main"

# GitHub Pages takes a moment to provision after enable. We poll for up to this long; if
# it's not built by then, we return what we have and flag the build state.
PAGES_TERMINAL_STATES = {"built", "errored"}
PAGES_POLL_INTERVAL_SECONDS = 4
PAGES_POLL_BUDGET_SECONDS = 60


class GitHubPublishError(Exception):
    """Raised when GitHub rejects a step of the publish flow."""


def _headers(github_token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "posthog-founder-mode-scaffold",
    }


def _request_with_retry(
    method: str, url: str, *, github_token: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Wrap a GitHub call in `RETRY_ATTEMPTS` tries with backoff.

    Retries cover transient network failures (SSL EOF, connection reset, read timeout) and
    5xx responses. 4xx responses raise immediately — they're real errors that retrying won't
    fix and re-running might double-charge state-changing endpoints.
    """
    last_exc: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            r = requests.request(method, url, headers=_headers(github_token), json=payload, timeout=TIMEOUT_SECONDS)
            if 500 <= r.status_code < 600:
                last_exc = GitHubPublishError(f"{method} {url} -> {r.status_code}: {r.text[:400]}")
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            if r.status_code >= 300:
                raise GitHubPublishError(f"{method} {url} -> {r.status_code}: {r.text[:400]}")
            return cast(dict[str, Any], r.json()) if r.content else {}
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue
    raise GitHubPublishError(f"{method} {url} failed after {RETRY_ATTEMPTS} attempts: {last_exc}")


def _post(url: str, *, github_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _request_with_retry("POST", url, github_token=github_token, payload=payload)


def _patch(url: str, *, github_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _request_with_retry("PATCH", url, github_token=github_token, payload=payload)


def _get(url: str, *, github_token: str) -> dict[str, Any]:
    return _request_with_retry("GET", url, github_token=github_token)


def enable_github_pages(
    *, github_token: str, owner: str, repo: str, branch: str = DEFAULT_BRANCH, path: str = "/"
) -> PagesLink:
    """Enable GitHub Pages on a repo and poll briefly for the live URL.

    Returns a `PagesLink` with the final `pages_status` (`built`, `building`, `errored`,
    or `not_provisioned` if our budget expires before GitHub reports a terminal state).
    """
    api_repo = f"{GITHUB_API}/repos/{owner}/{repo}"
    try:
        _post(f"{api_repo}/pages", github_token=github_token, payload={"source": {"branch": branch, "path": path}})
    except GitHubPublishError as exc:
        # 409 means Pages was already enabled — fine, fall through to the poll.
        if "409" not in str(exc):
            raise

    deadline = time.monotonic() + PAGES_POLL_BUDGET_SECONDS
    pages_status = "queued"
    html_url = f"https://{owner}.github.io/{repo}/"
    source_branch = branch
    source_path = path
    while time.monotonic() < deadline:
        info = _get(f"{api_repo}/pages", github_token=github_token)
        pages_status = info.get("status") or "queued"
        html_url = info.get("html_url") or html_url
        source = info.get("source") or {}
        source_branch = source.get("branch", branch)
        source_path = source.get("path", path)
        if pages_status in PAGES_TERMINAL_STATES:
            break
        time.sleep(PAGES_POLL_INTERVAL_SECONDS)
    if pages_status not in PAGES_TERMINAL_STATES:
        pages_status = pages_status or "not_provisioned"
    return PagesLink(html_url=html_url, pages_status=pages_status, source_branch=source_branch, source_path=source_path)


def push_to_github(
    *,
    github_token: str,
    repo_name: str,
    files: dict[str, str],
    visibility: str = "private",
    description: str = "",
) -> RepoLink:
    """Create a new repo on the authenticated user's account and push every file in one commit.

    Returns a `RepoLink` with the API URL, browseable URL, branch, and commit SHA. Raises
    `GitHubPublishError` if any step of the flow fails.
    """
    if not files:
        raise GitHubPublishError("Cannot publish: file tree is empty.")
    if visibility not in ("public", "private"):
        raise GitHubPublishError(f"Invalid visibility: {visibility!r}")

    # Step 1 — create the repository. `auto_init=true` gives us an initial commit + main
    # branch reference we can update; without it we'd have to create the first ref from
    # scratch, which is fiddly.
    repo = _post(
        f"{GITHUB_API}/user/repos",
        github_token=github_token,
        payload={
            "name": repo_name,
            "description": description,
            "private": visibility == "private",
            "auto_init": True,
        },
    )
    api_url = repo["url"]
    html_url = repo["html_url"]
    default_branch = repo.get("default_branch") or DEFAULT_BRANCH

    # Step 2 — fetch the SHA of the auto-init commit (parent for our commit) and the tree
    # SHA on it (base for our tree).
    ref = _get(f"{api_url}/git/ref/heads/{default_branch}", github_token=github_token)
    parent_commit_sha = ref["object"]["sha"]

    parent_commit = _get(f"{api_url}/git/commits/{parent_commit_sha}", github_token=github_token)
    base_tree_sha = parent_commit["tree"]["sha"]

    # Step 3 — create one blob per file. We could batch with multipart but the per-file POST
    # is the simplest correct path; the file tree is small (~30-50 files for a landing page).
    tree_entries: list[dict[str, Any]] = []
    for path, contents in files.items():
        blob = _post(
            f"{api_url}/git/blobs",
            github_token=github_token,
            payload={"content": contents, "encoding": "utf-8"},
        )
        tree_entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})

    # Step 4 — build a tree off the base (so we keep README.md from auto_init) and commit.
    tree = _post(
        f"{api_url}/git/trees",
        github_token=github_token,
        payload={"base_tree": base_tree_sha, "tree": tree_entries},
    )
    commit = _post(
        f"{api_url}/git/commits",
        github_token=github_token,
        payload={
            "message": "feat: initial scaffold from PostHog founder mode",
            "tree": tree["sha"],
            "parents": [parent_commit_sha],
        },
    )

    # Step 5 — update the branch ref to point at our new commit.
    _patch(
        f"{api_url}/git/refs/heads/{default_branch}",
        github_token=github_token,
        payload={"sha": commit["sha"], "force": False},
    )

    return RepoLink(
        repo_url=api_url,
        html_url=html_url,
        default_branch=default_branch,
        commit_sha=commit["sha"],
        file_count=len(files),
    )


__all__ = ["push_to_github", "GitHubPublishError", "RepoLink", "owner_of"]


def owner_of(github_token: str) -> str:
    """Resolve the authenticated user's GitHub login. Used for nicer error messages."""
    return cast(str, _get(f"{GITHUB_API}/user", github_token=github_token)["login"])
