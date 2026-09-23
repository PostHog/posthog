import hmac
import json
from collections.abc import Mapping

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import caches
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized
from prometheus_client import REGISTRY
from social_django.models import UserSocialAuth

from posthog.ingress.dispatch.dedup import INGRESS_DEDUP_CACHE_ALIAS
from posthog.ingress.dispatch.dispatcher import WebhookDispatcher
from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.ingress.dispatch.registry import ConsumerRegistry
from posthog.ingress.github.provider import SPECS, build_github_provider
from posthog.ingress.test import LOCMEM_CACHES
from posthog.ingress.views import build_webhook_view
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.review_hog.backend.automatic_reviews import enqueue_authored_pr_review
from products.review_hog.backend.models import ReviewUserSettings
from products.review_hog.backend.tasks import process_authored_pr_event
from products.review_hog.backend.webhook_consumers import WEBHOOK_CONSUMERS

_QUEUE = "products.review_hog.backend.tasks.process_authored_pr_event.delay"
_START = "products.review_hog.backend.temporal.client.start_review_pr_workflow"
_SECRET = "test-review-hog-webhook-secret"
_HEAD_SHA = "a" * 40
_DISPATCH_METRIC = "posthog_review_hog_authored_pr_review_total"


def _dispatch_count(outcome: str) -> float:
    return REGISTRY.get_sample_value(_DISPATCH_METRIC, {"outcome": outcome}) or 0.0


def _payload(*, action: str = "opened", draft: bool = False) -> dict[str, object]:
    return {
        "action": action,
        "installation": {"id": 1234},
        "repository": {"full_name": "PostHog/posthog"},
        "pull_request": {
            "number": 42,
            "state": "open",
            "draft": draft,
            "merged": False,
            "user": {"login": "OctoCat"},
            "head": {"sha": _HEAD_SHA, "repo": {"full_name": "posthog/PostHog"}},
            "base": {"repo": {"full_name": "PostHog/posthog"}},
        },
    }


@override_settings(CACHES=LOCMEM_CACHES)
class TestAuthoredPRWebhook(SimpleTestCase):
    def setUp(self) -> None:
        reset_consumer_registry()
        caches[INGRESS_DEDUP_CACHE_ALIAS].clear()
        self.addCleanup(reset_consumer_registry)
        self.addCleanup(caches[INGRESS_DEDUP_CACHE_ALIAS].clear)
        self.factory = RequestFactory()
        self.view = build_webhook_view(build_github_provider("posthog"))
        dispatcher = WebhookDispatcher(ConsumerRegistry(providers=SPECS, consumers=WEBHOOK_CONSUMERS))
        self.enterContext(patch("posthog.ingress.views.get_dispatcher", return_value=dispatcher))
        self.secret = self.enterContext(
            patch("posthog.ingress.github.provider.get_instance_setting", return_value=_SECRET)
        )

    def _post(self, body: bytes, *, event: str = "pull_request", signature: str | None = None) -> HttpResponse:
        request = self.factory.post(
            "/webhooks/github/",
            data=body,
            content_type="application/json",
            headers={
                "X-GitHub-Event": event,
                "X-GitHub-Delivery": "authored-pr-delivery",
                "X-Hub-Signature-256": signature or "sha256=" + hmac.digest(_SECRET.encode(), body, "sha256").hex(),
            },
        )
        return self.view(request)

    @parameterized.expand([("opened", False), ("opened", True), ("synchronize", False), ("synchronize", True)])
    @patch(_QUEUE)
    def test_signed_eligible_events_enqueue_once(self, action: str, draft: bool, enqueue: MagicMock) -> None:
        body = json.dumps(_payload(action=action, draft=draft)).encode()

        assert self._post(body).status_code == 202
        assert self._post(body).status_code == 202

        enqueue.assert_called_once_with(
            installation_id="1234", author_login="octocat", pr_number=42, head_sha=_HEAD_SHA
        )

    @parameterized.expand(
        [
            ("not_a_pr_event", "issues", None, False, False, 202),
            ("invalid_signature", "pull_request", "sha256=" + "0" * 64, False, False, 403),
            ("invalid_body", "pull_request", None, True, False, 400),
            ("missing_secret", "pull_request", None, False, True, 500),
        ]
    )
    @patch(_QUEUE)
    def test_refused_deliveries_do_not_enqueue(
        self,
        _name: str,
        event: str,
        signature: str | None,
        invalid_body: bool,
        missing_secret: bool,
        expected_status: int,
        enqueue: MagicMock,
    ) -> None:
        body = b"not json" if invalid_body else json.dumps(_payload()).encode()
        if missing_secret:
            self.secret.return_value = None

        response = self._post(body, event=event, signature=signature)

        assert response.status_code == expected_status
        enqueue.assert_not_called()

    @patch(_QUEUE)
    def test_non_post_does_not_enqueue(self, enqueue: MagicMock) -> None:
        assert self.view(self.factory.get("/webhooks/github/")).status_code == 405
        enqueue.assert_not_called()

    @parameterized.expand(
        [
            ("label", ("action",), "labeled"),
            ("ready_for_review", ("action",), "ready_for_review"),
            ("closed", ("pull_request", "state"), "closed"),
            ("merged", ("pull_request", "merged"), True),
            ("fork", ("pull_request", "head", "repo", "full_name"), "octocat/posthog"),
            ("deleted_fork", ("pull_request", "head", "repo"), None),
            ("other_repository", ("repository", "full_name"), "PostHog/another-repo"),
            ("other_base", ("pull_request", "base", "repo", "full_name"), "PostHog/another-repo"),
            ("no_installation", ("installation",), None),
            ("no_author", ("pull_request", "user"), None),
            ("no_head", ("pull_request", "head", "sha"), ""),
        ]
    )
    @patch(_QUEUE)
    def test_ineligible_pull_requests_do_not_enqueue(
        self, _name: str, path: tuple[str, ...], value: object, enqueue: MagicMock
    ) -> None:
        payload = _payload()
        target = payload
        for part in path[:-1]:
            nested = target[part]
            assert isinstance(nested, dict)
            target = nested
        target[path[-1]] = value

        assert self._post(json.dumps(payload).encode()).status_code == 202

        enqueue.assert_not_called()


class TestAuthoredPRReviewTask(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(override_settings(REVIEWHOG_TEAM_IDS=[self.team.id]))
        self.integration = Integration.objects.create(
            team=self.team, kind="github", integration_id="1234", config={"installation_id": "1234"}
        )
        self.github_identity = UserSocialAuth.objects.create(
            user=self.user, provider="github", uid="review-author", extra_data={"login": "OctoCat"}
        )
        self.preferences = ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, review_authored_prs=True
        )

    def _queued_event(self) -> Mapping[str, object]:
        with patch(_QUEUE) as enqueue:
            enqueue_authored_pr_review(_payload())
        enqueue.assert_called_once()
        return enqueue.call_args.kwargs

    @patch(_START)
    def test_opted_in_author_schedules_flash_on_the_configured_team(self, start: MagicMock) -> None:
        started_before = _dispatch_count("started")

        process_authored_pr_event.run(**self._queued_event())

        start.assert_called_once_with(
            pr_url="https://github.com/PostHog/posthog/pull/42",
            team_id=self.team.id,
            user_id=self.user.id,
            acting_user_id=self.user.id,
            publish=True,
            resolve_comments=False,
            review_mode="flash",
            trigger_source="automatic",
            requested_head_sha=_HEAD_SHA,
        )
        assert _dispatch_count("started") - started_before == 1.0

    @parameterized.expand(
        [
            ("disabled", "not_opted_in"),
            ("unset", "not_opted_in"),
            ("inactive", "not_opted_in"),
            ("left_org", "author_unmapped"),
            ("unmapped", "author_unmapped"),
        ]
    )
    @patch(_START)
    def test_queued_events_recheck_author_consent_and_membership(
        self, change: str, expected_outcome: str, start: MagicMock
    ) -> None:
        queued = self._queued_event()
        if change == "disabled":
            self.preferences.review_authored_prs = False
            self.preferences.save(update_fields=["review_authored_prs"])
        elif change == "unset":
            self.preferences.delete()
        elif change == "inactive":
            self.user.is_active = False
            self.user.save(update_fields=["is_active"])
        elif change == "left_org":
            OrganizationMembership.objects.filter(organization=self.organization, user=self.user).delete()
        else:
            self.github_identity.delete()
        outcome_before = _dispatch_count(expected_outcome)

        process_authored_pr_event.run(**queued)

        start.assert_not_called()
        assert _dispatch_count(expected_outcome) - outcome_before == 1.0

    @parameterized.expand(
        [
            ("missing_installation", "installation_mismatch"),
            ("other_team", "installation_mismatch"),
            ("other_configured_team", "installation_mismatch"),
            ("no_team", "no_team"),
        ]
    )
    @patch(_START)
    def test_delivery_must_match_the_configured_teams_installation(
        self, change: str, expected_outcome: str, start: MagicMock
    ) -> None:
        queued = self._queued_event()
        if change == "missing_installation":
            self.integration.delete()
        elif change == "no_team":
            self.enterContext(override_settings(REVIEWHOG_TEAM_IDS=[]))
        else:
            other_team = Team.objects.create(organization=self.organization)
            if change == "other_team":
                self.integration.team = other_team
                self.integration.save(update_fields=["team"])
            else:
                self.enterContext(override_settings(REVIEWHOG_TEAM_IDS=[other_team.id, self.team.id]))
        outcome_before = _dispatch_count(expected_outcome)

        process_authored_pr_event.run(**queued)

        start.assert_not_called()
        assert _dispatch_count(expected_outcome) - outcome_before == 1.0
