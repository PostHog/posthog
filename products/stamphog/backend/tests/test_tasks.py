from typing import Any

import pytest
from unittest.mock import patch

from posthog.models.scoping import team_scope

from products.stamphog.backend.facade.enums import ReviewRunStatus
from products.stamphog.backend.models import PullRequest, ReviewRun, StamphogRepoConfig
from products.stamphog.backend.tasks.tasks import process_pull_request_event
from products.stamphog.backend.tests.conftest import PRODUCT_DATABASES

REPO = "acme/widgets"
INSTALLATION_ID = "1001"


def _pr_payload(
    *,
    action: str = "opened",
    installation_id: str = INSTALLATION_ID,
    repo: str = REPO,
    pr_number: int = 42,
    head_sha: str = "sha-1",
    head_branch: str = "feature-branch",
) -> dict[str, Any]:
    return {
        "action": action,
        "installation": {"id": installation_id},
        "repository": {"full_name": repo},
        "pull_request": {
            "number": pr_number,
            "html_url": f"https://github.com/{repo}/pull/{pr_number}",
            "head": {"sha": head_sha, "ref": head_branch},
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
        return StamphogRepoConfig.objects.create(team_id=team.id, repository=REPO, installation_id=INSTALLATION_ID)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_queues_review_run_and_starts_workflow(team, repo_config):
    mock_execute = _run_task(_pr_payload(head_branch="feat/x"), "delivery-1", team.id)

    with team_scope(team.id):
        run = ReviewRun.objects.select_related("pull_request").get()
    assert run.status == ReviewRunStatus.QUEUED
    assert run.pull_request.pr_number == 42
    assert run.pull_request.head_branch == "feat/x"
    assert run.pull_request.repo_config_id == repo_config.id
    mock_execute.assert_called_once_with(review_run_id=str(run.id), team_id=team.id)


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
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
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_unmatched_events_create_no_review_run(team, repo_config, mutate_payload):
    payload = mutate_payload(_pr_payload())
    mock_execute = _run_task(payload, "delivery-noop", team.id)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 0
    mock_execute.assert_not_called()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_disabled_repo_config_is_a_noop(team, repo_config):
    with team_scope(team.id):
        repo_config.enabled = False
        repo_config.save()

    mock_execute = _run_task(_pr_payload(), "delivery-disabled", team.id)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 0
    mock_execute.assert_not_called()


@pytest.mark.parametrize(
    "enabled,digest_enabled,expect_capture",
    [(False, True, True), (True, False, True), (False, False, False)],
    ids=["digest_only_captures", "review_only_captures", "fully_disabled_drops"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_merge_capture_gates_on_either_flag(team, repo_config, enabled, digest_enabled, expect_capture):
    # A merged PR must be captured whenever review OR digest is on — a digest-only repo (review off,
    # digest on) still needs its merges recorded or the daily digest has nothing to send. Only a fully
    # disabled repo drops the merge. Regression: the merge path used to gate on review `enabled` alone.
    with team_scope(team.id):
        repo_config.enabled = enabled
        repo_config.digest_enabled = digest_enabled
        repo_config.save()

    payload = _pr_payload(action="closed")
    payload["pull_request"]["merged"] = True
    payload["pull_request"]["merged_at"] = "2026-07-14T00:00:00Z"
    _run_task(payload, f"delivery-merged-{enabled}-{digest_enabled}", team.id)

    with team_scope(team.id):
        captured = PullRequest.objects.filter(repo_config=repo_config, pr_number=42, merged_at__isnull=False).exists()
    assert captured is expect_capture


@pytest.mark.parametrize(
    "existing_status,expect_restart",
    [
        (ReviewRunStatus.QUEUED, True),
        (ReviewRunStatus.REVIEWING, False),
        (ReviewRunStatus.COMPLETED, False),
    ],
    ids=["queued_run_restarts", "reviewing_run_noop", "completed_run_noop"],
)
@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_redelivery_restarts_only_a_still_queued_run(team, repo_config, existing_status, expect_restart):
    # A run committed by an earlier delivery whose workflow never started (Temporal was briefly down)
    # stays QUEUED. The redelivery/Celery-retry hits the unique delivery_id, and must restart that
    # run instead of logging "already processed" and silently dropping the PR. A run already past
    # QUEUED has a live/finished workflow, so its redelivery stays a plain no-op.
    with team_scope(team.id):
        pr_obj = PullRequest.objects.create(team_id=team.id, repo_config=repo_config, pr_number=42)
        ReviewRun.objects.create(
            team_id=team.id,
            pull_request=pr_obj,
            head_sha="sha-1",
            delivery_id="delivery-redelivered",
            status=existing_status,
        )

    mock_execute = _run_task(_pr_payload(head_sha="sha-1"), "delivery-redelivered", team.id)

    with team_scope(team.id):
        assert ReviewRun.objects.count() == 1  # no second run created for the duplicate delivery
        surviving = ReviewRun.objects.get()
        assert surviving.status == existing_status  # not superseded by its own redelivery
    if expect_restart:
        mock_execute.assert_called_once_with(review_run_id=str(surviving.id), team_id=team.id)
    else:
        mock_execute.assert_not_called()


@pytest.mark.django_db(databases=PRODUCT_DATABASES)
def test_synchronize_supersedes_prior_non_terminal_run_but_not_terminal_ones(team, repo_config):
    _run_task(_pr_payload(action="opened", head_sha="sha-1"), "delivery-open", team.id)
    with team_scope(team.id):
        first_run = ReviewRun.objects.get()
        pull_request = PullRequest.objects.get(pr_number=42)
        completed_run = ReviewRun.objects.create(
            team_id=team.id,
            pull_request=pull_request,
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
