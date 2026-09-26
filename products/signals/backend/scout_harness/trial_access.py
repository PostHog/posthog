from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from rest_framework import exceptions
from rest_framework.request import Request

from posthog.auth import OAuthAccessTokenAuthentication

from products.signals.backend.models import SignalScoutRun
from products.signals.backend.scout_harness.trial_launch import (
    ScoutTrialLaunchError,
    bound_trial_run,
    load_trial_context,
)
from products.signals.backend.scout_harness.trial_reads import SavedScoutReads
from products.signals.backend.scout_harness.trial_state import ScoutTrialStateError, ScoutTrialStore


def trial_run_for_request(request: Request, team_id: int) -> SignalScoutRun | None:
    authenticator = request.successful_authenticator
    if not isinstance(authenticator, OAuthAccessTokenAuthentication):
        return None
    token = authenticator.access_token
    run = bound_trial_run(team_id, token.sandbox_task_id)
    carries_scope = "scout_experiment_internal:read" in (token.scope or "").split()
    if carries_scope != (run is not None):
        raise exceptions.PermissionDenied("The scout credential does not match its run.")
    return run


def trial_store_for_request(request: Request, team_id: int) -> ScoutTrialStore | None:
    run = trial_run_for_request(request, team_id)
    return ScoutTrialStore(run) if run is not None else None


def saved_reads_for_request(request: Request, team_id: int) -> SavedScoutReads | None:
    run = trial_run_for_request(request, team_id)
    if run is None:
        return None
    with trial_state_errors():
        return SavedScoutReads(load_trial_context(team_id, (run.metadata or {})["scout_trial"]["context_id"]))


@contextmanager
def trial_state_errors() -> Iterator[None]:
    try:
        yield
    except (ScoutTrialStateError, ScoutTrialLaunchError) as error:
        raise exceptions.ValidationError({"detail": str(error)}) from error
