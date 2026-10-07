import hmac
import json
import hashlib
from urllib.parse import quote

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import DatabaseError
from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.models import Team
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError, Integration

from products.error_tracking.backend.facade import api
from products.error_tracking.backend.models import (
    ErrorTrackingExternalReference,
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
)
from products.error_tracking.backend.tasks.github import process_github_external_reference

LINKED_BODY = "https://app.example.com/project/12/error_tracking/00000000-0000-0000-0000-000000000001"


@override_settings(SITE_URL="https://app.example.com")
class TestPrepareGitHubExternalReferenceJob(SimpleTestCase):
    @parameterized.expand(
        [
            ("unsupported_action", "closed", "MEMBER", "octocat", "User", LINKED_BODY),
            ("unrelated_author", "opened", "NONE", "octocat", "User", LINKED_BODY),
            ("missing_sender", "opened", "MEMBER", None, "User", LINKED_BODY),
            ("bot_sender", "opened", "MEMBER", "dependabot[bot]", "Bot", LINKED_BODY),
            ("missing_body", "opened", "MEMBER", "octocat", "User", None),
        ]
    )
    def test_rejects_ineligible_events(
        self,
        _name: str,
        action: str,
        author_association: str,
        sender_login: str | None,
        sender_type: str,
        body: str | None,
    ) -> None:
        payload = {
            "action": action,
            "installation": {"id": 123},
            "repository": {"full_name": "acme/widgets"},
            "sender": {"login": sender_login, "type": sender_type},
            "issue": {
                "number": 17,
                "title": "Checkout failed",
                "body": body,
                "user": {"login": "octocat"},
                "author_association": author_association,
            },
        }

        assert api.prepare_github_external_reference_jobs("issues", payload) == []

    def test_carries_the_editor_rather_than_the_author_as_the_actor(self) -> None:
        payload = {
            "action": "edited",
            "installation": {"id": 123},
            "repository": {"full_name": "acme/widgets"},
            "sender": {"login": "editor", "type": "User"},
            "issue": {
                "number": 17,
                "title": "Checkout failed",
                "body": LINKED_BODY,
                "user": {"login": "drive-by"},
                "author_association": "NONE",
            },
        }

        jobs = api.prepare_github_external_reference_jobs("issues", payload)

        assert [job.actor_login for job in jobs] == ["editor"]


class TestGitHubExternalReferenceTask(SimpleTestCase):
    def test_retries_transient_database_failures_without_losing_worker_crashes(self) -> None:
        assert process_github_external_reference.acks_late is True
        assert process_github_external_reference.reject_on_worker_lost is True
        assert process_github_external_reference.autoretry_for == (
            DatabaseError,
            GitHubIntegrationError,
            GitHubRateLimitError,
        )
        assert process_github_external_reference.max_retries == 5
        assert process_github_external_reference.retry_backoff is True
        assert process_github_external_reference.retry_backoff_max == 300
        assert process_github_external_reference.retry_jitter is True


@override_settings(SITE_URL="https://app.example.com")
class TestErrorTrackingGitHubWebhook(SimpleTestCase):
    def setUp(self) -> None:
        reset_consumer_registry()
        cache.clear()
        self.addCleanup(reset_consumer_registry)
        self.addCleanup(cache.clear)

    @parameterized.expand(
        [
            ("issue", "issues", "issue", "issue"),
            ("pull_request", "pull_request", "pull_request", "pull_request"),
        ]
    )
    @patch("products.error_tracking.backend.tasks.github.process_github_external_reference.delay")
    @patch("posthog.ingress.github.provider.get_instance_setting", return_value="webhook-secret")
    def test_verified_delivery_enqueues_supported_events(
        self,
        _name: str,
        event_type: str,
        resource_key: str,
        expected_resource_type: str,
        _get_instance_setting: Mock,
        delay: Mock,
    ) -> None:
        payload = {
            "action": "opened",
            "installation": {"id": 42},
            "repository": {"full_name": "example/app"},
            "sender": {"login": "octocat"},
            resource_key: {
                "number": 7,
                "title": "Fix checkout",
                "body": "https://app.example.com/project/12/error_tracking/00000000-0000-0000-0000-000000000001",
                "user": {"login": "octocat"},
                "author_association": "MEMBER",
            },
        }
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()

        with (
            patch("products.conversations.backend.facade.api.accept_github_event"),
            patch("products.tasks.backend.facade.api.accept_github_event_for_loops"),
            patch("products.tasks.backend.facade.api.accept_github_pull_request"),
            patch("products.workflows.backend.facade.api.accept_github_event"),
        ):
            response = self.client.post(
                "/webhooks/github/",
                data=body,
                content_type="application/json",
                headers={
                    "X-Hub-Signature-256": signature,
                    "X-GitHub-Delivery": f"delivery-{event_type}",
                    "X-GitHub-Event": event_type,
                },
            )

        assert response.status_code == 202
        delay.assert_called_once_with(
            team_id=12,
            installation_id="42",
            repository_full_name="example/app",
            number=7,
            title="Fix checkout",
            resource_type=expected_resource_type,
            actor_login="octocat",
            issue_id="00000000-0000-0000-0000-000000000001",
            fingerprint=None,
        )


@override_settings(SITE_URL="https://app.example.com")
class TestGitHubExternalReferences(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # The repo-permission result is cached per actor, and the cache outlives a rolled-back test.
        cache.clear()
        self.addCleanup(cache.clear)

    @parameterized.expand(
        [
            ("issue", "issues", "issue", "issues"),
            ("pull_request", "pull_request", "pull_request", "pull"),
        ]
    )
    def test_links_referenced_issues_with_team_and_installation_scope(
        self, _name: str, event_type: str, resource_key: str, expected_github_path: str
    ) -> None:
        integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.GITHUB.value,
            integration_id="123",
            config={"account": {"name": "acme"}},
            sensitive_config={"access_token": "access-token"},
        )
        direct_issue = ErrorTrackingIssue.objects.create(team=self.team, name="Direct issue")
        fingerprint_issue = ErrorTrackingIssue.objects.create(team=self.team, name="Fingerprint issue")
        foreign_host_issue = ErrorTrackingIssue.objects.create(team=self.team, name="Foreign host issue")
        fingerprint = "checkout/failure#group"
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=fingerprint_issue, fingerprint=fingerprint)

        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other_issue = ErrorTrackingIssue.objects.create(team=other_team, name="Other issue")

        if event_type == "pull_request":
            ErrorTrackingExternalReference.objects.create(
                issue=direct_issue,
                integration=integration,
                external_context={"repository": "widgets", "number": 17, "title": "Old title"},
            )

        body = "\n".join(
            [
                f"https://app.example.com/project/{self.team.id}/error_tracking/{direct_issue.id}",
                (
                    f"https://app.example.com/project/{self.team.id}/error_tracking/fingerprint/"
                    f"{quote(fingerprint, safe='')}"
                ),
                f"https://app.example.com/project/{other_team.id}/error_tracking/{other_issue.id}",
                f"https://other.example.com/project/{self.team.id}/error_tracking/{foreign_host_issue.id}",
            ]
        )
        payload = {
            "action": "opened",
            "installation": {"id": 123},
            "repository": {"full_name": "acme/widgets"},
            "sender": {"login": "maintainer"},
            resource_key: {
                "number": 17,
                "title": "Fix checkout failures",
                "body": body,
                "user": {"login": "maintainer"},
                "author_association": "MEMBER",
            },
        }

        mismatched_owner_payload = {**payload, "repository": {"full_name": "other/widgets"}}
        assert not any(
            api.link_github_external_reference(job)
            for job in api.prepare_github_external_reference_jobs(event_type, mismatched_owner_payload)
        )

        # An org member with read-only access to the repo passes the payload gate, so the repo
        # permission is the only thing standing between them and a permanent reference.
        read_only_payload = {**payload, "sender": {"login": "onlooker"}}
        with patch.object(GitHubIntegration, "get_collaborator_permission", return_value="read") as read_permission:
            assert not any(
                api.link_github_external_reference(job)
                for job in api.prepare_github_external_reference_jobs(event_type, read_only_payload)
            )
        read_permission.assert_called_with("acme/widgets", "onlooker")
        assert not ErrorTrackingExternalReference.objects.filter(issue=fingerprint_issue).exists()

        jobs = api.prepare_github_external_reference_jobs(event_type, payload)
        with (
            patch.object(GitHubIntegration, "get_collaborator_permission", return_value="write"),
            patch.object(
                ErrorTrackingIssue.objects,
                "select_for_update",
                wraps=ErrorTrackingIssue.objects.select_for_update,
            ) as select_for_update,
        ):
            created_count = sum(api.link_github_external_reference(job) for job in jobs)

        assert select_for_update.call_count == 2
        references = {
            reference.issue_id: reference
            for reference in ErrorTrackingExternalReference.objects.select_related("integration").all()
        }
        assert created_count == (1 if event_type == "pull_request" else 2)
        assert len(jobs) == 3
        assert set(references) == {direct_issue.id, fingerprint_issue.id}
        direct_context = references[direct_issue.id].external_context
        assert direct_context is not None
        assert direct_context["title"] == "Fix checkout failures"
        for reference in references.values():
            resolved_reference = api.get_external_reference(reference.id, self.team.id)
            assert resolved_reference is not None
            assert resolved_reference.external_url == f"https://github.com/acme/widgets/{expected_github_path}/17"
