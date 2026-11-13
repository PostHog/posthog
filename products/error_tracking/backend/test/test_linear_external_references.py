import hmac
import json
import time
from typing import Any
from urllib.parse import quote
from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, Mock, patch

from django.core.cache import cache
from django.db import DatabaseError
from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.models import Team
from posthog.models.integration import Integration, LinearIntegrationError

from products.error_tracking.backend.facade import api, contracts
from products.error_tracking.backend.models import (
    ErrorTrackingExternalReference,
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
)
from products.error_tracking.backend.tasks.linear import process_linear_external_reference

ORGANIZATION_ID = "linear-org-1"
ISSUE_ID = "00000000-0000-0000-0000-000000000001"
LINKED_DESCRIPTION = f"Seen in https://app.example.com/project/12/error_tracking/{ISSUE_ID}"


def _ticket_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "type": "Issue",
        "action": "create",
        "organizationId": ORGANIZATION_ID,
        "data": {"identifier": "ENG-1", "title": "Checkout fails", "description": LINKED_DESCRIPTION},
        **overrides,
    }


class _FakeLinear:
    """Answers the ticket read the link makes, and fails on any other Linear request."""

    def __init__(self, readable_identifiers: set[str]) -> None:
        self.readable_identifiers = readable_identifiers
        self.request_count = 0

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int) -> Mock:
        query, variables = json["query"], json["variables"]
        self.request_count += 1
        if "IssueStates" not in query:
            raise AssertionError(f"Unexpected Linear query: {query}")
        wanted = {(match["team"]["key"]["eq"], match["number"]["eq"]) for match in variables["filter"]["or"]}
        nodes = [
            {"identifier": identifier, "state": {"type": "started"}}
            for identifier in self.readable_identifiers
            if (identifier.split("-")[0], int(identifier.split("-")[1])) in wanted
        ]
        return Mock(status_code=200, headers={}, json=Mock(return_value={"data": {"issues": {"nodes": nodes}}}))


@override_settings(SITE_URL="https://app.example.com")
class TestPrepareLinearExternalReferenceJobs(SimpleTestCase):
    @parameterized.expand(
        [
            ("state_change", _ticket_payload(action="update", updatedFrom={"stateId": "state-1"})),
            ("removed_ticket", _ticket_payload(action="remove")),
            ("comment", _ticket_payload(type="Comment")),
            ("missing_workspace", _ticket_payload(organizationId=None)),
            (
                "malformed_identifier",
                _ticket_payload(data={"identifier": "../ENG-1", "description": LINKED_DESCRIPTION}),
            ),
            ("missing_description", _ticket_payload(data={"identifier": "ENG-1", "description": None})),
            (
                "link_to_another_region",
                _ticket_payload(
                    data={
                        "identifier": "ENG-1",
                        "description": f"https://other.example.com/project/12/error_tracking/{ISSUE_ID}",
                    }
                ),
            ),
        ]
    )
    def test_ignores_deliveries_with_nothing_to_link(self, _name: str, payload: dict[str, Any]) -> None:
        assert api.prepare_linear_external_reference_jobs(payload) == []

    @parameterized.expand(
        [
            ("created_ticket", _ticket_payload()),
            ("description_edit", _ticket_payload(action="update", updatedFrom={"description": "Old"})),
            ("title_edit", _ticket_payload(action="update", updatedFrom={"title": "Old"})),
        ]
    )
    def test_prepares_one_job_per_linked_issue(self, _name: str, payload: dict[str, Any]) -> None:
        payload["data"]["description"] += "\nhttps://app.example.com/project/12/error-tracking/fingerprint/a%2Fb"

        assert api.prepare_linear_external_reference_jobs(payload) == [
            contracts.LinearExternalReferenceJob(
                team_id=12,
                organization_id=ORGANIZATION_ID,
                identifier="ENG-1",
                title="Checkout fails",
                issue_id=UUID(ISSUE_ID),
            ),
            contracts.LinearExternalReferenceJob(
                team_id=12,
                organization_id=ORGANIZATION_ID,
                identifier="ENG-1",
                title="Checkout fails",
                fingerprint="a/b",
            ),
        ]


class TestLinearExternalReferenceTask(SimpleTestCase):
    def test_retries_transient_failures_without_losing_worker_crashes(self) -> None:
        assert process_linear_external_reference.acks_late is True
        assert process_linear_external_reference.reject_on_worker_lost is True
        assert process_linear_external_reference.autoretry_for == (
            DatabaseError,
            LinearIntegrationError,
            requests.RequestException,
        )
        assert process_linear_external_reference.max_retries == 5


@override_settings(LINEAR_APP_WEBHOOK_SECRET="linear-secret", SITE_URL="https://app.example.com")
class TestErrorTrackingLinearExternalReferenceWebhook(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        reset_consumer_registry()
        cache.clear()
        self.addCleanup(reset_consumer_registry)
        self.addCleanup(cache.clear)
        self.addCleanup(patch.stopall)
        # `testserver` is the primary region, because that is the region the Linear App's one webhook URL names.
        patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver").start()
        patch("posthog.regions.SECONDARY_REGION_DOMAIN", "us.posthog.com").start()
        self.forward = patch("posthog.ingress.dispatch.forward.requests.request").start()
        self.forward.return_value = Mock(status_code=200, ok=True)
        self.apply_async = patch(
            "products.error_tracking.backend.tasks.linear.process_linear_external_reference.apply_async"
        ).start()

    def _post(self, payload: dict[str, Any]) -> int:
        body = json.dumps({**payload, "webhookTimestamp": int(time.time() * 1000)}).encode()
        return self.client.post(
            "/webhooks/linear/",
            data=body,
            content_type="application/json",
            headers={
                "Linear-Signature": hmac.digest(b"linear-secret", body, "sha256").hex(),
                "Linear-Delivery": "delivery-1",
                "Linear-Event": "Issue",
            },
            secure=True,
        ).status_code

    def test_ticket_from_a_workspace_held_here_enqueues_the_link_without_a_forward(self) -> None:
        Integration.objects.create(
            team=self.team, kind=Integration.IntegrationKind.LINEAR.value, integration_id=ORGANIZATION_ID
        )

        assert self._post(_ticket_payload()) == 200
        self.forward.assert_not_called()
        self.apply_async.assert_called_once_with(
            kwargs={
                "team_id": 12,
                "organization_id": ORGANIZATION_ID,
                "identifier": "ENG-1",
                "title": "Checkout fails",
                "issue_id": ISSUE_ID,
                "fingerprint": None,
            },
            countdown=60,
        )

    @parameterized.expand(
        [
            ("linked_ticket_is_forwarded", LINKED_DESCRIPTION, True),
            (
                "link_to_another_region_is_forwarded",
                f"https://us.example.com/project/12/error_tracking/{ISSUE_ID}",
                True,
            ),
            ("unlinked_ticket_stays_here", "Checkout fails on Safari", False),
        ]
    )
    def test_ticket_from_a_workspace_held_elsewhere(self, _name: str, description: str, forwarded: bool) -> None:
        payload = _ticket_payload(data={"identifier": "ENG-1", "title": "Checkout fails", "description": description})

        assert self._post(payload) == 200
        assert [call.kwargs["url"] for call in self.forward.call_args_list] == (
            ["https://us.posthog.com/webhooks/linear/"] if forwarded else []
        )


@override_settings(SITE_URL="https://app.example.com")
class TestLinearExternalReferences(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.LINEAR.value,
            integration_id=ORGANIZATION_ID,
            sensitive_config={"access_token": "linear-token"},
        )
        self.capture = MagicMock()
        scoped_capture = patch(
            "products.error_tracking.backend.logic.linear_external_references.ph_scoped_capture"
        ).start()
        scoped_capture.return_value.__enter__.return_value = self.capture
        self.addCleanup(patch.stopall)

    def _link(self, linear: _FakeLinear, description: str, **overrides: Any) -> list[bool]:
        payload = _ticket_payload(
            **{"data": {"identifier": "ENG-1", "title": "Checkout fails", "description": description}, **overrides}
        )
        with patch("posthog.models.integration.linear.requests.post", side_effect=linear.post):
            return [
                api.link_linear_external_reference(job) for job in api.prepare_linear_external_reference_jobs(payload)
            ]

    def test_links_the_issues_a_ticket_points_at_without_writing_to_linear(self) -> None:
        direct_issue = ErrorTrackingIssue.objects.create(team=self.team, name="Direct issue")
        fingerprint_issue = ErrorTrackingIssue.objects.create(team=self.team, name="Fingerprint issue")
        fingerprint = "checkout/failure#group"
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=fingerprint_issue, fingerprint=fingerprint)
        description = "\n".join(
            [
                f"https://app.example.com/project/{self.team.id}/error-tracking/{direct_issue.id}",
                (
                    f"https://app.example.com/project/{self.team.id}/error_tracking/fingerprint/"
                    f"{quote(fingerprint, safe='')}"
                ),
            ]
        )

        assert self._link(_FakeLinear({"ENG-1"}), description) == [True, True]

        references = ErrorTrackingExternalReference.objects.filter(integration=self.integration)
        assert {reference.issue_id: reference.external_context for reference in references} == {
            direct_issue.id: {"id": "ENG-1", "title": "Checkout fails"},
            fingerprint_issue.id: {"id": "ENG-1", "title": "Checkout fails"},
        }
        assert [call.kwargs["event"] for call in self.capture.call_args_list] == [
            "error_tracking_issue_linked_from_linear"
        ] * 2

    def test_a_later_edit_refreshes_the_title_without_a_second_reference_or_linear_read(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="Checkout failed")
        description = f"https://app.example.com/project/{self.team.id}/error_tracking/{issue.id}"
        assert self._link(_FakeLinear({"ENG-1"}), description) == [True]

        linear = _FakeLinear({"ENG-1"})
        renamed = self._link(
            linear,
            description,
            action="update",
            updatedFrom={"title": "Checkout fails"},
            data={"identifier": "ENG-1", "title": "Checkout fails on Safari", "description": description},
        )

        assert renamed == [False]
        assert linear.request_count == 0
        reference = ErrorTrackingExternalReference.objects.get(issue=issue)
        assert reference.external_context == {"id": "ENG-1", "title": "Checkout fails on Safari"}

    def test_ignores_links_the_project_cannot_back(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="Checkout failed")
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other_issue = ErrorTrackingIssue.objects.create(team=other_team, name="Other issue")

        # The ticket's workspace is not the one this project connects.
        assert self._link(
            _FakeLinear({"ENG-1"}),
            f"https://app.example.com/project/{self.team.id}/error_tracking/{issue.id}",
            organizationId="linear-org-2",
        ) == [False]
        # The project that holds the issue connects no Linear workspace.
        assert self._link(
            _FakeLinear({"ENG-1"}),
            f"https://app.example.com/project/{other_team.id}/error_tracking/{other_issue.id}",
        ) == [False]
        # The issue id belongs to another project.
        assert self._link(
            _FakeLinear({"ENG-1"}),
            f"https://app.example.com/project/{self.team.id}/error_tracking/{other_issue.id}",
        ) == [False]
        # The project's token cannot read the ticket, so the status sync could never read its state.
        assert self._link(
            _FakeLinear(set()), f"https://app.example.com/project/{self.team.id}/error_tracking/{issue.id}"
        ) == [False]

        assert not ErrorTrackingExternalReference.objects.exists()
        self.capture.assert_not_called()
