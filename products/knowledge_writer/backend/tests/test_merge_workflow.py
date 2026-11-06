import os
import hmac
import json
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import caches
from django.test import RequestFactory

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
    COMMITS_PER_PAGE,
    reconcile_merged_pull_requests_activity,
)
from products.knowledge_writer.backend.webhook_consumers import WEBHOOK_CONSUMERS
from products.knowledge_writer.merge_check.sources import LandedChange

MERGE_COMMIT_SHA = "b" * 40
PARENT_COMMIT_SHA = "a" * 40
LANDED = LandedChange(repository="PostHog/posthog", after=MERGE_COMMIT_SHA)
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


def _push_delivery(
    *,
    ref: str = "refs/heads/master",
    repository: str = "PostHog/posthog",
    is_private: bool = False,
    deleted: bool = False,
    installation_id: int = LINKED_INSTALLATION_ID,
) -> dict[str, object]:
    return {
        "ref": ref,
        "before": PARENT_COMMIT_SHA,
        "after": MERGE_COMMIT_SHA,
        "deleted": deleted,
        "installation": {"id": installation_id},
        "repository": {"full_name": repository, "default_branch": "master", "private": is_private},
    }


def _post_signed(view, payload: dict[str, object], *, delivery_id: str = "delivery-1"):
    body = json.dumps(payload).encode("utf-8")
    request = RequestFactory().post(
        "/webhooks/github/",
        data=body,
        content_type="application/json",
        headers={
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": "sha256=" + hmac.digest(WEBHOOK_SECRET.encode(), body, "sha256").hex(),
        },
    )
    return view(request)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "delivery, starts_merge_check",
    [
        pytest.param(_push_delivery(), True, id="pushed_to_the_default_branch"),
        pytest.param(_push_delivery(ref="refs/heads/stack/parent-branch"), False, id="pushed_to_another_branch"),
        pytest.param(_push_delivery(deleted=True), False, id="default_branch_deleted"),
        pytest.param(_push_delivery(is_private=True), False, id="private_repository"),
        pytest.param(_push_delivery(repository="PostHog/posthog.com"), False, id="unlisted_repository"),
        pytest.param(_push_delivery(installation_id=9999), False, id="installation_not_linked"),
    ],
)
def test_a_signed_default_branch_push_starts_the_merge_check(
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
    start_merge_check.assert_called_once_with(LANDED, team_id=team.id)


@pytest.mark.django_db
def test_a_redelivered_push_starts_one_merge_check(team, writer_env, github_webhook_view) -> None:
    with (
        patch(KNOWLEDGE_WRITER_ENABLED, return_value=True),
        patch(START_MERGE_CHECK) as start_merge_check,
    ):
        for _ in range(2):
            assert _post_signed(github_webhook_view, _push_delivery()).status_code == 202

    start_merge_check.assert_called_once_with(LANDED, team_id=team.id)


@pytest.mark.django_db
def test_the_merge_pushes_endpoint_is_gone(client, team, user, writer_env) -> None:
    client.force_login(user)

    response = client.post(
        f"/api/projects/{team.id}/knowledge_writer/merge_pushes/",
        {"commit_sha": MERGE_COMMIT_SHA},
        content_type="application/json",
    )

    assert response.status_code == 404


class DefaultBranchCommits:
    def __init__(self, commit_pages_by_repository: dict[str, list[list[dict[str, Any]]]]) -> None:
        self.commit_pages_by_repository = commit_pages_by_repository
        self.requested_pages: list[tuple[str, int]] = []

    def api_request(self, method, path, *, endpoint, params=None, headers=None, priority=None):
        response = MagicMock()
        repository = path.removeprefix("/repos/").removesuffix("/commits")
        if not path.endswith("/commits"):
            response.json.return_value = {"default_branch": "main", "private": repository.endswith("-js")}
            return response
        assert params["sha"] == "main"
        page = int(params["page"])
        self.requested_pages.append((repository, page))
        response.json.return_value = self.commit_pages_by_repository[repository][page - 1]
        return response


def _commit(commit_sha: str, *parent_shas: str) -> dict[str, Any]:
    return {"sha": commit_sha, "parents": [{"sha": parent_sha} for parent_sha in parent_shas]}


@pytest.mark.django_db(transaction=True)
async def test_the_hourly_reconcile_walks_each_public_default_branch_by_first_parent_on_one_client(
    team, writer_env
) -> None:
    head, merge_commit, older, side_branch, outside_window = ("1" * 40, "2" * 40, "3" * 40, "4" * 40, "5" * 40)
    filler = [_commit("6" * 40, "7" * 40)] * (COMMITS_PER_PAGE - 3)
    github = DefaultBranchCommits(
        {
            "PostHog/posthog": [
                [
                    _commit(head, merge_commit),
                    _commit(merge_commit, older, side_branch),
                    _commit(side_branch, older),
                    *filler,
                ],
                [_commit(older, outside_window)],
            ],
        }
    )
    temporal = MagicMock(start_workflow=AsyncMock())

    with (
        patch(KNOWLEDGE_WRITER_ENABLED, return_value=True),
        patch(f"{RECONCILE_MODULE}.docs_github", return_value=github),
        patch(f"{RECONCILE_MODULE}.async_connect", AsyncMock(return_value=temporal)) as async_connect,
    ):
        await ActivityEnvironment().run(reconcile_merged_pull_requests_activity)

    assert github.requested_pages == [("PostHog/posthog", 1), ("PostHog/posthog", 2)]
    async_connect.assert_awaited_once()
    started = [(call.kwargs["id"], call.args[1].repository) for call in temporal.start_workflow.await_args_list]
    assert started == [
        (merge_check_workflow_id(head), "PostHog/posthog"),
        (merge_check_workflow_id(merge_commit), "PostHog/posthog"),
        (merge_check_workflow_id(older), "PostHog/posthog"),
    ]
