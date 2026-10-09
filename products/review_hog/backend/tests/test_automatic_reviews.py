import hmac
import json
from collections.abc import Mapping

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import caches
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized
from prometheus_client import REGISTRY
from social_django.models import UserSocialAuth

from posthog.ingress.dispatch.dedup import INGRESS_DEDUP_CACHE_ALIAS
from posthog.ingress.dispatch.dispatcher import WebhookDispatcher
from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.ingress.dispatch.registry import ConsumerRegistry
from posthog.ingress.github.provider import SPECS, build_github_provider
from posthog.ingress.views import build_webhook_view
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.review_hog.backend.automatic_reviews import enqueue_authored_pr_review
from products.review_hog.backend.models import (
    ReviewInstallationClaim,
    ReviewProjectSettings,
    ReviewRepository,
    ReviewRepositoryPerson,
    ReviewUserSettings,
)
from products.review_hog.backend.ownership import OwnedRepositoryPrefilter
from products.review_hog.backend.tasks import process_authored_pr_event
from products.review_hog.backend.webhook_consumers import WEBHOOK_CONSUMERS

_QUEUE = "products.review_hog.backend.tasks.process_authored_pr_event.delay"
_START = "products.review_hog.backend.temporal.client.start_review_pr_workflow"
_SECRET = "test-review-hog-webhook-secret"
_HEAD_SHA = "a" * 40
_DISPATCH_METRIC = "posthog_review_hog_authored_pr_review_total"
_INSTALLATION_ID = "1234"
_REPO_ID = 5001


def _dispatch_count(outcome: str) -> float:
    return REGISTRY.get_sample_value(_DISPATCH_METRIC, {"outcome": outcome}) or 0.0


def _payload(
    *, action: str = "opened", draft: bool = False, repository: str = "PostHog/posthog", login: str = "OctoCat"
) -> dict[str, object]:
    return {
        "action": action,
        "installation": {"id": int(_INSTALLATION_ID)},
        "repository": {"id": _REPO_ID, "full_name": repository},
        "pull_request": {
            "number": 42,
            "state": "open",
            "draft": draft,
            "merged": False,
            "user": {"login": login},
            "head": {"sha": _HEAD_SHA, "repo": {"full_name": repository.lower()}},
            "base": {"repo": {"full_name": repository}},
        },
    }


class TestAuthoredPRWebhook(SimpleTestCase):
    def setUp(self) -> None:
        reset_consumer_registry()
        caches[INGRESS_DEDUP_CACHE_ALIAS].clear()
        caches["default"].clear()
        self.addCleanup(reset_consumer_registry)
        self.addCleanup(caches[INGRESS_DEDUP_CACHE_ALIAS].clear)
        self.addCleanup(caches["default"].clear)
        self._cache_summary(names=["posthog/posthog"])
        self.factory = RequestFactory()
        self.view = build_webhook_view(build_github_provider("posthog"))
        dispatcher = WebhookDispatcher(ConsumerRegistry(providers=SPECS, consumers=WEBHOOK_CONSUMERS))
        self.enterContext(patch("posthog.ingress.views.get_dispatcher", return_value=dispatcher))
        self.secret = self.enterContext(
            patch("posthog.ingress.github.provider.get_instance_setting", return_value=_SECRET)
        )

    def _cache_summary(
        self, *, takes_all: bool = False, names: list[str] | None = None, ids: list[int] | None = None
    ) -> None:
        caches["default"].set(
            OwnedRepositoryPrefilter.cache_key(_INSTALLATION_ID),
            {"all": takes_all, "names": names or [], "ids": ids or []},
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
            installation_id=_INSTALLATION_ID,
            repository=repository,
            author_login="octocat",
            pr_number=42,
            head_sha=_HEAD_SHA,
            github_repo_id=_REPO_ID,
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
            ("selected_by_name", "PostHog/posthog", {"names": ["posthog/posthog"]}, False, True),
            ("selected_by_id_after_rename", "PostHog/posthog-renamed", {"ids": [_REPO_ID]}, False, True),
            ("all_repositories_claimed", "PostHog/posthog-js", {"takes_all": True}, False, True),
            ("nobody_reviews_it", "PostHog/posthog-js", {"names": ["posthog/posthog"]}, False, False),
            ("cache_error_fails_open", "PostHog/posthog-js", {}, True, True),
        ]
    )
    @patch(_QUEUE)
    def test_only_owned_repositories_enqueue(
        self,
        _name: str,
        repository: str,
        summary: dict,
        cache_error: bool,
        expected_enqueue: bool,
        enqueue: MagicMock,
    ) -> None:
        self._cache_summary(**summary)
        if cache_error:
            self.enterContext(
                patch(
                    "products.review_hog.backend.ownership.cache.get_or_set",
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
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id=_INSTALLATION_ID,
            config={"installation_id": _INSTALLATION_ID, "account": {"name": "PostHog"}},
            created_by=self.user,
        )
        self.github_identity = UserSocialAuth.objects.create(
            user=self.user, provider="github", uid="review-author", extra_data={"login": "OctoCat"}
        )
        ReviewInstallationClaim.objects.for_team(self.team.id).create(
            team=self.team, installation_id=_INSTALLATION_ID, scope=ReviewInstallationClaim.Scope.SELECTED
        )
        self.repository = ReviewRepository.objects.for_team(self.team.id).create(
            team=self.team, installation_id=_INSTALLATION_ID, full_name="PostHog/posthog", selected=True
        )
        self.preferences = ReviewUserSettings.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, preferences={"default_review_mode": "flash"}
        )

    def _queued_event(self, login: str = "OctoCat") -> Mapping[str, object]:
        with patch(_QUEUE) as enqueue:
            enqueue_authored_pr_review(_payload(login=login))
        enqueue.assert_called_once()
        return enqueue.call_args.kwargs

    def _expected_start(self, *, team_id: int, user_id: int) -> dict[str, object]:
        return {
            "pr_url": "https://github.com/PostHog/posthog/pull/42",
            "team_id": team_id,
            "user_id": user_id,
            "acting_user_id": user_id,
            "publish": True,
            "resolve_comments": False,
            "review_mode": "flash",
            "trigger_source": "automatic",
            "requested_head_sha": _HEAD_SHA,
            "installation_id": _INSTALLATION_ID,
            "github_repo_id": _REPO_ID,
        }

    @parameterized.expand([("own_flash_default",), ("listed_by_the_project",), ("repository_exception",)])
    @patch(_START)
    def test_eligible_author_schedules_flash_in_the_owning_project(self, setup: str, start: MagicMock) -> None:
        if setup != "own_flash_default":
            self.preferences.preferences = {}
            self.preferences.save(update_fields=["preferences"])
        if setup == "listed_by_the_project":
            ReviewProjectSettings.objects.for_team(self.team.id).create(team=self.team, flash_for="listed")
            ReviewRepositoryPerson.objects.for_team(self.team.id).create(
                team=self.team, repository=None, user=self.user, kind=ReviewRepositoryPerson.Kind.LISTED
            )
        if setup == "repository_exception":
            self.repository.flash_for = "everyone"
            self.repository.save()
        started_before = _dispatch_count("started")

        process_authored_pr_event.run(**self._queued_event())

        start.assert_called_once_with(**self._expected_start(team_id=self.team.id, user_id=self.user.id))
        assert _dispatch_count("started") - started_before == 1.0
        # The first sighting stores GitHub's id, so a later rename keeps the row.
        self.repository.refresh_from_db()
        assert self.repository.github_repo_id == _REPO_ID

    @parameterized.expand(
        [
            ("opted_out", "not_opted_in"),
            ("repository_removed", "repository_not_added"),
            ("inactive", "bot_skipped"),
            ("left_org", "bot_skipped"),
            ("unmapped", "bot_skipped"),
            ("missing_installation", "installation_mismatch"),
        ]
    )
    @patch(_START)
    def test_queued_events_recheck_ownership_consent_and_membership(
        self, change: str, expected_outcome: str, start: MagicMock
    ) -> None:
        queued = self._queued_event()
        if change == "opted_out":
            self.preferences.preferences = {"default_review_mode": "off"}
            self.preferences.save(update_fields=["preferences"])
        elif change == "repository_removed":
            self.repository.delete()
        elif change == "inactive":
            self.user.is_active = False
            self.user.save(update_fields=["is_active"])
        elif change == "left_org":
            OrganizationMembership.objects.filter(organization=self.organization, user=self.user).delete()
        elif change == "missing_installation":
            self.integration.delete()
        else:
            self.github_identity.delete()
        outcome_before = _dispatch_count(expected_outcome)

        process_authored_pr_event.run(**queued)

        start.assert_not_called()
        assert _dispatch_count(expected_outcome) - outcome_before == 1.0

    @parameterized.expand([("connector_runs_it", True, "started"), ("no_connector", False, "bot_no_connector")])
    @patch(_START)
    def test_bot_pull_requests_run_as_the_connector_when_the_project_reviews_bots(
        self, _name: str, has_connector: bool, expected_outcome: str, start: MagicMock
    ) -> None:
        ReviewProjectSettings.objects.for_team(self.team.id).create(
            team=self.team, bot_prs=ReviewProjectSettings.BotPullRequests.RUN
        )
        if not has_connector:
            self.integration.created_by = None
            self.integration.save(update_fields=["created_by"])
        outcome_before = _dispatch_count(expected_outcome)

        process_authored_pr_event.run(**self._queued_event(login="dependabot[bot]"))

        if has_connector:
            start.assert_called_once_with(**self._expected_start(team_id=self.team.id, user_id=self.user.id))
        else:
            start.assert_not_called()
        assert _dispatch_count(expected_outcome) - outcome_before == 1.0

    @patch(_START)
    def test_a_project_that_takes_all_repositories_owns_the_unselected_ones(self, start: MagicMock) -> None:
        other_team = Team.objects.create(organization=self.organization)
        Integration.objects.create(
            team=other_team, kind="github", integration_id=_INSTALLATION_ID, config={}, created_by=self.user
        )
        ReviewInstallationClaim.objects.for_team(other_team.id).create(
            team=other_team, installation_id=_INSTALLATION_ID, scope=ReviewInstallationClaim.Scope.ALL
        )
        ReviewUserSettings.objects.for_team(other_team.id).create(
            team_id=other_team.id, user_id=self.user.id, preferences={"default_review_mode": "flash"}
        )
        self.repository.delete()

        process_authored_pr_event.run(**self._queued_event())

        start.assert_called_once_with(**self._expected_start(team_id=other_team.id, user_id=self.user.id))
