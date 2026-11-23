from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from unittest.mock import patch

from django.db.models import Q
from django.test import override_settings

from posthog.models import Team

from products.signals.backend.models import SignalSpend
from products.signals.backend.trial.policy import TrialPolicy

__all__ = ["claim_trial", "report_task_run_limits_payload", "trial_incomplete_sources"]


def claim_trial(*, team: Team, user_id: int) -> UUID:
    return TrialPolicy(team).claim(user_id=user_id).id


def trial_incomplete_sources(*, team: Team, grant_id: UUID) -> int:
    return (
        SignalSpend.objects.unscoped()
        .filter(trial_grant_id=grant_id, trial_grant__team_id=team.parent_team_id or team.id)
        .filter(Q(accounting_pending=True) | Q(accounting_failed=True))
        .count()
    )


@contextmanager
def report_task_run_limits_payload(region_config: dict) -> Iterator[None]:
    """Serve `region_config` as the US entry of the `signal-report-task-limits` flag payload."""
    with (
        override_settings(CLOUD_DEPLOYMENT="US"),
        patch("products.signals.backend.report_task_limits.read_flag_payload", return_value={"US": region_config}),
    ):
        yield
