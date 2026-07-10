from typing import Any

import pytest
from unittest.mock import patch

from posthog.models.scoping import team_scope

from products.stamphog.backend.facade.enums import ReviewRunStatus
from products.stamphog.backend.models import ReviewRun, StamphogRepoConfig
from products.stamphog.backend.tasks.tasks import process_pull_request_event

REPO = "acme/widgets"
INSTALLATION_ID = "1001"


def _pr_payload(
    *,
    action: str = "opened",
    installation_id: str = INSTALLATION_ID,
    repo: str = REPO,
    pr_number: int = 42,
    head_sha: str = "sha-1",
) -> dict[str, Any]:
    return {
        "action": action,
        "installation": {"id": installation_id},
        "repository": {"full_name": repo},
        "pull_request": {
            "number": pr_number,
            "html_url": f"https://github.com/{repo}/pull/{pr_number}",
            "head": {"sha": head_sha},
        },
    }


def _run_task(payload: dict[str, Any], delivery_id: str, team_id: int):
    # transaction.on_commit never fires on its own outside a real commit, so run it
    # inline; execute_stamphog_review_workflow is a Temporal network call and gets mocked.
    with (
        team_scope(team_id),
        patch("products.stamphog.backend.tasks.tasks.transaction.on_commit", side_effect=lambda fn: fn()),
        patch("products.stamphog.backend.tasks.tasks.execute_stamphog_review_workflow") as mock_execute,
    ):
        process_pull_request_event(payload, delivery_id)
    return mock_execute


@pytest.fixture
def repo_config(team):
    with team_scope(team.id):
        return StamphogRepoConfig.objects.create(team=team, repository=REPO, github_installation_id=INSTALLATION_ID)


@pytest.mark.django_db
def test_queues_review_run_and_starts_workflow(team, repo_config):
    mock_execute = _run_task(_pr_payload(), "delivery-1", team.id)

    with team_scope(team.id):
        run = ReviewRun.objects.get()
    assert run.status == ReviewRunStatus.QUEUED
    assert run.pr_number == 42
    assert run.repo_config_id == repo_config.id
    mock_execute.assert_called_once_with(review_run_id=str(run.id), team_id=team.id)


@pytest.mark.django_db
def test_duplicate_delivery_id_is_a_noop(team, repo_config):
    _run_task(_pr_payload(), "delivery-dup", team.id)
    mock_execute = _run_task(_pr_payload(), "delivery-dup", team.id)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 1
    mock_execute.assert_not_called()


@pytest.mark.parametrize(
    "mutate_payload",
    [
        lambda p: {**p, "installation": {"id": "unknown"}},
        lambda p: {**p, "repository": {"full_name": "acme/other-repo"}},
        lambda p: {**p, "action": "closed"},
        lambda p: {**p, "pull_request": {}},
    ],
    ids=["unknown_installation", "unknown_repo", "irrelevant_action", "missing_pr_number"],
)
@pytest.mark.django_db
def test_unmatched_events_create_no_review_run(team, repo_config, mutate_payload):
    payload = mutate_payload(_pr_payload())
    mock_execute = _run_task(payload, "delivery-noop", team.id)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 0
    mock_execute.assert_not_called()


@pytest.mark.django_db
def test_disabled_repo_config_is_a_noop(team, repo_config):
    with team_scope(team.id):
        repo_config.enabled = False
        repo_config.save()

    mock_execute = _run_task(_pr_payload(), "delivery-disabled", team.id)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 0
    mock_execute.assert_not_called()


@pytest.mark.django_db
def test_synchronize_supersedes_prior_non_terminal_run_but_not_terminal_ones(team, repo_config):
    _run_task(_pr_payload(action="opened", head_sha="sha-1"), "delivery-open", team.id)
    with team_scope(team.id):
        first_run = ReviewRun.objects.get()
        completed_run = ReviewRun.objects.create(
            team=team,
            repo_config=repo_config,
            pr_number=42,
            pr_url=f"https://github.com/{REPO}/pull/42",
            head_sha="sha-old",
            status=ReviewRunStatus.COMPLETED,
        )

    _run_task(_pr_payload(action="synchronize", head_sha="sha-2"), "delivery-sync", team.id)

    with team_scope(team.id):
        first_run.refresh_from_db()
        completed_run.refresh_from_db()
        new_run = ReviewRun.objects.exclude(id__in=[first_run.id, completed_run.id]).get()

    assert first_run.status == ReviewRunStatus.SUPERSEDED
    assert completed_run.status == ReviewRunStatus.COMPLETED
    assert new_run.status == ReviewRunStatus.QUEUED
    assert new_run.head_sha == "sha-2"
