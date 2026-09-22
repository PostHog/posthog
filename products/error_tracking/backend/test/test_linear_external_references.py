import hmac
import json
import hashlib

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.db import DatabaseError
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve

import requests
from parameterized import parameterized

from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.models import Team
from posthog.models.integration import Integration, LinearIntegration

from products.error_tracking.backend.facade import api, contracts
from products.error_tracking.backend.models import ErrorTrackingExternalReference, ErrorTrackingIssue
from products.error_tracking.backend.tasks.linear import process_linear_external_reference

LINKED_BODY = "https://app.example.com/project/12/error_tracking/00000000-0000-0000-0000-000000000001"


@override_settings(SITE_URL="https://app.example.com")
class TestPrepareLinearExternalReferenceJob(SimpleTestCase):
    def _issue_payload(self) -> dict:
        return {
            "action": "create",
            "organizationId": "workspace-1",
            "data": {
                "identifier": "ENG-123",
                "title": "Fix checkout",
                "description": LINKED_BODY,
            },
        }

    @parameterized.expand(
        [
            ("wrong_event_type", "ProjectUpdate"),
            ("removed", "Issue"),
            ("unrelated_update", "Issue"),
            ("blank_text", "Issue"),
            ("missing_workspace", "Issue"),
            ("malformed_identifier", "Issue"),
        ]
    )
    def test_rejects_ineligible_events(self, case: str, event_type: str) -> None:
        payload = self._issue_payload()
        if case == "removed":
            payload["action"] = "remove"
        elif case == "unrelated_update":
            payload["action"] = "update"
            payload["updatedFrom"] = {"title": "Old title"}
        elif case == "blank_text":
            payload["data"]["description"] = " "
        elif case == "missing_workspace":
            payload.pop("organizationId")
        elif case == "malformed_identifier":
            payload["data"]["identifier"] = "../ENG-123"

        assert api.prepare_linear_external_reference_jobs(event_type, payload) == []

    def test_update_without_updated_from_still_prepares_a_job(self) -> None:
        payload = self._issue_payload()
        payload["action"] = "update"

        jobs = api.prepare_linear_external_reference_jobs("Issue", payload)

        assert len(jobs) == 1
        assert jobs[0].identifier == "ENG-123"

    @parameterized.expand(
        [
            ("parent_issue", "ENG-123", "Fix checkout", None, "ENG-123", "Fix checkout"),
            ("url_fallback", None, "", "https://linear.app/acme/issue/ENG-456/fix-checkout", "ENG-456", "ENG-456"),
            ("no_parent_issue", None, None, "https://linear.app/acme/issue/ENG-789/fix-checkout", "ENG-789", "ENG-789"),
        ]
    )
    def test_comment_uses_parent_issue_context(
        self,
        _name: str,
        identifier: str | None,
        title: str | None,
        url: str | None,
        expected_identifier: str,
        expected_title: str,
    ) -> None:
        data: dict = {"body": LINKED_BODY}
        if title is not None:
            parent_issue = {"title": title}
            if identifier is not None:
                parent_issue["identifier"] = identifier
            data["issue"] = parent_issue
        payload = {
            "action": "create",
            "organizationId": "workspace-1",
            "url": url,
            "data": data,
        }

        jobs = api.prepare_linear_external_reference_jobs("Comment", payload)

        assert len(jobs) == 1
        assert jobs[0].identifier == expected_identifier
        assert jobs[0].title == expected_title

    def test_truncates_a_title_longer_than_the_reference_limit(self) -> None:
        payload = self._issue_payload()
        payload["data"]["title"] = "a" * 600

        jobs = api.prepare_linear_external_reference_jobs("Issue", payload)

        assert [len(job.title) for job in jobs] == [500]


class TestLinearExternalReferenceTask(SimpleTestCase):
    def test_retries_transport_and_database_failures_without_losing_worker_crashes(self) -> None:
        assert process_linear_external_reference.acks_late is True
        assert process_linear_external_reference.reject_on_worker_lost is True
        assert process_linear_external_reference.autoretry_for == (DatabaseError, requests.RequestException)
        assert process_linear_external_reference.max_retries == 5
        assert process_linear_external_reference.retry_backoff is True
        assert process_linear_external_reference.retry_backoff_max == 300
        assert process_linear_external_reference.retry_jitter is True


@override_settings(SITE_URL="https://app.example.com")
class TestErrorTrackingLinearWebhook(SimpleTestCase):
    def setUp(self) -> None:
        reset_consumer_registry()
        cache.clear()
        self.addCleanup(reset_consumer_registry)
        self.addCleanup(cache.clear)

    @patch("products.error_tracking.backend.tasks.linear.process_linear_external_reference.delay")
    @patch("posthog.ingress.linear.provider.get_instance_setting", return_value="webhook-secret")
    def test_verified_delivery_enqueues_an_issue_event(self, _get_instance_setting: Mock, delay: Mock) -> None:
        payload = {
            "action": "create",
            "organizationId": "workspace-1",
            "data": {
                "identifier": "ENG-123",
                "title": "Fix checkout",
                "description": LINKED_BODY,
            },
        }
        body = json.dumps(payload).encode()
        signature = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
        request = RequestFactory().post(
            "/webhooks/linear",
            data=body,
            content_type="application/json",
            headers={
                "Linear-Signature": signature,
                "Linear-Delivery": "8cb58466-0219-492a-ad29-38e645969738",
                "Linear-Event": "Issue",
            },
        )

        response = resolve("/webhooks/linear").func(request)

        assert response.status_code == 202
        delay.assert_called_once_with(
            team_id=12,
            organization_id="workspace-1",
            identifier="ENG-123",
            title="Fix checkout",
            issue_id="00000000-0000-0000-0000-000000000001",
            fingerprint=None,
        )


@override_settings(SITE_URL="https://app.example.com")
class TestLinearExternalReferences(BaseTest):
    def _job(self, issue: ErrorTrackingIssue) -> contracts.LinearExternalReferenceJob:
        return contracts.LinearExternalReferenceJob(
            team_id=self.team.id,
            organization_id="workspace-1",
            identifier="ENG-123",
            title="Fix checkout",
            issue_id=issue.id,
        )

    @parameterized.expand([("no_workspace_match", False), ("workspace_on_another_team", True)])
    def test_does_not_link_without_a_team_scoped_workspace_integration(
        self, _name: str, integration_on_other_team: bool
    ) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="Checkout failed")
        if integration_on_other_team:
            other_team = Team.objects.create(organization=self.organization, name="Other team")
            Integration.objects.create(
                team=other_team,
                kind=Integration.IntegrationKind.LINEAR.value,
                integration_id="workspace-1",
                config={"data": {"viewer": {"organization": {"urlKey": "acme"}}}},
                sensitive_config={"access_token": "access-token"},
            )

        assert not api.link_linear_external_reference(self._job(issue))
        assert not ErrorTrackingExternalReference.objects.exists()

    def test_creates_an_idempotent_reference_without_attaching_a_backlink(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="Checkout failed")
        integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.LINEAR.value,
            integration_id="workspace-1",
            config={"data": {"viewer": {"organization": {"urlKey": "acme"}}}},
            sensitive_config={"access_token": "access-token"},
        )

        with patch.object(LinearIntegration, "create_attachment") as create_attachment:
            assert api.link_linear_external_reference(self._job(issue))
            assert not api.link_linear_external_reference(self._job(issue))

        create_attachment.assert_not_called()
        reference = ErrorTrackingExternalReference.objects.get()
        assert reference.issue_id == issue.id
        assert reference.integration_id == integration.id
        assert reference.external_context == {"id": "ENG-123", "title": "Fix checkout"}
