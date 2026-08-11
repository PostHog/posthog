"""Scanners minted from a config passed inline, for one-off questions about named sessions.

An observation belongs to a scanner: that FK is its RBAC anchor, the unique `(scanner, session)` slot
that makes a scan idempotent, and the thing its results are read back through. An inline scan has no
saved scanner, so it needs one anyway, and it gets one keyed by a fingerprint of its config. Asking the
same question twice resolves to the same scanner and reuses the observations it already has; asking a
different question about the same session gets its own.

These rows are not scanners in the sense the rest of the product means. They have no name, no candidate
query, and no schedule, and `ReplayScanner.objects` excludes them so nothing lists, counts, edits, or
sweeps them. `ReplayScanner.all_origins` is the deliberate opt-in for the two paths that must see them:
resolving a scan id, and reading observations back.
"""

from typing import Any

from posthog.models.team import Team

from products.replay_vision.backend.fingerprint import config_fingerprint
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerOrigin, ScannerType


def inline_scan_key(*, scanner_type: str, scanner_config: dict[str, Any], model: str) -> str:
    """Fingerprint of everything that decides what an inline scan produces.

    Full digest, not the schedule fingerprint's 16 chars: this key is an identity, so a collision would
    merge two unrelated questions into one result set rather than cost a redundant reconcile.
    """
    return config_fingerprint(
        {"scanner_type": ScannerType(scanner_type).value, "model": str(model), "scanner_config": scanner_config}
    )


def find_inline_scanner(*, team: Team, key: str) -> ReplayScanner | None:
    """The scanner this config already resolved to, if this question has been asked before."""
    return ReplayScanner.all_origins.filter(team=team, origin=ScannerOrigin.INLINE, inline_key=key).first()


def create_inline_scanner(
    *,
    team: Team,
    key: str,
    scanner_type: ScannerType,
    scanner_config: dict[str, Any],
    model: str,
) -> ReplayScanner:
    """Mint the scanner for an inline config. Call only once a scan is actually going to start.

    `get_or_create` rather than a plain create: two requests can ask the same question at the same
    moment, and it wraps the losing INSERT in a savepoint so the unique violation doesn't poison an
    enclosing transaction.
    """
    scanner, _ = ReplayScanner.all_origins.get_or_create(
        team=team,
        origin=ScannerOrigin.INLINE,
        inline_key=key,
        defaults={
            # No name: inline scanners aren't addressed by one, and the team-name uniqueness index is
            # partial on configured rows so several unnamed rows per team coexist happily.
            "name": "",
            "description": "Created by an inline scan. Runs only against the sessions it was pointed at.",
            # No owner: the row is shared by everyone who asks this question, so crediting whoever got
            # here first would misattribute it.
            "created_by": None,
            "scanner_type": scanner_type,
            "scanner_config": scanner_config,
            "model": model,
            # Nothing to sweep: no query, and disabled, which is what actually gates scheduling.
            "enabled": False,
            "sampling_rate": 0.0,
        },
    )
    return scanner
