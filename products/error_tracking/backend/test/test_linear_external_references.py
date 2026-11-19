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
from celery.exceptions import Retry
from parameterized import parameterized
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)

from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.models import Team
from posthog.models.integration import Integration, LinearIntegrationError

from products.error_tracking.backend.facade import api, contracts
from products.error_tracking.backend.facade.linear import enqueue_linear_external_references
from products.error_tracking.backend.models import (
    ErrorTrackingExternalReference,
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
)
from products.error_tracking.backend.tasks.linear import process_linear_external_reference

ORGANIZATION_ID = "linear-org-1"
ISSUE_ID = "00000000-0000-0000-0000-000000000001"
TICKET_ID = "00000000-0000-0000-0000-000000000002"
ACTOR_ID = "00000000-0000-0000-0000-000000000003"
LINKED_DESCRIPTION = f"Seen in https://app.example.com/project/12/error_tracking/{ISSUE_ID}"


def _ticket_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "type": "Issue",
        "action": "create",
        "organizationId": ORGANIZATION_ID,
        "actor": {"id": ACTOR_ID, "type": "user"},
        **overrides,
        "data": {
            "id": TICKET_ID,
            **overrides.get(
                "data", {"identifier": "ENG-1", "title": "Checkout fails", "description": LINKED_DESCRIPTION}
            ),
        },
    }


class _FakeLinear:
    def __init__(
        self,
        readable_identifiers: set[str],
        *,
        actor: dict[str, Any] | None = None,
        visibility: str = "public",
        team_member: bool = False,
        current_identifier: str = "ENG-1",
        ticket_states: dict[str, str] | None = None,
        rate_limit_seconds: int | None = None,
    ) -> None:
        self.readable_identifiers = readable_identifiers
        self.actor = {
            "id": ACTOR_ID,
            "active": True,
            "app": False,
            "canAccessAnyPublicTeam": True,
            "organization": {"id": ORGANIZATION_ID},
            **(actor or {}),
        }
        self.visibility = visibility
        self.team_member = team_member
        self.current_identifier = current_identifier
        self.ticket_states = ticket_states or dict.fromkeys(readable_identifiers, "started")
        self.rate_limit_seconds = rate_limit_seconds
        self.request_count = 0
        self.authority_requests: list[str] = []

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int) -> Mock:
        query, variables = json["query"], json["variables"]
        self.request_count += 1
        if self.rate_limit_seconds:
            return Mock(
                status_code=429,
                headers={"X-RateLimit-Requests-Reset": str(int((time.time() + self.rate_limit_seconds) * 1000))},
                json=Mock(return_value={"errors": [{"extensions": {"code": "RATELIMITED"}}]}),
            )
        if "ReferenceAuthority" in query:
            self.authority_requests.append(headers["Authorization"])
            assert variables == {"issueId": TICKET_ID, "actorId": ACTOR_ID}
            nodes = (
                [
                    {
                        "id": TICKET_ID,
                        "identifier": self.current_identifier,
                        "previousIdentifiers": ["ENG-1"] if self.current_identifier != "ENG-1" else [],
                        "team": {
                            "visibility": self.visibility,
                            "organization": {"id": ORGANIZATION_ID},
                            "members": {"nodes": [{"id": ACTOR_ID}] if self.team_member else []},
                        },
                    }
                ]
                if self.current_identifier in self.readable_identifiers
                else []
            )
            body = {"data": {"issues": {"nodes": nodes}, "users": {"nodes": [self.actor]}}}
        elif "IssueStates" in query:
            wanted = {(match["team"]["key"]["eq"], match["number"]["eq"]) for match in variables["filter"]["or"]}
            nodes = [
                {"identifier": identifier, "state": {"type": state}}
                for identifier, state in self.ticket_states.items()
                if (identifier.split("-")[0], int(identifier.split("-")[1])) in wanted
                and identifier in self.readable_identifiers
            ]
            body = {"data": {"issues": {"nodes": nodes}}}
        else:
            raise AssertionError(f"Unexpected Linear query: {query}")
        return Mock(status_code=200, headers={}, json=Mock(return_value=body))


@override_settings(SITE_URL="https://app.example.com")
class TestPrepareLinearExternalReferenceJobs(SimpleTestCase):
    @parameterized.expand(
        [
            ("state_change", _ticket_payload(action="update", updatedFrom={"stateId": "state-1"})),
            ("removed_ticket", _ticket_payload(action="remove")),
            ("comment", _ticket_payload(type="Comment")),
            ("missing_workspace", _ticket_payload(organizationId=None)),
            ("missing_actor", _ticket_payload(actor=None)),
            ("external_actor", _ticket_payload(actor={"id": ACTOR_ID, "type": "externalUser"})),
            ("app_actor", _ticket_payload(actor={"id": ACTOR_ID, "type": "integration"})),
            ("invalid_actor_id", _ticket_payload(actor={"id": "not-a-uuid", "type": "user"})),
            ("invalid_ticket_id", _ticket_payload(data={"id": "not-a-uuid", "description": LINKED_DESCRIPTION})),
            (
                "overlong_project_id",
                _ticket_payload(
                    data={
                        "identifier": "ENG-1",
                        "description": "https://app.example.com/project/"
                        + "1" * 4301
                        + "/error_tracking/fingerprint/example",
                    }
                ),
            ),
            (
                "out_of_range_project_id",
                _ticket_payload(
                    data={
                        "identifier": "ENG-1",
                        "description": "https://app.example.com/project/9223372036854775808/error_tracking/fingerprint/example",
                    }
                ),
            ),
            (
                "embedded_origin",
                _ticket_payload(
                    data={
                        "identifier": "ENG-1",
                        "description": "https://other.example.com/https://app.example.com/project/12/error_tracking/"
                        + ISSUE_ID,
                    }
                ),
            ),
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
                ticket_id=UUID(TICKET_ID),
                actor_id=UUID(ACTOR_ID),
                identifier="ENG-1",
                title="Checkout fails",
                issue_id=UUID(ISSUE_ID),
            ),
            contracts.LinearExternalReferenceJob(
                team_id=12,
                organization_id=ORGANIZATION_ID,
                ticket_id=UUID(TICKET_ID),
                actor_id=UUID(ACTOR_ID),
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
            RedisConnectionError,
            RedisTimeoutError,
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
                "ticket_id": TICKET_ID,
                "actor_id": ACTOR_ID,
                "identifier": "ENG-1",
                "title": "Checkout fails",
                "references": [{"issue_id": ISSUE_ID, "fingerprint": None}],
            },
            countdown=60,
        )

    @parameterized.expand(
        [
            ("linked_ticket_is_forwarded", LINKED_DESCRIPTION, True),
            (
                "link_to_another_region_is_forwarded",
                f"https://us.posthog.com/project/12/error_tracking/{ISSUE_ID}",
                True,
            ),
            ("unlinked_ticket_stays_here", "Checkout fails on Safari", False),
            ("unrelated_origin_stays_here", f"https://example.org/project/12/error_tracking/{ISSUE_ID}", False),
            (
                "overlong_project_id_stays_here",
                "https://app.example.com/project/" + "1" * 4301 + "/error_tracking/fingerprint/example",
                False,
            ),
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

    @parameterized.expand([("allowed", True), ("denied", False)])
    def test_one_access_read_per_project_for_multiple_references(self, _name: str, allowed: bool) -> None:
        first = ErrorTrackingIssue.objects.create(team=self.team)
        second = ErrorTrackingIssue.objects.create(team=self.team)
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        third = ErrorTrackingIssue.objects.create(team=other_team)
        Integration.objects.create(
            team=other_team,
            kind=Integration.IntegrationKind.LINEAR.value,
            integration_id=ORGANIZATION_ID,
            sensitive_config={"access_token": "other-token"},
        )
        targets = (first, second, third)
        description = "\n".join(
            f"https://app.example.com/project/{issue.team_id}/error_tracking/{issue.id}" for issue in targets
        )
        linear = _FakeLinear({"ENG-1"} if allowed else set())
        with (
            patch.object(process_linear_external_reference, "apply_async") as queue,
            patch("posthog.models.integration.linear.requests.post", side_effect=linear.post),
        ):
            enqueue_linear_external_references(
                _ticket_payload(
                    data={
                        "identifier": "ENG-1",
                        "title": "Checkout fails",
                        "description": description,
                    }
                )
            )
            messages = [call.kwargs for call in queue.call_args_list]
            for message in messages:
                process_linear_external_reference(**message["kwargs"])

        assert len(messages) == 2
        assert linear.authority_requests == ["Bearer linear-token", "Bearer other-token"]
        assert set(ErrorTrackingExternalReference.objects.values_list("issue_id", flat=True)) == (
            {issue.id for issue in targets} if allowed else set()
        )

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

    @parameterized.expand([("readable", True, True), ("revoked", False, True), ("actor_revoked", True, False)])
    def test_a_later_edit_refreshes_the_title_only_while_the_ticket_is_readable(
        self, _name: str, readable: bool, actor_active: bool
    ) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="Checkout failed")
        description = f"https://app.example.com/project/{self.team.id}/error_tracking/{issue.id}"
        assert self._link(_FakeLinear({"ENG-1"}), description) == [True]

        linear = _FakeLinear({"ENG-1"} if readable else set(), actor={"active": actor_active})
        renamed = self._link(
            linear,
            description,
            action="update",
            updatedFrom={"title": "Checkout fails"},
            data={"identifier": "ENG-1", "title": "Checkout fails on Safari", "description": description},
        )

        assert renamed == [False]
        reference = ErrorTrackingExternalReference.objects.get(issue=issue)
        assert reference.external_context == {
            "id": "ENG-1",
            "title": "Checkout fails on Safari" if readable and actor_active else "Checkout fails",
        }

    @parameterized.expand(
        [
            ("inactive_actor", {"active": False}, "public", False, False),
            ("app_actor", {"app": True}, "public", False, False),
            ("different_workspace", {"organization": {"id": "other-workspace"}}, "public", False, False),
            ("different_actor", {"id": ISSUE_ID}, "public", True, False),
            ("missing_active_flag", {"active": None}, "public", True, False),
            ("public_team_writer", {}, "public", False, True),
            ("private_team_nonmember", {}, "private", False, False),
            ("private_team_member", {}, "private", True, True),
            ("restricted_team_nonmember", {}, "restricted", False, False),
            ("restricted_team_member", {}, "restricted", True, True),
            ("guest_outside_team", {"canAccessAnyPublicTeam": False}, "public", False, False),
            ("guest_in_team", {"canAccessAnyPublicTeam": False}, "public", True, True),
            ("unknown_team_visibility", {}, "unknown", True, False),
        ]
    )
    def test_only_an_actor_with_team_write_access_can_link(
        self, _name: str, actor: dict[str, Any], visibility: str, team_member: bool, allowed: bool
    ) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        linear = _FakeLinear({"ENG-1"}, actor=actor, visibility=visibility, team_member=team_member)

        assert self._link(linear, f"https://app.example.com/project/{self.team.id}/error_tracking/{issue.id}") == [
            allowed
        ]
        assert ErrorTrackingExternalReference.objects.filter(issue=issue).exists() == allowed

    @parameterized.expand([("new_link", False), ("existing_link", True)])
    def test_a_ticket_that_moves_during_the_delay_links_with_its_current_identifier(
        self, _name: str, existing_link: bool
    ) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        if existing_link:
            ErrorTrackingExternalReference.objects.create(
                issue=issue, integration=self.integration, external_context={"id": "ENG-1"}
            )
        linear = _FakeLinear({"OPS-2"}, current_identifier="OPS-2")
        with patch("posthog.models.integration.linear.requests.post", side_effect=linear.post):
            process_linear_external_reference(
                team_id=self.team.id,
                organization_id=ORGANIZATION_ID,
                ticket_id=TICKET_ID,
                actor_id=ACTOR_ID,
                identifier="ENG-1",
                title="Checkout fails",
                issue_id=str(issue.id),
                fingerprint=None,
            )

        assert list(
            ErrorTrackingExternalReference.objects.filter(issue=issue).values_list("external_context", flat=True)
        ) == [{"id": "OPS-2", "title": "Checkout fails"}]

    @parameterized.expand(
        [
            ("completed", {"ENG-1": "completed"}, "active", "resolved", True),
            ("canceled", {"ENG-1": "canceled"}, "active", "active", True),
            ("another_ticket_open", {"ENG-1": "completed", "ENG-2": "started"}, "active", "active", True),
            ("already_resolved", {"ENG-1": "started"}, "resolved", "resolved", True),
            ("switched_off", {"ENG-1": "completed"}, "active", "active", False),
        ]
    )
    def test_linking_reconciles_current_ticket_states(
        self, _name: str, states: dict[str, str], initial: str, expected: str, enabled: bool
    ) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, status=initial)
        if "ENG-2" in states:
            ErrorTrackingExternalReference.objects.create(
                issue=issue, integration=self.integration, external_context={"id": "ENG-2"}
            )
        linear = _FakeLinear(set(states), ticket_states=states)

        with patch("posthoganalytics.feature_enabled", return_value=enabled):
            assert self._link(linear, f"https://app.example.com/project/{self.team.id}/error_tracking/{issue.id}") == [
                True
            ]
        issue.refresh_from_db()
        assert issue.status == expected

    def test_a_rate_limited_link_retries_after_linear_resets_its_limit(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        linear = _FakeLinear({"ENG-1"}, rate_limit_seconds=900)

        def schedule_retry(*args: Any, **kwargs: Any) -> None:
            raise Retry(exc=kwargs.get("exc"), when=kwargs["countdown"])

        with (
            patch("posthog.models.integration.linear.requests.post", side_effect=linear.post),
            patch.object(process_linear_external_reference, "retry", side_effect=schedule_retry),
            self.assertRaises(Retry) as retry,
        ):
            process_linear_external_reference(
                team_id=self.team.id,
                organization_id=ORGANIZATION_ID,
                ticket_id=TICKET_ID,
                actor_id=ACTOR_ID,
                identifier="ENG-1",
                title=None,
                issue_id=str(issue.id),
                fingerprint=None,
            )

        assert 899 <= retry.exception.when <= 900
        assert not ErrorTrackingExternalReference.objects.filter(issue=issue).exists()

    def test_a_retry_reconciles_a_reference_stored_before_a_failed_status_read(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        description = f"https://app.example.com/project/{self.team.id}/error_tracking/{issue.id}"
        linear = _FakeLinear({"ENG-1"}, ticket_states={"ENG-1": "completed"})

        def failing_status_read(*args: Any, **kwargs: Any) -> Mock:
            if "IssueStates" in kwargs["json"]["query"]:
                raise requests.ConnectionError("Linear is unavailable")
            return linear.post(*args, **kwargs)

        with (
            patch("posthog.models.integration.linear.requests.post", side_effect=failing_status_read),
            self.assertRaises(requests.ConnectionError),
        ):
            for job in api.prepare_linear_external_reference_jobs(
                _ticket_payload(
                    data={
                        "identifier": "ENG-1",
                        "description": description,
                    }
                )
            ):
                api.link_linear_external_reference(job)

        assert self._link(linear, description) == [False]
        issue.refresh_from_db()
        assert issue.status == "resolved"
        assert ErrorTrackingExternalReference.objects.filter(issue=issue).count() == 1

    def test_ignores_links_the_project_cannot_back(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="Checkout failed")
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other_issue = ErrorTrackingIssue.objects.create(team=other_team, name="Other issue")

        assert self._link(
            _FakeLinear({"ENG-1"}),
            f"https://app.example.com/project/{self.team.id}/error_tracking/{issue.id}",
            organizationId="linear-org-2",
        ) == [False]
        assert self._link(
            _FakeLinear({"ENG-1"}),
            f"https://app.example.com/project/{other_team.id}/error_tracking/{other_issue.id}",
        ) == [False]
        assert self._link(
            _FakeLinear({"ENG-1"}),
            f"https://app.example.com/project/{self.team.id}/error_tracking/{other_issue.id}",
        ) == [False]
        assert self._link(
            _FakeLinear(set()), f"https://app.example.com/project/{self.team.id}/error_tracking/{issue.id}"
        ) == [False]

        assert not ErrorTrackingExternalReference.objects.exists()
        self.capture.assert_not_called()
