from typing import Any

from django.utils.dateparse import parse_datetime

from posthog.github.installations import installation_team_ids
from posthog.github.pull_request_events import pr_state_for_action
from posthog.ph_client import ph_scoped_capture

from products.wizard.backend.facade.enums import WizardPullRequestState
from products.wizard.backend.logic.artifacts import store
from products.wizard.backend.logic.runs import store as run_store
from products.wizard.backend.observability.service import wizard_observability as run_observability

_FINISHED_STATES = (WizardPullRequestState.MERGED, WizardPullRequestState.CLOSED)


class PullRequestArtifactNotStoredError(Exception):
    """A PR closed before the run stored its artifact, which the handoff writes after opening the PR."""


def handle_pull_request_event(payload: dict[str, Any]) -> None:
    pull_request = payload.get("pull_request") or {}
    url = pull_request.get("html_url")
    state = pr_state_for_action(payload.get("action"), pull_request)
    updated_at = parse_datetime(pull_request.get("updated_at") or "")
    if not isinstance(url, str) or state is None or updated_at is None:
        return

    team_ids = tuple(installation_team_ids(payload))
    # GitHub assigned this URL when the worker opened the PR, so a look-alike branch name cannot match it.
    owner = store.find_pull_request_owner(team_ids, url) if team_ids else None
    if owner is None:
        if team_ids and WizardPullRequestState(state) in _FINISHED_STATES:
            raise PullRequestArtifactNotStoredError(url)
        return

    artifact = store.update_pull_request_state(
        team_id=owner.team_id,
        artifact_id=owner.artifact_id,
        state=WizardPullRequestState(state),
        updated_at=updated_at,
        merged_at=parse_datetime(pull_request.get("merged_at") or ""),
        closed_at=parse_datetime(pull_request.get("closed_at") or ""),
    )

    if artifact is not None and artifact.state in _FINISHED_STATES:
        with ph_scoped_capture() as capture:
            run_observability.pull_request_finished(run_store.get_run(owner.team_id, owner.run_id), artifact, capture)
