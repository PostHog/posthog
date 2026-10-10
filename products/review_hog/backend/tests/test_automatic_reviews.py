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
from posthog.models.user import User

from products.review_hog.backend.models import (
    ReviewInstallationClaim,
    ReviewProjectSettings,
    ReviewReport,
    ReviewRepository,
    ReviewRepositoryPerson,
    ReviewUserSettings,
)
from products.review_hog.backend.ownership import OwnedRepositoryPrefilter
from products.review_hog.backend.pull_request_events import accept_pull_request_event
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError
from products.review_hog.backend.tasks import process_authored_pr_event, process_label_event
from products.review_hog.backend.webhook_consumers import WEBHOOK_CONSUMERS

_QUEUE = "products.review_hog.backend.tasks.process_authored_pr_event.delay"
_LABEL_QUEUE = "products.review_hog.backend.tasks.process_label_event.delay"
_START = "products.review_hog.backend.temporal.client.start_review_pr_workflow"
_BUSY = "products.review_hog.backend.temporal.client.workflow_running"
_GITHUB = "products.review_hog.backend.label_reviews.github_api_request"
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
            "head": {"sha": _HEAD_SHA, "ref": "feature", "repo": {"full_name": repository.lower()}},
            "base": {"repo": {"full_name": repository}},
        },
    }


def _label_payload(
    *, label: str = "reviewhog", sender: str = "OctoCat", sender_type: str = "User", login: str = "OctoCat"
) -> dict[str, object]:
    return {
        **_payload(action="labeled", login=login),
        "label": {"name": label},
        "sender": {"login": sender, "type": sender_type},
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

    @parameterized.expand(
        [
            ("person_adds_the_label", "reviewhog", "OctoCat", "User", True),
            ("label_name_ignores_case", "ReviewHog", "OctoCat", "User", True),
            # The task explains the refusal on the pull request and removes the label.
            ("bot_adds_the_label", "reviewhog", "renovate[bot]", "Bot", True),
            ("another_label", "bug", "OctoCat", "User", False),
        ]
    )
    @patch(_QUEUE)
    @patch(_LABEL_QUEUE)
    def test_the_reviewhog_label_queues_a_label_review(
        self,
        _name: str,
        label: str,
        sender: str,
        sender_type: str,
        expected_enqueue: bool,
        label_enqueue: MagicMock,
        enqueue: MagicMock,
    ) -> None:
        body = json.dumps(_label_payload(label=label, sender=sender, sender_type=sender_type)).encode()

        assert self._post(body).status_code == 202

        enqueue.assert_not_called()
        if expected_enqueue:
            label_enqueue.assert_called_once_with(
                installation_id=_INSTALLATION_ID,
                repository="PostHog/posthog",
                github_repo_id=_REPO_ID,
                pr_number=42,
                author_login="octocat",
                head_branch="feature",
                labeler_login=sender,
                labeled_by_bot=sender_type == "Bot",
            )
        else:
            label_enqueue.assert_not_called()

    @patch(_QUEUE)
    def test_non_post_does_not_enqueue(self, enqueue: MagicMock) -> None:
        assert self.view(self.factory.get("/webhooks/github/")).status_code == 405
        enqueue.assert_not_called()

    @parameterized.expand(
        [
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
            accept_pull_request_event(_payload(login=login))
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
            ("full_review_published", "full_review_published"),
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
        elif change == "full_review_published":
            ReviewReport.objects.for_team(self.team.id).create(
                team=self.team,
                repository="PostHog/posthog",
                pr_number=42,
                head_branch="feature",
                base_branch="master",
                published_heads_by_mode={"full": _HEAD_SHA},
            )
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


class TestLabelReviewTask(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.connector = User.objects.create_and_join(self.organization, "connector@example.com", None)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id=_INSTALLATION_ID,
            config={"installation_id": _INSTALLATION_ID, "account": {"name": "PostHog"}},
            created_by=self.connector,
        )
        UserSocialAuth.objects.create(
            user=self.user, provider="github", uid="review-author", extra_data={"login": "OctoCat"}
        )
        ReviewInstallationClaim.objects.for_team(self.team.id).create(
            team=self.team, installation_id=_INSTALLATION_ID, scope=ReviewInstallationClaim.Scope.SELECTED
        )
        self.repository = ReviewRepository.objects.for_team(self.team.id).create(
            team=self.team, installation_id=_INSTALLATION_ID, full_name="PostHog/posthog", selected=True
        )
        self.enterContext(patch(_BUSY, return_value=False))
        self.start = self.enterContext(patch(_START))
        self.github = self.enterContext(patch(_GITHUB))
        self.enterContext(patch("products.review_hog.backend.label_reviews.GitHubIntegration.get_access_token"))

    def _queued_event(self, payload: dict[str, object]) -> Mapping[str, object]:
        with patch(_LABEL_QUEUE) as enqueue:
            accept_pull_request_event(payload)
        enqueue.assert_called_once()
        return enqueue.call_args.kwargs

    def _run(self, payload: dict[str, object]) -> None:
        process_label_event.run(**self._queued_event(payload))

    @parameterized.expand([("the_author_owns_it", "OctoCat", "author"), ("no_owner", "stranger", "connector")])
    def test_a_label_review_runs_as_the_owner_else_as_the_connector(
        self, _name: str, author_login: str, run_as: str
    ) -> None:
        self._run(_label_payload(login=author_login))

        self.start.assert_called_once_with(
            pr_url="https://github.com/PostHog/posthog/pull/42",
            team_id=self.team.id,
            user_id=self.user.id if run_as == "author" else self.connector.id,
            publish=True,
            trigger_source="label",
        )

    @parameterized.expand([("another_bot", "renovate[bot]", False), ("stamphog_hands_off", "stamphog[bot]", True)])
    def test_only_stamphog_may_label_as_a_bot(self, _name: str, sender: str, starts: bool) -> None:
        self._run(_label_payload(sender=sender, sender_type="Bot"))

        assert self.start.called == starts
        calls = [(call.args[0], call.args[1]) for call in self.github.call_args_list]
        if starts:
            assert calls == []
        else:
            assert calls == [
                ("DELETE", "/repos/PostHog/posthog/issues/42/labels/reviewhog"),
                ("POST", "/repos/PostHog/posthog/issues/42/comments"),
            ]

    def test_a_retried_bot_label_refusal_comments_once(self) -> None:
        queued = self._queued_event(_label_payload(sender="renovate[bot]", sender_type="Bot"))
        self.github.side_effect = [GitHubAPIError("boom", status=502), GitHubAPIError("gone", status=404), None]

        with self.assertRaises(GitHubAPIError):
            process_label_event.run(**queued)
        process_label_event.run(**queued)

        calls = [call.args[0] for call in self.github.call_args_list]
        assert calls == ["DELETE", "DELETE", "POST"]
        self.start.assert_not_called()

    @parameterized.expand(
        [
            ("repository_not_added", "repository_not_added"),
            ("no_run_user", "no_run_user"),
        ]
    )
    def test_a_label_without_an_owning_project_or_run_user_starts_nothing(self, change: str, outcome: str) -> None:
        queued = self._queued_event(_label_payload(login="stranger"))
        if change == "repository_not_added":
            self.repository.delete()
        else:
            self.integration.created_by = None
            self.integration.save(update_fields=["created_by"])
        before = REGISTRY.get_sample_value("posthog_review_hog_label_review_total", {"outcome": outcome}) or 0.0

        process_label_event.run(**queued)

        self.start.assert_not_called()
        after = REGISTRY.get_sample_value("posthog_review_hog_label_review_total", {"outcome": outcome}) or 0.0
        assert after - before == 1.0
