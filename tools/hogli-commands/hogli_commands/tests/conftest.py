"""Shared test fixtures for hogli_commands extension tests.

These tests do not require Django. Run from the repo root with:
    pytest tools/hogli-commands/hogli_commands/tests/ -p no:django -o 'addopts=' -o 'DJANGO_SETTINGS_MODULE='
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from hogli_commands.devbox import herdr as devbox_herdr


@pytest.fixture(autouse=True)
def _no_real_herdr_machine_removal(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deleting a devbox calls `hc`, which is on the PATH of any developer who uses Herdr.
    monkeypatch.setattr(devbox_herdr, "forget_machine", lambda workspace_name: None)


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
