"""On-demand scout fleet materialization, and the telemetry that makes it measurable.

The body of the `signals/scout/configs/sync/` action minus its HTTP shell: resolve the team's
seed posture and holdback from one flag read, reconcile the canonical skills, register a config
for every scout missing one, and record what the pass actually did.

The recording is the reason this module exists. `sync_canonical_skills` returns a full
`SyncResult` and the endpoint discarded it, so the only trace of a materialization was a server
log line. Nothing could count the projects a tab-open rescued, the scouts a sync seeded, or how
long a cold project waited for its catalog. Every sync now captures
`signals_scout_fleet_synced`, zero counts included — a no-op sync is the denominator for "how
often does opening the tab find work to do".
"""

from __future__ import annotations

import time
import logging

import posthoganalytics

from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.config_registry import register_missing_configs
from products.signals.backend.scout_harness.lazy_seed import SyncResult, canonical_skill_names, sync_canonical_skills
from products.signals.backend.scout_harness.skill_loader import SIGNALS_SCOUT_SKILL_PREFIX
from products.signals.backend.scout_harness.team_limits import resolve_sync_seed_inputs

logger = logging.getLogger(__name__)

FLEET_SYNCED_EVENT = "signals_scout_fleet_synced"

# Which surface asked for the materialization. The whole point of the `surface` dimension is to
# separate a fleet the coordinator was going to deliver anyway from one a person's tab-open
# rescued, so an unlabelled caller is recorded as unknown rather than folded into a real surface.
SYNC_SURFACES = ("roster", "desktop", "wizard")
UNKNOWN_SURFACE = "unknown"

# A prune reaping more than half the canonical fleet, and at least this many scouts, is not a
# retirement. Canonical scouts retire one or two at a time; a reap that size means the sync read
# a fleet the deploy did not actually ship, and it has just tombstoned live scouts on every
# project that opened the tab. The floor keeps a one-scout fleet from crying wolf.
MASS_PRUNE_FLOOR = 3


class UnexpectedScoutFleetPrune(Exception):
    """One fleet sync tombstoned more canonical scouts than a retirement explains.

    Captured, never raised at the caller: by the time the count exists the rows are already
    tombstoned, so this is a detector, not a guard. It rides into error tracking because the
    mass-prune failure mode has to be noticed within a deploy, not found later in an event
    breakdown.
    """


def materialize_scout_fleet(team: Team, *, surface: str | None = None) -> set[str]:
    """Reconcile `team`'s scout fleet against the canonical skills on disk, and record the outcome.

    Returns the team's holdback denylist so the caller can keep withheld scouts out of the fleet
    it answers with.

    `prune=True` puts this on the same terms as the coordinator tick: a scout retired from
    `products/signals/skills/` is tombstoned on the team instead of lingering as a live row the
    fleet UI keeps listing. The reap only touches rows the harness seeded and the team never
    edited, so a hand-authored or forked scout of the same name survives it.
    """
    # Timed from the first read, not from the reconcile: `duration_ms` is what a cold project
    # waits with its roster under a skeleton, and the flag read is part of that wait.
    started_at = time.monotonic()
    # Resolve the holdback denylist and the launch seed posture from a single flag read so they
    # can't disagree if the flag changes mid-request (the coordinator reads once and threads the
    # snapshot too). Holdback: a held-back scout can't be seeded or enabled by a manual fleet
    # materialization. Posture: seed the same launch shape the coordinator applies, so a
    # self-serve materialization doesn't bypass the launch cost posture by enabling the fleet.
    seed_config_layers, withheld = resolve_sync_seed_inputs(team.id)
    configs_before = _config_skill_names(team.id)
    result = sync_canonical_skills(team, prune=True, withheld_skill_names=withheld)
    register_missing_configs(team.id, seed_config_layers, withheld_skill_names=withheld)
    configs_after = _config_skill_names(team.id)
    _capture_fleet_synced(
        team=team,
        surface=surface,
        result=result,
        configs_before=configs_before,
        configs_after=configs_after,
        withheld_count=len(withheld),
        duration_ms=round((time.monotonic() - started_at) * 1000),
    )
    return withheld


def _config_skill_names(team_id: int) -> set[str]:
    return set(SignalScoutConfig.objects.for_team(team_id).values_list("skill_name", flat=True))


def _is_mass_prune(pruned_count: int) -> bool:
    fleet_size = len([name for name in canonical_skill_names() if name.startswith(SIGNALS_SCOUT_SKILL_PREFIX)])
    return pruned_count >= MASS_PRUNE_FLOOR and pruned_count > fleet_size // 2


def _capture_fleet_synced(
    *,
    team: Team,
    surface: str | None,
    result: SyncResult,
    configs_before: set[str],
    configs_after: set[str],
    withheld_count: int,
    duration_ms: int,
) -> None:
    """Emit the fleet-synced analytics event, and trip the mass-prune wire when the reap is absurd.

    Best-effort on both halves: a materialization that worked must not fail because its telemetry
    did. `was_empty` paired with `fleet_size` is the rescue metric — a project that had no configs
    and now has a fleet is one the coordinator had not reached.
    """
    pruned_count = len(result.pruned_skill_names)
    unexpected_prune = _is_mass_prune(pruned_count)
    if unexpected_prune:
        _trip_mass_prune_wire(team=team, surface=surface, pruned_skill_names=result.pruned_skill_names)
    try:
        organization = team.organization
        posthoganalytics.capture(
            event=FLEET_SYNCED_EVENT,
            distinct_id=str(team.uuid),
            properties={
                "team_id": team.id,
                "organization_id": str(organization.id),
                "surface": surface or UNKNOWN_SURFACE,
                "created_count": len(result.created_skill_names),
                "updated_count": len(result.updated_skill_names),
                "diverged_count": len(result.diverged_skill_names),
                "tombstoned_count": len(result.tombstoned_skill_names),
                "pruned_count": pruned_count,
                "configs_registered_count": len(configs_after - configs_before),
                "withheld_count": withheld_count,
                "fleet_size": len(configs_after),
                "was_empty": not configs_before,
                # Set when the canonical fleet could not be read at all, which is the one branch
                # where every count above is zero for a reason other than "nothing to do".
                "skipped_reason": result.skipped_reason,
                "unexpected_prune": unexpected_prune,
                "duration_ms": duration_ms,
            },
            groups=groups(organization, team),
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to capture fleet-synced analytics event",
            extra={"team_id": team.id},
        )


def _trip_mass_prune_wire(*, team: Team, surface: str | None, pruned_skill_names: tuple[str, ...]) -> None:
    try:
        capture_exception(
            UnexpectedScoutFleetPrune(
                f"Scout fleet sync tombstoned {len(pruned_skill_names)} canonical scouts in one pass"
            ),
            additional_properties={
                "team_id": team.id,
                "surface": surface or UNKNOWN_SURFACE,
                "pruned_count": len(pruned_skill_names),
                "pruned_skills": list(pruned_skill_names),
            },
        )
    except Exception:
        logger.warning(
            "signals_scout: failed to report an unexpected fleet prune",
            extra={"team_id": team.id, "pruned_skills": list(pruned_skill_names)},
        )
