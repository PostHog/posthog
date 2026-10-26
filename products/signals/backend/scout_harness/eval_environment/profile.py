from __future__ import annotations

from copy import deepcopy
from typing import cast

from django.db import transaction

from pydantic import JsonValue

from products.signals.backend.scout_harness.tools.profile import get_project_profile
from products.signals.backend.scout_harness.trial_access_policy import local_scout_trial_team
from products.signals.backend.scout_harness.trial_launch import load_trial_context
from products.signals.backend.scout_harness.trial_state import ScoutTrialStateError, ScoutTrialStore


def snapshot_project_profile(team_id: int) -> dict[str, JsonValue]:
    profile = get_project_profile(team_id=team_id, lazy_build=False)
    if profile is None:
        raise ScoutTrialStateError("Prepare a cached project profile before starting a local scout trial.")
    return cast(dict[str, JsonValue], profile.as_dict())


def local_trial_project_profile(store: ScoutTrialStore, *, force_refresh: bool) -> dict[str, JsonValue]:
    if not local_scout_trial_team(store.run.team_id):
        raise ScoutTrialStateError(
            "Private project profiles are restricted to the configured local evaluation project."
        )
    if force_refresh:
        with transaction.atomic():
            profile = get_project_profile(team_id=store.run.team_id, force_refresh=True, lazy_build=False)
            # Discard the real builder's cache/prune writes and its queued on-commit surface refresh.
            transaction.set_rollback(True)
        if profile is None:
            raise ScoutTrialStateError("The local project profile refresh returned no profile.")
        body = cast(dict[str, JsonValue], profile.as_dict())
        store.capture_project_profile(body)
        return body
    saved = store.project_profile()
    if saved is not None:
        return saved
    context_id = (store.run.metadata or {}).get("scout_trial", {}).get("context_id")
    if not isinstance(context_id, str):
        raise ScoutTrialStateError("The local scout trial has no saved starting context.")
    context = load_trial_context(store.run.team_id, context_id)
    if context.project_profile is None:
        raise ScoutTrialStateError("This local trial has no saved project profile. Start a new trial.")
    return deepcopy(context.project_profile)
