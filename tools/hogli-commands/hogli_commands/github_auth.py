"""Shared GitHub auth for hogli commands: a token from the env or gh CLI, plus API headers.

Centralizes the one decision (how to source a github.com token and what headers to send)
so callers like db:restore-test-db and pr:upload-image don't each reimplement it.
"""

from __future__ import annotations

import os
import shutil
import subprocess


def github_token(*, prefer_cli: bool = False) -> str | None:
    """Use GH_TOKEN as an explicit override, then choose between GITHUB_TOKEN and gh.

    Personal uploads prefer the stored gh login because hogli also loads application
    credentials from .env.local. GITHUB_TOKEN remains the fallback without a gh login.
    Other callers retain environment-first selection for CI and service credentials.
    """
    if token := os.environ.get("GH_TOKEN"):
        return token
    fallback_token = os.environ.get("GITHUB_TOKEN") or None
    if fallback_token and not prefer_cli:
        return fallback_token
    gh = shutil.which("gh")
    if gh is None:
        return fallback_token
    try:
        result = subprocess.run(
            [gh, "auth", "token", "--hostname", "github.com"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env={key: value for key, value in os.environ.items() if key not in ("GH_TOKEN", "GITHUB_TOKEN")},
        )
    except (OSError, subprocess.TimeoutExpired):
        return fallback_token
    token = result.stdout.strip()
    return token if result.returncode == 0 and token else fallback_token


def github_headers(token: str | None) -> dict[str, str]:
    """Standard GitHub API headers, with Bearer auth when a token is available.

    The REST version pin is inert on GraphQL requests, which ignore unknown headers.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
