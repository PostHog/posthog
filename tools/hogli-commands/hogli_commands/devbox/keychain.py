"""macOS Keychain helpers for storing secrets.

On non-macOS platforms all functions silently return None/False.
"""

from __future__ import annotations

import os
import sys
import subprocess


def _account() -> str:
    return os.environ.get("USER", "posthog")


def _is_macos() -> bool:
    return sys.platform == "darwin"


def is_supported() -> bool:
    """Return whether Keychain storage is available on this platform."""
    return _is_macos()


def read(service: str) -> str | None:
    """Read a secret from macOS Keychain by service name."""
    if not _is_macos():
        return None

    result = subprocess.run(
        ["security", "find-generic-password", "-a", _account(), "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    value = result.stdout.strip()
    return value or None


def write(service: str, value: str) -> bool:
    """Store a secret in macOS Keychain under the given service name."""
    if not _is_macos():
        return False

    account = _account()

    # Delete existing entry (add-generic-password doesn't update in place)
    subprocess.run(
        ["security", "delete-generic-password", "-a", account, "-s", service],
        capture_output=True,
    )

    result = subprocess.run(
        ["security", "add-generic-password", "-a", account, "-s", service, "-w", value],
        capture_output=True,
    )
    return result.returncode == 0


def delete(service: str) -> bool:
    """Remove a secret from macOS Keychain by service name."""
    if not _is_macos():
        return False

    result = subprocess.run(
        ["security", "delete-generic-password", "-a", _account(), "-s", service],
        capture_output=True,
    )
    return result.returncode == 0
