"""Implicit scanners behind ad-hoc scans — a prompt pointed at named sessions, with nothing saved.

An observation belongs to a scanner (RBAC, the unique (scanner, session) slot, the snapshot it is read
back through), so an ad-hoc prompt still needs one. Rather than a second parallel model, a scan mints a
scanner keyed by a fingerprint of its config: asking the same question twice reuses one scanner, asking a
different question about the same session gets a fresh one. These scanners are never scheduled and
`ReplayScanner.objects.configured()` keeps them out of the team's scanner set.
"""

from typing import Any

from django.db import IntegrityError

from posthog.models.team import Team
from posthog.models.user import User

from products.replay_vision.backend.fingerprint import config_fingerprint
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType


def ad_hoc_key(*, scanner_type: str, scanner_config: dict[str, Any], model: str) -> str:
    """Fingerprint of everything that decides what an ad-hoc scan produces."""
    return config_fingerprint(
        {"scanner_type": str(scanner_type), "model": str(model), "scanner_config": scanner_config}
    )


def get_or_create_ad_hoc_scanner(
    *,
    team: Team,
    user: User,
    scanner_type: ScannerType,
    scanner_config: dict[str, Any],
    model: str,
) -> ReplayScanner:
    """The scanner this ad-hoc config resolves to, created on first use."""
    key = ad_hoc_key(scanner_type=scanner_type, scanner_config=scanner_config, model=model)
    existing = ReplayScanner.objects.filter(team=team, ad_hoc_key=key).first()
    if existing is not None:
        return existing
    try:
        return ReplayScanner.objects.create(
            team=team,
            created_by=user,
            ad_hoc_key=key,
            # Named off the fingerprint so (team, name) uniqueness never fights (team, ad_hoc_key).
            name=f"Ad hoc scan {key}",
            description="Created by an ad-hoc scan. Runs only against the sessions it's pointed at.",
            scanner_type=scanner_type,
            scanner_config=scanner_config,
            model=model,
            # Nothing to sweep: no query, and disabled, which is what actually gates scheduling.
            # `sampling_rate=0` guards the one way that could change — these rows stay addressable
            # by id, so a later PATCH flipping `enabled` would otherwise start a standing sweep.
            enabled=False,
            sampling_rate=0.0,
        )
    except IntegrityError:
        # A concurrent request for the same fingerprint won the unique index; share its scanner.
        concurrent = ReplayScanner.objects.filter(team=team, ad_hoc_key=key).first()
        if concurrent is None:
            raise
        return concurrent
