import os
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache, caches
from django.test import RequestFactory

import requests
from temporalio.testing import ActivityEnvironment

from posthog.ingress.dispatch.dedup import INGRESS_DEDUP_CACHE_ALIAS
from posthog.ingress.dispatch.dispatcher import WebhookDispatcher
from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.ingress.dispatch.registry import ConsumerRegistry
from posthog.ingress.github.provider import SPECS, build_github_provider
from posthog.ingress.views import build_webhook_view
from posthog.models.integration import Integration
from posthog.redis import get_client
from posthog.token_bucket import Budget

from products.knowledge_writer.backend.temporal.client import merge_check_workflow_id
from products.knowledge_writer.backend.temporal.merge_workflow import (
    MergeCheckInputs,
    MergeCheckNotAdmitted,
    check_merge,
    merge_check_budget_key,
)
from products.knowledge_writer.backend.temporal.reconcile_workflow import (
    PULL_REQUESTS_PER_PAGE,
    reconcile_merged_pull_requests_activity,
    reconciled_at_cache_key,
)
from products.knowledge_writer.backend.webhook_consumers import WEBHOOK_CONSUMERS
from products.knowledge_writer.merge_check.deadline import CheckDeadlineExceeded
from products.knowledge_writer.merge_check.sources import LandedChange

MERGE_COMMIT_SHA = "b" * 40
PULL_REQUEST_NUMBER = 7
LANDED = LandedChange(repository="PostHog/posthog", after=MERGE_COMMIT_SHA, pull_request_number=PULL_REQUEST_NUMBER)
WEBHOOK_SECRET = "test-knowledge-writer-webhook-secret"
LINKED_INSTALLATION_ID = 1234
START_MERGE_CHECK = "products.knowledge_writer.backend.temporal.client.start_merge_check"
KNOWLEDGE_WRITER_ENABLED = "products.knowledge_writer.backend.settings.is_writer_enabled"
RECONCILE_MODULE = "products.knowledge_writer.backend.temporal.reconcile_workflow"
MERGE_WORKFLOW_MODULE = "products.knowledge_writer.backend.temporal.merge_workflow"


@pytest.fixture
def writer_env(team, user):
    Integration.objects.create(team=team, kind="github", integration_id=str(LINKED_INSTALLATION_ID), config={})
    with patch.dict(
        os.environ,
        {
            "KNOWLEDGE_WRITER_TEAM_ID": str(team.id),
            "KNOWLEDGE_WRITER_USER_ID": str(user.id),
            "KNOWLEDGE_WRITER_DOCS_REPOSITORY": "PostHog/posthog.com",
            "KNOWLEDGE_WRITER_SOURCE_REPOSITORIES": "PostHog/posthog, PostHog/posthog-js",
        },
    ):
        yield


@pytest.fixture
def github_webhook_view():
    reset_consumer_registry()
    caches[INGRESS_DEDUP_CACHE_ALIAS].clear()
    dispatcher = WebhookDispatcher(ConsumerRegistry(providers=SPECS, consumers=WEBHOOK_CONSUMERS))
    with (
        patch("posthog.ingress.views.get_dispatcher", return_value=dispatcher),
        patch("posthog.credentials_service.instance_settings.get_instance_setting", return_value=WEBHOOK_SECRET),
    ):
        yield build_webhook_view(build_github_provider("posthog"))
    reset_consumer_registry()
    caches[INGRESS_DEDUP_CACHE_ALIAS].clear()


def _merged_pull_request_delivery(
    *,
    action: str = "closed",
    is_merged: bool = True,
    repository: str = "PostHog/posthog",
    is_private: bool = False,
    installation_id: int | None = LINKED_INSTALLATION_ID,
) -> dict[str, object]:
    delivery: dict[str, object] = {
        "action": action,
        "pull_request": {
            "number": PULL_REQUEST_NUMBER,
            "title": "feat: add flag banner",
            "html_url": f"https://github.com/{repository}/pull/{PULL_REQUEST_NUMBER}",
            "merged": is_merged,
            "merged_at": "2026-11-09T12:00:00Z" if is_merged else None,
            "merge_commit_sha": MERGE_COMMIT_SHA,
            "base": {"ref": "stack/parent-branch"},
        },
        "repository": {"full_name": repository, "default_branch": "master", "private": is_private},
    }
    if installation_id is not None:
        delivery["installation"] = {"id": installation_id}
    return delivery


def _post_signed(view, payload: dict[str, object], *, delivery_id: str = "delivery-1"):
    body = json.dumps(payload).encode("utf-8")
    request = RequestFactory().post(
        "/webhooks/github/",
        data=body,
        content_type="application/json",
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": "sha256=" + hmac.digest(WEBHOOK_SECRET.encode(), body, "sha256").hex(),
        },
    )
    return view(request)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "delivery, starts_merge_check",
    [
        pytest.param(_merged_pull_request_delivery(), True, id="merged_into_a_stack_parent_branch"),
        pytest.param(_merged_pull_request_delivery(is_merged=False), False, id="closed_without_merging"),
        pytest.param(_merged_pull_request_delivery(action="synchronize"), False, id="not_closed"),
        pytest.param(_merged_pull_request_delivery(is_private=True), False, id="private_repository"),
        pytest.param(_merged_pull_request_delivery(repository="PostHog/posthog.com"), False, id="unlisted_repository"),
        pytest.param(_merged_pull_request_delivery(installation_id=None), False, id="no_installation"),
    ],
)
def test_a_signed_merged_pull_request_starts_the_merge_check(
    team, writer_env, github_webhook_view, delivery, starts_merge_check
) -> None:
    with (
        patch(KNOWLEDGE_WRITER_ENABLED, return_value=True) as is_writer_enabled,
        patch(START_MERGE_CHECK) as start_merge_check,
    ):
        response = _post_signed(github_webhook_view, delivery)

    assert response.status_code == 202
    is_writer_enabled.assert_not_called()
    if not starts_merge_check:
        start_merge_check.assert_not_called()
        return
    start_merge_check.assert_called_once_with(LANDED, team_id=team.id, installation_id=str(LINKED_INSTALLATION_ID))


@pytest.mark.django_db
def test_a_redelivered_merged_pull_request_starts_one_merge_check(team, writer_env, github_webhook_view) -> None:
    with (
        patch(KNOWLEDGE_WRITER_ENABLED, return_value=True),
        patch(START_MERGE_CHECK) as start_merge_check,
    ):
        for _ in range(2):
            assert _post_signed(github_webhook_view, _merged_pull_request_delivery()).status_code == 202

    start_merge_check.assert_called_once_with(LANDED, team_id=team.id, installation_id=str(LINKED_INSTALLATION_ID))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "installation_id, pull_request_number, is_writer_enabled, reads_github, recorded_reasons",
    [
        pytest.param(
            str(LINKED_INSTALLATION_ID),
            PULL_REQUEST_NUMBER,
            True,
            True,
            ("merge_check_failed", "no_docs_github"),
            id="linked_installation",
        ),
        pytest.param("9999", PULL_REQUEST_NUMBER, True, False, ("not_admitted", None), id="installation_not_linked"),
        pytest.param(
            str(LINKED_INSTALLATION_ID), PULL_REQUEST_NUMBER, False, False, ("not_admitted", None), id="writer_disabled"
        ),
        pytest.param(
            None,
            PULL_REQUEST_NUMBER,
            False,
            True,
            ("merge_check_failed", "no_docs_github"),
            id="started_by_the_reconcile",
        ),
        pytest.param(
            None,
            None,
            False,
            False,
            ("merge_check_failed", "no_pull_request_number"),
            id="started_without_a_pull_request_number",
        ),
    ],
)
def test_a_merge_check_reads_github_only_for_a_numbered_pull_request_of_the_linked_writer(
    team, writer_env, installation_id, pull_request_number, is_writer_enabled, reads_github, recorded_reasons
) -> None:
    inputs = MergeCheckInputs(
        commit_sha=MERGE_COMMIT_SHA,
        team_id=team.id,
        pull_request_number=pull_request_number,
        installation_id=installation_id,
    )
    with (
        patch(KNOWLEDGE_WRITER_ENABLED, return_value=is_writer_enabled),
        patch(f"{MERGE_WORKFLOW_MODULE}.docs_github", return_value=None) as docs_github,
        patch(f"{MERGE_WORKFLOW_MODULE}.intake.submit") as submit,
    ):
        check_merge(inputs, is_final_attempt=True)

    assert docs_github.called == reads_github
    verdict = submit.call_args.args[0]
    assert (verdict.reason, verdict.failure_reason) == recorded_reasons


@pytest.mark.django_db
def test_a_team_past_its_check_budget_records_capped_merges_without_reading_github(team, writer_env) -> None:
    inputs = MergeCheckInputs(commit_sha=MERGE_COMMIT_SHA, team_id=team.id, pull_request_number=PULL_REQUEST_NUMBER)
    get_client().delete(merge_check_budget_key(team.id))
    with (
        patch(f"{MERGE_WORKFLOW_MODULE}.MERGE_CHECK_BUDGET", Budget(burst=1, per_hour=1)),
        patch(f"{MERGE_WORKFLOW_MODULE}.docs_github", side_effect=[MagicMock(), None]) as docs_github,
        patch(f"{MERGE_WORKFLOW_MODULE}.judge_client", return_value=MagicMock()),
        patch(f"{MERGE_WORKFLOW_MODULE}.run_merge_check", side_effect=CheckDeadlineExceeded()),
        patch(f"{MERGE_WORKFLOW_MODULE}.intake.submit") as submit,
    ):
        with pytest.raises(CheckDeadlineExceeded):
            check_merge(inputs, is_final_attempt=False)
        check_merge(inputs, is_final_attempt=True)
        check_merge(inputs, is_final_attempt=True)

    assert docs_github.call_count == 2
    assert [call.args[0].reason for call in submit.call_args_list] == ["merge_check_failed", "check_capped"]


@pytest.mark.django_db
def test_a_refused_delivery_is_retried_before_its_final_attempt(team, writer_env) -> None:
    inputs = MergeCheckInputs(commit_sha=MERGE_COMMIT_SHA, team_id=team.id, installation_id=str(LINKED_INSTALLATION_ID))
    with patch(KNOWLEDGE_WRITER_ENABLED, return_value=False), pytest.raises(MergeCheckNotAdmitted):
        check_merge(inputs, is_final_attempt=False)


@pytest.mark.django_db
def test_the_merge_pushes_endpoint_is_gone(client, team, user, writer_env) -> None:
    client.force_login(user)

    response = client.post(
        f"/api/projects/{team.id}/knowledge_writer/merge_pushes/",
        {"commit_sha": MERGE_COMMIT_SHA},
        content_type="application/json",
    )

    assert response.status_code == 404


class ClosedPullRequests:
    def __init__(self, pull_request_pages_by_repository: dict[str, list[list[dict[str, Any]]]]) -> None:
        self.pull_request_pages_by_repository = pull_request_pages_by_repository
        self.requested_pages: list[tuple[str, int]] = []

    def api_request(self, method, path, *, endpoint, params=None, headers=None, priority=None):
        response = MagicMock()
        repository = path.removeprefix("/repos/").removesuffix("/pulls")
        if repository not in self.pull_request_pages_by_repository and not repository.endswith("-js"):
            response.raise_for_status.side_effect = requests.HTTPError("404 Not Found", response=response)
            return response
        if not path.endswith("/pulls"):
            response.json.return_value = {"default_branch": "main", "private": repository.endswith("-js")}
            return response
        assert (params["state"], params["sort"], params["direction"]) == ("closed", "updated", "desc")
        page = int(params["page"])
        self.requested_pages.append((repository, page))
        response.json.return_value = self.pull_request_pages_by_repository[repository][page - 1]
        return response


RECONCILE_STARTED_AT = datetime(2026, 11, 9, 18, 0, tzinfo=UTC)


def _closed_pull_request(number: int, *, merged_hours_ago: float | None, updated_hours_ago: float) -> dict[str, Any]:
    merged_at = None if merged_hours_ago is None else RECONCILE_STARTED_AT - timedelta(hours=merged_hours_ago)
    return {
        "number": number,
        "title": "feat: add flag banner",
        "html_url": f"https://github.com/PostHog/posthog/pull/{number}",
        "merged_at": merged_at and merged_at.isoformat().replace("+00:00", "Z"),
        "updated_at": (RECONCILE_STARTED_AT - timedelta(hours=updated_hours_ago)).isoformat().replace("+00:00", "Z"),
        "merge_commit_sha": f"{number:040d}",
    }


@pytest.mark.parametrize(
    "hours_since_last_reconcile, checked_pull_request_numbers",
    [
        pytest.param(None, [1, 3], id="nothing saved looks back three hours"),
        pytest.param(6, [1, 3, 4], id="an outage looks back to the last reconcile"),
    ],
)
@pytest.mark.django_db(transaction=True)
async def test_the_hourly_reconcile_starts_a_numbered_check_for_each_pull_request_merged_since_the_last_reconcile(
    team, writer_env, hours_since_last_reconcile, checked_pull_request_numbers
) -> None:
    cache.delete(reconciled_at_cache_key("PostHog/posthog"))
    if hours_since_last_reconcile is not None:
        last_reconciled_at = RECONCILE_STARTED_AT - timedelta(hours=hours_since_last_reconcile)
        cache.set(reconciled_at_cache_key("PostHog/posthog"), last_reconciled_at)
    recently_updated = [
        _closed_pull_request(1, merged_hours_ago=1, updated_hours_ago=0.5),
        _closed_pull_request(2, merged_hours_ago=None, updated_hours_ago=1),
        _closed_pull_request(3, merged_hours_ago=2, updated_hours_ago=2),
        _closed_pull_request(4, merged_hours_ago=8, updated_hours_ago=2),
        _closed_pull_request(5, merged_hours_ago=72, updated_hours_ago=2),
    ]
    filler = [_closed_pull_request(6, merged_hours_ago=None, updated_hours_ago=2)] * (PULL_REQUESTS_PER_PAGE - 5)
    older_page = [_closed_pull_request(7, merged_hours_ago=10, updated_hours_ago=10)]
    github = ClosedPullRequests({"PostHog/posthog": [[*recently_updated, *filler], older_page]})
    temporal = MagicMock(start_workflow=AsyncMock())

    with (
        patch.dict(
            os.environ, {"KNOWLEDGE_WRITER_SOURCE_REPOSITORIES": "PostHog/renamed, PostHog/posthog, PostHog/posthog-js"}
        ),
        patch(KNOWLEDGE_WRITER_ENABLED, return_value=True),
        patch(f"{RECONCILE_MODULE}.docs_github", return_value=github),
        patch(f"{RECONCILE_MODULE}.async_connect", AsyncMock(return_value=temporal)) as async_connect,
        time_machine.travel(RECONCILE_STARTED_AT, tick=False),
    ):
        await ActivityEnvironment().run(reconcile_merged_pull_requests_activity)
        # The entry expires a day after the frozen time, so read it before the clock returns to now.
        reconciled_at = cache.get(reconciled_at_cache_key("PostHog/posthog"))

    assert github.requested_pages == [("PostHog/posthog", 1), ("PostHog/posthog", 2)]
    async_connect.assert_awaited_once()
    started = [
        (call.kwargs["id"], call.args[1].repository, call.args[1].pull_request_number)
        for call in temporal.start_workflow.await_args_list
    ]
    assert started == [
        (merge_check_workflow_id(f"{number:040d}"), "PostHog/posthog", number)
        for number in checked_pull_request_numbers
    ]
    assert reconciled_at == RECONCILE_STARTED_AT
