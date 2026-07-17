"""Shared GitHub auth for hogli commands: a token from the env or gh CLI, plus API headers.

Centralizes the one decision (how to source a github.com token and what REST headers to
send) so callers like db:restore-test-db and pr:upload-image don't each reimplement it.
"""

from __future__ import annotations

import os
import shutil
import subprocess


def github_token() -> str | None:
    """A github.com token from GH_TOKEN/GITHUB_TOKEN, else `gh auth token`, else None.

    Env vars win so CI and explicit overrides work without gh; otherwise fall back to the
    caller's gh login. Pinned to github.com so the result is independent of the cwd's repo.
    """
    for env_var in ("GH_TOKEN", "GITHUB_TOKEN"):
        if token := os.environ.get(env_var):
            return token
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        result = subprocess.run(
            [gh, "auth", "token", "--hostname", "github.com"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    token = result.stdout.strip()
    return token if result.returncode == 0 and token else None


def github_headers(token: str | None) -> dict[str, str]:
    """Standard GitHub REST API headers, with Bearer auth when a token is available."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
