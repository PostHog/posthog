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

from products.review_hog.backend.automatic_review_rules import AddedRepositoryNames
from products.review_hog.backend.automatic_reviews import enqueue_authored_pr_review
from products.review_hog.backend.models import ReviewRepository, ReviewRepositoryPerson, ReviewUserSettings
from products.review_hog.backend.tasks import process_authored_pr_event
from products.review_hog.backend.webhook_consumers import WEBHOOK_CONSUMERS

_QUEUE = "products.review_hog.backend.tasks.process_authored_pr_event.delay"
_START = "products.review_hog.backend.temporal.client.start_review_pr_workflow"
_SECRET = "test-review-hog-webhook-secret"
_HEAD_SHA = "a" * 40
_DISPATCH_METRIC = "posthog_review_hog_authored_pr_review_total"
_REVIEWHOG_TEAM_ID = 7


def _dispatch_count(outcome: str) -> float:
    return REGISTRY.get_sample_value(_DISPATCH_METRIC, {"outcome": outcome}) or 0.0


def _payload(*, action: str = "opened", draft: bool = False, repository: str = "PostHog/posthog") -> dict[str, object]:
    return {
        "action": action,
        "installation": {"id": 1234},
        "repository": {"full_name": repository},
        "pull_request": {
            "number": 42,
            "state": "open",
            "draft": draft,
            "merged": False,
            "user": {"login": "OctoCat"},
            "head": {"sha": _HEAD_SHA, "repo": {"full_name": repository.lower()}},
            "base": {"repo": {"full_name": repository}},
        },
    }


@override_settings(CACHES=LOCMEM_CACHES)
class TestAuthoredPRWebhook(SimpleTestCase):
    def setUp(self) -> None:
        reset_consumer_registry()
        caches[INGRESS_DEDUP_CACHE_ALIAS].clear()
        caches["default"].clear()
        self.addCleanup(reset_consumer_registry)
        self.addCleanup(caches[INGRESS_DEDUP_CACHE_ALIAS].clear)
        self.addCleanup(caches["default"].clear)
        self.enterContext(override_settings(REVIEWHOG_TEAM_IDS=[_REVIEWHOG_TEAM_ID]))
        caches["default"].set(AddedRepositoryNames.cache_key(_REVIEWHOG_TEAM_ID), frozenset({"posthog/posthog"}))
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

    @parameterized.expand(
        [
            ("opened", False, "PostHog/posthog"),
            ("opened", True, "PostHog/posthog"),
            ("synchronize", False, "PostHog/posthog"),
            ("synchronize", True, "PostHog/posthog"),
        ]
    )
    @patch(_QUEUE)
    def test_signed_eligible_events_enqueue_once(
        self, action: str, draft: bool, repository: str, enqueue: MagicMock
    ) -> None:
        body = json.dumps(_payload(action=action, draft=draft, repository=repository)).encode()

        assert self._post(body).status_code == 202
        assert self._post(body).status_code == 202

        enqueue.assert_called_once_with(
            installation_id="1234", repository=repository, author_login="octocat", pr_number=42, head_sha=_HEAD_SHA
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

    @parameterized.expand(
        [
            ("added", "PostHog/posthog", [_REVIEWHOG_TEAM_ID], False, True),
            ("not_added", "PostHog/posthog-js", [_REVIEWHOG_TEAM_ID], False, False),
            ("no_team", "PostHog/posthog", [], False, False),
            ("cache_error_fails_open", "PostHog/posthog-js", [_REVIEWHOG_TEAM_ID], True, True),
        ]
    )
    @patch(_QUEUE)
    def test_only_added_repositories_enqueue(
        self,
        _name: str,
        repository: str,
        team_ids: list[int],
        cache_error: bool,
        expected_enqueue: bool,
        enqueue: MagicMock,
    ) -> None:
        self.enterContext(override_settings(REVIEWHOG_TEAM_IDS=team_ids))
        if cache_error:
            self.enterContext(
                patch(
                    "products.review_hog.backend.automatic_review_rules.cache.get_or_set",
                    side_effect=ConnectionError("redis down"),
                )
            )

        assert self._post(json.dumps(_payload(repository=repository)).encode()).status_code == 202

        assert enqueue.called == expected_enqueue

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
        self.repository = ReviewRepository.objects.for_team(self.team.id).create(
            team=self.team, full_name="PostHog/posthog", flash_for=ReviewRepository.FlashFor.LISTED
        )
        self.preferences = ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, default_review_mode=ReviewUserSettings.DefaultReviewMode.FLASH
        )

    def _queued_event(self) -> Mapping[str, object]:
        with patch(_QUEUE) as enqueue:
            enqueue_authored_pr_review(_payload())
        enqueue.assert_called_once()
        return enqueue.call_args.kwargs

    @parameterized.expand([("own_flash_default", False), ("listed_by_the_repository", True)])
    @patch(_START)
    def test_eligible_author_schedules_flash_on_the_configured_team(
        self, _name: str, listed: bool, start: MagicMock
    ) -> None:
        if listed:
            self.preferences.default_review_mode = ReviewUserSettings.DefaultReviewMode.FOLLOW
            self.preferences.save(update_fields=["default_review_mode"])
            ReviewRepositoryPerson.objects.for_team(self.team.id).create(
                team=self.team, repository=self.repository, user=self.user, kind=ReviewRepositoryPerson.Kind.LISTED
            )
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
            ("full", "full_not_supported"),
            ("repository_removed", "repository_not_added"),
            ("inactive", "author_unmapped"),
            ("left_org", "author_unmapped"),
            ("unmapped", "author_unmapped"),
        ]
    )
    @patch(_START)
    def test_queued_events_recheck_repository_author_consent_and_membership(
        self, change: str, expected_outcome: str, start: MagicMock
    ) -> None:
        queued = self._queued_event()
        if change in ("disabled", "full"):
            mode = "follow" if change == "disabled" else "full"
            self.preferences.default_review_mode = ReviewUserSettings.DefaultReviewMode(mode)
            self.preferences.save(update_fields=["default_review_mode"])
        elif change == "repository_removed":
            self.repository.delete()
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
                ReviewRepository.objects.for_team(other_team.id).create(team=other_team, full_name="PostHog/posthog")
                self.enterContext(override_settings(REVIEWHOG_TEAM_IDS=[other_team.id, self.team.id]))
        outcome_before = _dispatch_count(expected_outcome)

        process_authored_pr_event.run(**queued)

        start.assert_not_called()
        assert _dispatch_count(expected_outcome) - outcome_before == 1.0
