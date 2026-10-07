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
from products.review_hog.backend.repository_config import RepositoryConfigError, RepositoryReviewConfig
from products.review_hog.backend.tasks import process_authored_pr_event
from products.review_hog.backend.temporal.types import RepositoryReviewPolicy
from products.review_hog.backend.webhook_consumers import WEBHOOK_CONSUMERS

_QUEUE = "products.review_hog.backend.tasks.process_authored_pr_event.delay"
_START = "products.review_hog.backend.temporal.client.start_review_pr_workflow"
_LOAD_CONFIG = "products.review_hog.backend.automatic_reviews.load_repository_config"
_SECRET = "test-review-hog-webhook-secret"
_HEAD_SHA = "a" * 40
_DISPATCH_METRIC = "posthog_review_hog_authored_pr_review_total"


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
            "labels": [{"name": "chore"}, {"name": "no-reviewhog"}],
            "head": {"sha": _HEAD_SHA, "repo": {"full_name": repository.swapcase()}},
            "base": {"ref": "master", "repo": {"full_name": repository}},
        },
        **({"changes": {"base": {"ref": {"from": "main"}}}} if action == "edited" else {}),
    }


def _queued_kwargs(*, action: str = "opened", draft: bool = False, repository: str = "PostHog/posthog") -> dict:
    return {
        "installation_id": "1234",
        "repository": repository,
        "author_login": "octocat",
        "pr_number": 42,
        "head_sha": _HEAD_SHA,
        "action": action,
        "base_ref": "master",
        "draft": draft,
        "labels": ["chore", "no-reviewhog"],
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

    @parameterized.expand(
        [
            ("opened", False, "PostHog/posthog"),
            ("opened", True, "PostHog/posthog"),
            ("synchronize", False, "PostHog/posthog"),
            ("synchronize", True, "PostHog/posthog"),
            ("ready_for_review", False, "PostHog/posthog"),
            ("unlabeled", False, "PostHog/posthog"),
            ("edited", False, "PostHog/posthog"),
            ("opened", False, "PostHog/posthog-js"),
        ]
    )
    @patch(_QUEUE)
    def test_signed_eligible_events_enqueue_once(
        self, action: str, draft: bool, repository: str, enqueue: MagicMock
    ) -> None:
        body = json.dumps(_payload(action=action, draft=draft, repository=repository)).encode()

        assert self._post(body).status_code == 202
        assert self._post(body).status_code == 202

        enqueue.assert_called_once_with(**_queued_kwargs(action=action, draft=draft, repository=repository))

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
            ("edit_without_base_change", ("action",), "edited"),
            ("closed", ("pull_request", "state"), "closed"),
            ("merged", ("pull_request", "merged"), True),
            ("fork", ("pull_request", "head", "repo", "full_name"), "octocat/posthog"),
            ("deleted_fork", ("pull_request", "head", "repo"), None),
            ("head_in_other_repository", ("repository", "full_name"), "PostHog/another-repo"),
            ("other_base", ("pull_request", "base", "repo", "full_name"), "PostHog/another-repo"),
            ("no_repository", ("repository",), None),
            ("no_installation", ("installation",), None),
            ("no_author", ("pull_request", "user"), None),
            ("no_head", ("pull_request", "head", "sha"), ""),
            ("no_base_ref", ("pull_request", "base", "ref"), ""),
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
        # The repository's config, as the task reads it; the default has no skip label hit.
        self.load_config = self.enterContext(patch(_LOAD_CONFIG))
        self.load_config.return_value = RepositoryReviewConfig(skip_labels=[])

    def _queued_event(self, repository: str = "PostHog/posthog") -> Mapping[str, object]:
        with patch(_QUEUE) as enqueue:
            enqueue_authored_pr_review(_payload(repository=repository))
        enqueue.assert_called_once()
        return enqueue.call_args.kwargs

    @parameterized.expand([("PostHog/posthog",), ("PostHog/posthog-js",)])
    @patch(_START)
    def test_opted_in_author_schedules_flash_on_the_configured_team(self, repository: str, start: MagicMock) -> None:
        started_before = _dispatch_count("started")

        process_authored_pr_event.run(**self._queued_event(repository=repository))

        self.load_config.assert_called_once_with(self.integration, repository)
        start.assert_called_once_with(
            pr_url=f"https://github.com/{repository}/pull/42",
            team_id=self.team.id,
            user_id=self.user.id,
            acting_user_id=self.user.id,
            publish=True,
            resolve_comments=False,
            review_mode="flash",
            trigger_source="automatic",
            requested_head_sha=_HEAD_SHA,
            repository_policy=RepositoryReviewPolicy(),
        )
        assert _dispatch_count("started") - started_before == 1.0

    @patch(_START)
    def test_config_decides_the_turns_policy(self, start: MagicMock) -> None:
        self.load_config.return_value = RepositoryReviewConfig(
            authors="members", flash={"effort": "xhigh"}, instructions="Flag blocking calls.", skip_labels=[]
        )
        self.preferences.delete()

        process_authored_pr_event.run(**self._queued_event())

        assert start.call_args.kwargs["repository_policy"] == RepositoryReviewPolicy(
            author_opt_in_required=False, flash_reasoning_effort="xhigh", instructions="Flag blocking calls."
        )

    @parameterized.expand(
        [
            ("no_config", None, "no_config"),
            ("config_invalid", RepositoryConfigError("bad"), "config_invalid"),
            ("config_disabled", RepositoryReviewConfig(enabled=False), "config_disabled"),
            ("skip_label", RepositoryReviewConfig(), "label_skipped"),
            ("ignored_author", RepositoryReviewConfig(skip_labels=[], ignore_authors=["octo*"]), "author_ignored"),
        ]
    )
    @patch(_START)
    def test_config_gates_run_before_the_opt_in_check(
        self, _name: str, config: object, expected_outcome: str, start: MagicMock
    ) -> None:
        if isinstance(config, Exception):
            self.load_config.side_effect = config
        else:
            self.load_config.return_value = config
        outcome_before = _dispatch_count(expected_outcome)

        process_authored_pr_event.run(**self._queued_event())

        start.assert_not_called()
        assert _dispatch_count(expected_outcome) - outcome_before == 1.0

    @patch(_START)
    def test_queued_task_without_event_state_is_dropped(self, start: MagicMock) -> None:
        outcome_before = _dispatch_count("event_state_missing")

        process_authored_pr_event.run(installation_id="1234", author_login="octocat", pr_number=42, head_sha=_HEAD_SHA)

        start.assert_not_called()
        self.load_config.assert_not_called()
        assert _dispatch_count("event_state_missing") - outcome_before == 1.0

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
        if expected_outcome == "author_unmapped":
            self.load_config.assert_not_called()

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
        self.load_config.assert_not_called()
        assert _dispatch_count(expected_outcome) - outcome_before == 1.0
