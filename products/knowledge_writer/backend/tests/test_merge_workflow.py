import os
import hmac
import json

import pytest
from unittest.mock import patch

from django.core.cache import caches
from django.test import RequestFactory

from posthog.ingress.dispatch.dedup import INGRESS_DEDUP_CACHE_ALIAS
from posthog.ingress.dispatch.dispatcher import WebhookDispatcher
from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.ingress.dispatch.registry import ConsumerRegistry
from posthog.ingress.github.provider import SPECS, build_github_provider
from posthog.ingress.views import build_webhook_view
from posthog.models.integration import Integration

from products.knowledge_writer.backend.webhook_consumers import WEBHOOK_CONSUMERS

MERGE_COMMIT_SHA = "b" * 40
WEBHOOK_SECRET = "test-knowledge-writer-webhook-secret"
LINKED_INSTALLATION_ID = 1234
START_MERGE_CHECK = "products.knowledge_writer.backend.temporal.client.start_merge_check"
KNOWLEDGE_WRITER_ENABLED = "products.knowledge_writer.backend.settings.is_writer_enabled"


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
