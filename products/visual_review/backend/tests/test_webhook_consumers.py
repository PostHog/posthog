import hmac
import json
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache, caches
from django.db import OperationalError
from django.http.response import HttpResponseBase
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from posthog.ingress.contracts import WebhookDelivery
from posthog.ingress.dispatch.dedup import INGRESS_DEDUP_CACHE_ALIAS
from posthog.ingress.dispatch.dispatcher import WebhookDispatcher
from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.ingress.dispatch.registry import ConsumerRegistry
from posthog.ingress.github.provider import SPECS, build_github_provider
from posthog.ingress.views import build_webhook_view
from posthog.models.team.team import Team

from products.visual_review.backend.facade.enums import BaselineMode
from products.visual_review.backend.models import Repo
from products.visual_review.backend.tests.conftest import PRODUCT_DATABASES, VisualReviewTeamScopedTestMixin
from products.visual_review.backend.webhook_consumers import WEBHOOK_CONSUMERS

WEBHOOK_SECRET = "test-visual-review-webhook-secret"
GITHUB_REPO_ID = 4242
ENQUEUE = "products.visual_review.backend.tasks.tasks.advance_visual_review_baseline_ledger_after_push.apply_async"
FACADE_ADVANCE = "products.visual_review.backend.facade.api.advance_baseline_ledgers_after_push"


def _push(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ref": "refs/heads/master",
        "deleted": False,
        "repository": {"id": GITHUB_REPO_ID, "full_name": "org/app", "default_branch": "master"},
    }
    payload.update(overrides)
    return payload


class TestDefaultBranchPushFilter(SimpleTestCase):
    @parameterized.expand(
        [
            ("default_branch_push", _push(), True),
            ("another_branch", _push(ref="refs/heads/feature"), False),
            ("branch_delete", _push(deleted=True), False),
            ("tag_push", _push(ref="refs/tags/master"), False),
            ("no_repository_object", _push(repository="org/app"), False),
            (
                "repository_id_not_an_integer",
                _push(repository={"id": str(GITHUB_REPO_ID), "full_name": "org/app", "default_branch": "master"}),
                False,
            ),
        ]
    )
    def test_only_a_push_of_commits_to_the_default_branch_reaches_the_facade(
        self, _name: str, payload: dict[str, Any], reaches_facade: bool
    ) -> None:
        delivery = WebhookDelivery(
            provider="github",
            app="posthog",
            delivery_id="delivery-1",
            event_type="push",
            payload=payload,
            received_at=datetime.now(UTC),
            context={},
        )

        with patch(FACADE_ADVANCE) as advance:
            WEBHOOK_CONSUMERS[0].handler(delivery)

        assert advance.call_args_list == ([((GITHUB_REPO_ID,),)] if reaches_facade else [])


class TestDefaultBranchPushConsumer(VisualReviewTeamScopedTestMixin, BaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self) -> None:
        super().setUp()
        reset_consumer_registry()
        cache.clear()
        caches[INGRESS_DEDUP_CACHE_ALIAS].clear()
        self.addCleanup(reset_consumer_registry)
        self.addCleanup(cache.clear)
        self.addCleanup(caches[INGRESS_DEDUP_CACHE_ALIAS].clear)
        dispatcher = WebhookDispatcher(ConsumerRegistry(providers=SPECS, consumers=WEBHOOK_CONSUMERS))
        for patcher in (
            patch("posthog.ingress.views.get_dispatcher", return_value=dispatcher),
            patch("posthog.credentials_service.instance_settings.get_instance_setting", return_value=WEBHOOK_SECRET),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.view = build_webhook_view(build_github_provider("posthog"))

    def _post(self, payload: dict[str, Any]) -> HttpResponseBase:
        body = json.dumps(payload).encode("utf-8")
        request = RequestFactory().post(
            "/webhooks/github/",
            data=body,
            content_type="application/json",
            headers={
                "X-GitHub-Event": "push",
                "X-GitHub-Delivery": "delivery-1",
                "X-Hub-Signature-256": "sha256=" + hmac.digest(WEBHOOK_SECRET.encode(), body, "sha256").hex(),
            },
        )
        return self.view(request)

    def _repo(self, team_id: int, mode: BaselineMode, github_repo_id: int = GITHUB_REPO_ID) -> Repo:
        return Repo.objects.create(
            team_id=team_id, repo_external_id=github_repo_id, repo_full_name="org/app", baseline_mode=mode
        )

    @parameterized.expand(
        [
            ("ledger_mode", BaselineMode.LEDGER, _push(), True),
            ("shadow_mode", BaselineMode.SHADOW, _push(), True),
            ("yaml_mode", BaselineMode.YAML, _push(), False),
            (
                "unknown_repo",
                BaselineMode.LEDGER,
                _push(repository={"id": GITHUB_REPO_ID + 1, "full_name": "org/other", "default_branch": "master"}),
                False,
            ),
        ]
    )
    def test_only_a_default_branch_push_of_a_moving_ledger_enqueues_an_advance(
        self, _name: str, mode: BaselineMode, payload: dict[str, Any], enqueues: bool
    ) -> None:
        repo = self._repo(self.team.id, mode)

        with patch(ENQUEUE) as enqueue:
            response = self._post(payload)

        assert response.status_code == 202
        enqueued = [call.kwargs["args"] for call in enqueue.call_args_list]
        assert enqueued == ([(self.team.id, str(repo.id))] if enqueues else [])

    def test_each_project_that_follows_the_repository_gets_its_own_advance(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        mine = self._repo(self.team.id, BaselineMode.LEDGER)
        theirs = self._repo(other_team.id, BaselineMode.SHADOW)

        with patch(ENQUEUE) as enqueue:
            self._post(_push())

        enqueued = sorted(call.kwargs["args"] for call in enqueue.call_args_list)
        assert enqueued == sorted([(self.team.id, str(mine.id)), (other_team.id, str(theirs.id))])

    def test_a_failed_lookup_still_answers_the_shared_endpoint_and_enqueues_nothing(self) -> None:
        with (
            patch(
                "products.visual_review.backend.logic.ledger_advance.repos_with_ledger",
                side_effect=OperationalError("canceling statement due to statement timeout"),
            ),
            patch(ENQUEUE) as enqueue,
            patch("posthog.ingress.dispatch.dispatcher.observe_consumer_run") as observe,
        ):
            response = self._post(_push())

        assert response.status_code == 202
        enqueue.assert_not_called()
        # The ingress view answers 202 even for a consumer that raised, so the outcome is what shows
        # that the handler swallowed the failure instead of failing the shared delivery.
        assert [call.kwargs["outcome"] for call in observe.call_args_list] == ["succeeded"]
