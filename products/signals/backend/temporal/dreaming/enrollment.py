"""Force-enrollment of the mandatory dreaming scout for every signals-enabled team.

The Dreaming Agent is NOT an opt-in scout. Unlike the rest of the `signals-scout-*` fleet —
where a `SignalScoutConfig` row can be disabled per team — the dreaming scout is core and
mandatory: every team enrolled in signals always has it enabled.

We reuse the `SignalScoutConfig` row (keyed on the dreaming skill name) purely as the
per-team scheduling + `last_run_at` ledger the coordinator reads. ``force_enable_dreaming``
reasserts ``enabled=True`` on every tick, so even if someone flips it off (API, admin), the
next nightly tick turns it back on. This is the "can't be turned opt-in" guarantee.
"""

from __future__ import annotations

import logging

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.skill_loader import DREAMING_SKILL_NAME

logger = logging.getLogger(__name__)

__all__ = ["DREAMING_RUN_INTERVAL_MINUTES", "DREAMING_SKILL_NAME", "force_enable_dreaming"]

# The dreaming scout runs once per night. The coordinator's due-check honors this interval; a
# nightly schedule tick at a low-traffic hour does the actual cadence.
DREAMING_RUN_INTERVAL_MINUTES = 24 * 60


def force_enable_dreaming(team_id: int) -> SignalScoutConfig:
    """Ensure the dreaming scout config exists and is enabled for the team.

    Idempotent: creates the row on first call, and reasserts ``enabled=True`` and the nightly
    interval on every subsequent call so the dreaming scout can never be left disabled. Keyed
    on the canonical (parent) team via the explicit ``team_id`` kwarg.
    """
    config, created = SignalScoutConfig.all_teams.get_or_create(
        team_id=team_id,
        skill_name=DREAMING_SKILL_NAME,
        defaults={"enabled": True, "run_interval_minutes": DREAMING_RUN_INTERVAL_MINUTES},
    )
    # Reassert the mandatory posture on every call — the row may have been flipped off, or its
    # interval changed, between runs. `.update()` bypasses save() so this reassertion never
    # spams the activity log.
    if not created and (not config.enabled or config.run_interval_minutes != DREAMING_RUN_INTERVAL_MINUTES):
        SignalScoutConfig.all_teams.filter(pk=config.pk).update(
            enabled=True,
            run_interval_minutes=DREAMING_RUN_INTERVAL_MINUTES,
        )
        config.enabled = True
        config.run_interval_minutes = DREAMING_RUN_INTERVAL_MINUTES
        logger.info("dreaming: reasserted mandatory enablement", extra={"team_id": team_id})
    return config
