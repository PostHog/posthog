"""Shared test fixtures for hogli_commands extension tests.

These tests do not require Django. Run from the repo root with:
    pytest tools/hogli-commands/hogli_commands/tests/ -p no:django -o 'addopts=' -o 'DJANGO_SETTINGS_MODULE='
"""

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def git() -> Callable[..., str]:
    def run(repo: Path, *args: str) -> str:
        return subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.com",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    return run
