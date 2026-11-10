from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from unittest.mock import patch

from django.db.models import Q

from posthog.models import Team

from products.signals.backend import agent_run_requests
from products.signals.backend.facade.agent_sources import agent_source_registered
from products.signals.backend.models import SignalSourceConfig, SignalSpend
from products.signals.backend.trial.policy import TrialPolicy

__all__ = ["agent_runs_startable", "agent_source_registered", "claim_trial", "trial_incomplete_sources"]


@contextmanager
def agent_runs_startable(team: Team, *, product: str, type: str) -> Iterator[list[str]]:
    """Let `request_agent_run` accept requests for one source of the team, and start no workflow.

    Yields the ids of the passes whose workflow would have started, in order. For a product's tests
    of the code that hands its records to an agent: the request runs for real up to the workflow.
    """
    SignalSourceConfig.objects.update_or_create(
        team=team, source_product=product, source_type=type, defaults={"enabled": True}
    )
    dispatched: list[str] = []
    with (
        patch.object(agent_run_requests, "check_fleet_gates", return_value=None),
        patch.object(agent_run_requests, "check_spend_gates", return_value=None),
        patch.object(agent_run_requests, "dispatch_agent_run", side_effect=dispatched.append),
    ):
        yield dispatched


def claim_trial(*, team: Team, user_id: int) -> UUID:
    return TrialPolicy(team).claim(user_id=user_id).id


def trial_incomplete_sources(*, team: Team, grant_id: UUID) -> int:
    return (
        SignalSpend.objects.unscoped()
        .filter(trial_grant_id=grant_id, trial_grant__team_id=team.parent_team_id or team.id)
        .filter(Q(accounting_pending=True) | Q(accounting_failed=True))
        .count()
    )
