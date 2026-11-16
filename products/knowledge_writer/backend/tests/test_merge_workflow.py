import os
import hmac
import json
from datetime import timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import caches
from django.test import RequestFactory
from django.utils import timezone

from temporalio.testing import ActivityEnvironment

from posthog.ingress.dispatch.dedup import INGRESS_DEDUP_CACHE_ALIAS
from posthog.ingress.dispatch.dispatcher import WebhookDispatcher
from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.ingress.dispatch.registry import ConsumerRegistry
from posthog.ingress.github.provider import SPECS, build_github_provider
from posthog.ingress.views import build_webhook_view
from posthog.models.integration import Integration

from products.knowledge_writer.backend.temporal.client import merge_check_workflow_id
from products.knowledge_writer.backend.temporal.reconcile_workflow import (
    PULL_REQUESTS_PER_PAGE,
    reconcile_merged_pull_requests_activity,
)
from products.knowledge_writer.backend.webhook_consumers import WEBHOOK_CONSUMERS

MERGE_COMMIT_SHA = "b" * 40
WEBHOOK_SECRET = "test-knowledge-writer-webhook-secret"
LINKED_INSTALLATION_ID = 1234
START_MERGE_CHECK = "products.knowledge_writer.backend.temporal.client.start_merge_check"
KNOWLEDGE_WRITER_ENABLED = "products.knowledge_writer.backend.settings.is_writer_enabled"
RECONCILE_MODULE = "products.knowledge_writer.backend.temporal.reconcile_workflow"


@pytest.fixture
def writer_env(team, user):
    Integration.objects.create(team=team, kind="github", integration_id=str(LINKED_INSTALLATION_ID), config={})
    with patch.dict(
        os.environ,
        {
            "KNOWLEDGE_WRITER_TEAM_ID": str(team.id),
            "KNOWLEDGE_WRITER_USER_ID": str(user.id),
            "KNOWLEDGE_WRITER_DOCS_REPOSITORY": "PostHog/posthog.com",
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


def _pull_request_delivery(
    *,
    action: str = "closed",
    merged_at: str | None = "2026-11-05T12:00:00Z",
    repository: str = "PostHog/posthog",
    base_ref: str = "master",
    installation_id: int = LINKED_INSTALLATION_ID,
) -> dict[str, object]:
    return {
        "action": action,
        "installation": {"id": installation_id},
        "repository": {"full_name": repository},
        "pull_request": {
            "number": 42,
            "merged_at": merged_at,
            "merge_commit_sha": MERGE_COMMIT_SHA,
            "base": {"ref": base_ref},
        },
    }


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
        pytest.param(_pull_request_delivery(), True, id="merged_into_master"),
        pytest.param(_pull_request_delivery(merged_at=None), False, id="closed_unmerged"),
        pytest.param(_pull_request_delivery(action="opened"), False, id="not_closed"),
        pytest.param(_pull_request_delivery(repository="PostHog/posthog.com"), False, id="other_repository"),
        pytest.param(_pull_request_delivery(base_ref="release"), False, id="other_base"),
        pytest.param(_pull_request_delivery(installation_id=9999), False, id="installation_not_linked"),
    ],
)
def test_a_signed_merged_pull_request_starts_the_merge_check(
    team, writer_env, github_webhook_view, delivery, starts_merge_check
) -> None:
    with (
        patch(KNOWLEDGE_WRITER_ENABLED, return_value=True),
        patch(START_MERGE_CHECK) as start_merge_check,
    ):
        response = _post_signed(github_webhook_view, delivery)

    assert response.status_code == 202
    if not starts_merge_check:
        start_merge_check.assert_not_called()
        return
    start_merge_check.assert_called_once_with(MERGE_COMMIT_SHA, team_id=team.id)


@pytest.mark.django_db
def test_a_redelivered_merge_starts_one_merge_check(team, writer_env, github_webhook_view) -> None:
    with (
        patch(KNOWLEDGE_WRITER_ENABLED, return_value=True),
        patch(START_MERGE_CHECK) as start_merge_check,
    ):
        for _ in range(2):
            assert _post_signed(github_webhook_view, _pull_request_delivery()).status_code == 202

    start_merge_check.assert_called_once_with(MERGE_COMMIT_SHA, team_id=team.id)


@pytest.mark.django_db
def test_the_merge_pushes_endpoint_is_gone(client, team, user, writer_env) -> None:
    client.force_login(user)

    response = client.post(
        f"/api/projects/{team.id}/knowledge_writer/merge_pushes/",
        {"commit_sha": MERGE_COMMIT_SHA},
        content_type="application/json",
    )

    assert response.status_code == 404


class ClosedPullRequestPages:
    def __init__(self, pages: list[list[dict[str, object]]]) -> None:
        self.pages = pages
        self.requested_pages: list[int] = []

    def api_request(self, method, path, *, endpoint, params=None, headers=None, priority=None):
        page = int(params["page"])
        self.requested_pages.append(page)
        response = MagicMock()
        response.json.return_value = self.pages[page - 1]
        return response


def _closed_pull_request(
    commit_sha: str, *, merged_hours_ago: float | None, updated_hours_ago: float
) -> dict[str, object]:
    now = timezone.now()
    merged_at = None if merged_hours_ago is None else (now - timedelta(hours=merged_hours_ago)).isoformat()
    return {
        "merged_at": merged_at,
        "merge_commit_sha": commit_sha,
        "updated_at": (now - timedelta(hours=updated_hours_ago)).isoformat(),
        "base": {"ref": "master"},
    }


@pytest.mark.django_db(transaction=True)
async def test_the_hourly_reconcile_starts_merge_checks_for_recent_merges_on_one_client(team, writer_env) -> None:
    recent_merges = ["1" * 40, "2" * 40]
    filler = [_closed_pull_request("3" * 40, merged_hours_ago=None, updated_hours_ago=1)] * (
        PULL_REQUESTS_PER_PAGE - len(recent_merges)
    )
    github = ClosedPullRequestPages(
        [
            [
                _closed_pull_request(recent_merges[0], merged_hours_ago=0.5, updated_hours_ago=0.5),
                *filler,
                _closed_pull_request(recent_merges[1], merged_hours_ago=2, updated_hours_ago=2),
            ],
            [_closed_pull_request("4" * 40, merged_hours_ago=5, updated_hours_ago=5)],
            [_closed_pull_request("5" * 40, merged_hours_ago=0.1, updated_hours_ago=0.1)],
        ]
    )
    temporal = MagicMock(start_workflow=AsyncMock())

    with (
        patch(KNOWLEDGE_WRITER_ENABLED, return_value=True),
        patch(f"{RECONCILE_MODULE}.source_repository_github", return_value=github),
        patch(f"{RECONCILE_MODULE}.async_connect", AsyncMock(return_value=temporal)) as async_connect,
    ):
        await ActivityEnvironment().run(reconcile_merged_pull_requests_activity)

    assert github.requested_pages == [1, 2]
    async_connect.assert_awaited_once()
    started_workflow_ids = [call.kwargs["id"] for call in temporal.start_workflow.await_args_list]
    assert started_workflow_ids == [merge_check_workflow_id(commit_sha) for commit_sha in recent_merges]
