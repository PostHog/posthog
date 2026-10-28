"""The user a scout run acts as.

The runner and the pre-check both resolve it here. The pre-check reads project data as this user,
so it can read the same tables the run can read, and no more.
"""

from __future__ import annotations

from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.skill_loader import resolve_scout_acting_user_id


@frozen
class ScoutActingUser:
    user_id: int
    # True when no scout-level identity resolved and the team-level default stands in. That member
    # never approved the scout's write grant.
    is_team_fallback: bool = False


def resolve_scout_run_acting_user(
    team: Team, skill_name: str, config: SignalScoutConfig | None, *, trial_user_id: int | None = None
) -> ScoutActingUser | None:
    """The trial's user, else the scout's own identity, else the team-level default.

    Returns None when no member of the project can act, in which case the run does not start.
    """
    # Deferred: the pre-check imports this module, and the scout scheduler imports the pre-check
    # while the temporal package that defines this function is still loading.
    from products.signals.backend.temporal.agentic import resolve_acting_user_id_for_team  # noqa: PLC0415

    if trial_user_id is not None:
        return ScoutActingUser(user_id=trial_user_id)
    user_id = resolve_scout_acting_user_id(team, skill_name, config)
    if user_id is not None:
        return ScoutActingUser(user_id=user_id)
    fallback_id = resolve_acting_user_id_for_team(team.id)
    if fallback_id is None:
        return None
    return ScoutActingUser(user_id=fallback_id, is_team_fallback=True)
