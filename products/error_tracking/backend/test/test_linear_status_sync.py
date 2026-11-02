import hmac
import json
import time
from collections import Counter
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

import redis.exceptions as redis_exceptions
from celery.exceptions import Retry
from parameterized import parameterized

from posthog.ingress.dispatch.loading import reset_consumer_registry
from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.integration import Integration, LinearIntegrationError

from products.error_tracking.backend.facade import contracts, issues
from products.error_tracking.backend.models import (
    ErrorTrackingExternalReference,
    ErrorTrackingIssue,
    ErrorTrackingSettings,
)
from products.error_tracking.backend.tasks.linear import process_linear_status_sync

ORGANIZATION_ID = "linear-org-1"
PREVIOUS_STATE_ID = "state-previous"


def _state_change_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "type": "Issue",
        "action": "update",
        "organizationId": ORGANIZATION_ID,
        "data": {"identifier": "ENG-1", "previousIdentifiers": ["OPS-7"]},
        "updatedFrom": {"stateId": PREVIOUS_STATE_ID},
        **overrides,
    }


class _FakeLinear:
    """Answers the Linear GraphQL reads the sync makes, from the ticket states a test sets."""

    def __init__(
        self,
        ticket_states: dict[str, str],
        previous_state_type: str | None,
        *,
        failing_tokens: frozenset[str] = frozenset(),
        rate_limited_tokens: dict[str, int] | None = None,
        tokens_without_previous_state: frozenset[str] = frozenset(),
    ) -> None:
        self.ticket_states = ticket_states
        self.previous_state_type = previous_state_type
        self.failing_tokens = failing_tokens
        self.tokens_without_previous_state = tokens_without_previous_state
        self.rate_limited_tokens = rate_limited_tokens or {}
        self.requests_by_token: Counter[str] = Counter()

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: int) -> Mock:
        query, variables = json["query"], json["variables"]
        token = headers["Authorization"].removeprefix("Bearer ")
        self.requests_by_token[token] += 1
        if token in self.rate_limited_tokens:
            reset_ms = int((time.time() + self.rate_limited_tokens[token]) * 1000)
            return Mock(
                status_code=429,
                headers={"X-RateLimit-Requests-Reset": str(reset_ms)},
                json=Mock(return_value={"errors": [{"extensions": {"code": "RATELIMITED"}}]}),
            )
        if token in self.failing_tokens:
            body: dict[str, Any] = {"errors": [{"message": "Authentication required"}]}
        elif "IssueStates" in query:
            wanted = {(match["team"]["key"]["eq"], match["number"]["eq"]) for match in variables["filter"]["or"]}
            nodes = [
                {"identifier": identifier, "state": {"type": state_type}}
                for identifier, state_type in self.ticket_states.items()
                if (identifier.split("-")[0], int(identifier.split("-")[1])) in wanted
            ]
            body = {"data": {"issues": {"nodes": nodes}}}
        elif "WorkflowStateType" in query:
            assert variables["id"] == PREVIOUS_STATE_ID
            visible = token not in self.tokens_without_previous_state
            nodes = [{"type": self.previous_state_type}] if self.previous_state_type and visible else []
            body = {"data": {"workflowStates": {"nodes": nodes}}}
        else:
            raise AssertionError(f"Unexpected Linear query: {query}")
        return Mock(status_code=200, headers={}, json=Mock(return_value=body))


class TestPrepareLinearStatusSyncJob(SimpleTestCase):
    @parameterized.expand(
        [
            ("title_edit", _state_change_payload(updatedFrom={"title": "Old title"})),
            ("created_ticket", _state_change_payload(action="create")),
            ("comment", _state_change_payload(type="Comment")),
            ("missing_workspace", _state_change_payload(organizationId=None)),
        ]
    )
    def test_ignores_deliveries_that_do_not_change_a_ticket_state(self, _name: str, payload: dict[str, Any]) -> None:
        assert issues.prepare_linear_status_sync_job(payload) is None

    def test_carries_identifiers_from_before_a_team_move(self) -> None:
        assert issues.prepare_linear_status_sync_job(_state_change_payload()) == contracts.LinearStatusSyncJob(
            organization_id=ORGANIZATION_ID,
            identifiers=("ENG-1", "OPS-7"),
            previous_state_id=PREVIOUS_STATE_ID,
        )


@override_settings(LINEAR_APP_WEBHOOK_SECRET="linear-secret")
class TestErrorTrackingLinearWebhook(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        reset_consumer_registry()
        cache.clear()
        self.addCleanup(reset_consumer_registry)
        self.addCleanup(cache.clear)
        self.addCleanup(patch.stopall)
        # `pytest.ini` sets DEBUG, which rewrites both region domains to localhost hosts. `testserver`
        # is the primary region here, because that is the region the Linear App's one webhook URL names.
        patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver").start()
        patch("posthog.regions.SECONDARY_REGION_DOMAIN", "us.posthog.com").start()
        self.forward = patch("posthog.ingress.dispatch.forward.requests.request").start()
        self.forward.return_value = Mock(status_code=200, ok=True)
        self.delay = patch("products.error_tracking.backend.tasks.linear.process_linear_status_sync.delay").start()

    def _post_status(self, payload: dict[str, Any]) -> int:
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

    def test_state_change_from_a_workspace_held_here_enqueues_the_sync_without_a_forward(self) -> None:
        Integration.objects.create(
            team=self.team, kind=Integration.IntegrationKind.LINEAR.value, integration_id=ORGANIZATION_ID
        )

        assert self._post_status(_state_change_payload()) == 200
        self.forward.assert_not_called()
        self.delay.assert_called_once_with(
            organization_id=ORGANIZATION_ID,
            identifiers=["ENG-1", "OPS-7"],
            previous_state_id=PREVIOUS_STATE_ID,
        )

    @parameterized.expand(
        [
            ("state_change_is_forwarded", _state_change_payload(), True),
            ("title_edit_stays_here", _state_change_payload(updatedFrom={"title": "Old title"}), False),
        ]
    )
    def test_delivery_from_a_workspace_held_elsewhere(
        self, _name: str, payload: dict[str, Any], forwarded: bool
    ) -> None:
        assert self._post_status(payload) == 200
        assert [call.kwargs["url"] for call in self.forward.call_args_list] == (
            ["https://us.posthog.com/webhooks/linear/"] if forwarded else []
        )


class TestLinearStatusSync(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._opt_in(self.team)

    def _opt_in(self, team: Team) -> None:
        ErrorTrackingSettings.objects.create(team=team, linear_status_sync_enabled=True)

    def _linear_integration(
        self, team: Team, organization_id: str = ORGANIZATION_ID, token: str = "linear-token"
    ) -> Integration:
        return Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.LINEAR.value,
            integration_id=organization_id,
            sensitive_config={"access_token": token},
        )

    def _linked_issue(
        self, team: Team, integration: Integration, identifiers: list[str], status: str = "active"
    ) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=team, name="Checkout failed", status=status)
        for identifier in identifiers:
            ErrorTrackingExternalReference.objects.create(
                issue=issue, integration=integration, external_context={"id": identifier}
            )
        return issue

    def _sync(self, linear: _FakeLinear, identifiers: tuple[str, ...] = ("ENG-1",)) -> None:
        with patch("posthog.models.integration.linear.requests.post", side_effect=linear.post):
            process_linear_status_sync(
                organization_id=ORGANIZATION_ID, identifiers=list(identifiers), previous_state_id=PREVIOUS_STATE_ID
            )

    @parameterized.expand(
        [
            ("done_resolves", ["ENG-1"], {"ENG-1": "completed"}, "started", "active", "resolved"),
            ("canceled_alone_does_not_resolve", ["ENG-1"], {"ENG-1": "canceled"}, "started", "active", "active"),
            (
                "waits_for_every_linked_ticket",
                ["ENG-1", "ENG-2"],
                {"ENG-1": "completed", "ENG-2": "started"},
                "started",
                "active",
                "active",
            ),
            (
                "done_and_canceled_resolves",
                ["ENG-1", "ENG-2"],
                {"ENG-1": "completed", "ENG-2": "canceled"},
                "started",
                "active",
                "resolved",
            ),
            (
                "unreturned_ticket_holds_the_issue_open",
                ["ENG-1", "ENG-9"],
                {"ENG-1": "completed"},
                "started",
                "active",
                "active",
            ),
            ("reopened_ticket_reactivates", ["ENG-1"], {"ENG-1": "started"}, "completed", "resolved", "active"),
            (
                "move_between_open_states_keeps_resolved",
                ["ENG-1"],
                {"ENG-1": "started"},
                "unstarted",
                "resolved",
                "resolved",
            ),
            (
                "suppressed_issue_is_left_alone",
                ["ENG-1"],
                {"ENG-1": "completed"},
                "started",
                "suppressed",
                "suppressed",
            ),
        ]
    )
    def test_issue_status_follows_linked_ticket_states(
        self,
        _name: str,
        linked: list[str],
        ticket_states: dict[str, str],
        previous_state_type: str,
        initial_status: str,
        expected_status: str,
    ) -> None:
        issue = self._linked_issue(self.team, self._linear_integration(self.team), linked, status=initial_status)

        self._sync(_FakeLinear(ticket_states, previous_state_type))

        issue.refresh_from_db()
        assert issue.status == expected_status
        system_status_changes = ActivityLog.objects.filter(
            team_id=self.team.id, scope="ErrorTrackingIssue", item_id=str(issue.id), is_system=True
        )
        assert system_status_changes.count() == (0 if expected_status == initial_status else 1)

    def test_changes_only_opted_in_projects_linked_through_the_same_workspace(self) -> None:
        linked_issue = self._linked_issue(self.team, self._linear_integration(self.team), ["ENG-1"])
        other_workspace_issue = self._linked_issue(
            self.team, self._linear_integration(self.team, organization_id="linear-org-2"), ["ENG-1"]
        )
        opted_in_team = Team.objects.create(organization=self.organization, name="Opted in")
        self._opt_in(opted_in_team)
        opted_in_issue = self._linked_issue(opted_in_team, self._linear_integration(opted_in_team), ["ENG-1"])
        not_opted_in_team = Team.objects.create(organization=self.organization, name="Not opted in")
        not_opted_in_issue = self._linked_issue(
            not_opted_in_team, self._linear_integration(not_opted_in_team), ["ENG-1"]
        )

        self._sync(_FakeLinear({"ENG-1": "completed"}, "started"))

        statuses = dict(
            ErrorTrackingIssue.objects.filter(
                id__in=[linked_issue.id, other_workspace_issue.id, opted_in_issue.id, not_opted_in_issue.id]
            ).values_list("id", "status")
        )
        assert statuses == {
            linked_issue.id: "resolved",
            other_workspace_issue.id: "active",
            opted_in_issue.id: "resolved",
            not_opted_in_issue.id: "active",
        }

    @parameterized.expand([("move_job_first", True), ("completion_job_first", False)])
    def test_a_ticket_that_moved_teams_holds_its_issue_open_until_it_closes(
        self, _name: str, move_job_first: bool
    ) -> None:
        issue = self._linked_issue(self.team, self._linear_integration(self.team), ["ENG-1", "OPS-7"])
        linear = _FakeLinear({"ENG-1": "completed", "ENG-2": "started"}, "started")
        move_job, completion_job = ("ENG-2", "OPS-7"), ("ENG-1",)

        for identifiers in (move_job, completion_job) if move_job_first else (completion_job, move_job):
            self._sync(linear, identifiers=identifiers)
        issue.refresh_from_db()
        assert issue.status == "active"

        linear.ticket_states["ENG-2"] = "completed"
        self._sync(linear, identifiers=("ENG-2",))
        issue.refresh_from_db()
        assert issue.status == "resolved"

    def test_each_project_reads_the_previous_state_with_its_own_token(self) -> None:
        blind_team = Team.objects.create(organization=self.organization, name="Cannot see the previous team")
        self._opt_in(blind_team)
        blind_issue = self._linked_issue(
            blind_team, self._linear_integration(blind_team, token="blind-token"), ["ENG-1"], status="resolved"
        )
        seeing_issue = self._linked_issue(self.team, self._linear_integration(self.team), ["ENG-1"], status="resolved")
        linear = _FakeLinear(
            {"ENG-1": "started"}, "completed", tokens_without_previous_state=frozenset({"blind-token"})
        )

        self._sync(linear)

        statuses = dict(
            ErrorTrackingIssue.objects.filter(id__in=[blind_issue.id, seeing_issue.id]).values_list("id", "status")
        )
        assert statuses == {blind_issue.id: "resolved", seeing_issue.id: "active"}

    def test_a_project_whose_linear_read_fails_raises_without_holding_back_the_others(self) -> None:
        revoked_team = Team.objects.create(organization=self.organization, name="Revoked token")
        self._opt_in(revoked_team)
        failing_issue = self._linked_issue(
            revoked_team, self._linear_integration(revoked_team, token="revoked-token"), ["ENG-1"]
        )
        working_issue = self._linked_issue(self.team, self._linear_integration(self.team), ["ENG-1"])
        linear = _FakeLinear({"ENG-1": "completed"}, "started", failing_tokens=frozenset({"revoked-token"}))

        with (
            patch("posthog.models.integration.linear.requests.post", side_effect=linear.post),
            self.assertRaises(LinearIntegrationError),
        ):
            issues.sync_linear_status(
                contracts.LinearStatusSyncJob(
                    organization_id=ORGANIZATION_ID, identifiers=("ENG-1",), previous_state_id=PREVIOUS_STATE_ID
                )
            )

        statuses = dict(
            ErrorTrackingIssue.objects.filter(id__in=[failing_issue.id, working_issue.id]).values_list("id", "status")
        )
        assert statuses == {failing_issue.id: "active", working_issue.id: "resolved"}

    @parameterized.expand([("alone", False), ("behind_a_project_whose_read_fails", True)])
    def test_a_rate_limited_read_retries_once_linear_resets_the_limit(
        self, _name: str, failing_project_first: bool
    ) -> None:
        if failing_project_first:
            revoked_team = Team.objects.create(organization=self.organization, name="Revoked token")
            self._opt_in(revoked_team)
            self._linked_issue(revoked_team, self._linear_integration(revoked_team, token="revoked-token"), ["ENG-1"])
        integration = self._linear_integration(self.team)
        self._linked_issue(self.team, integration, ["ENG-1"])
        self._linked_issue(self.team, integration, ["ENG-1"])
        linear = _FakeLinear(
            {"ENG-1": "completed"},
            "started",
            failing_tokens=frozenset({"revoked-token"}),
            rate_limited_tokens={"linear-token": 900},
        )

        with (
            patch.object(process_linear_status_sync, "retry", side_effect=Retry()) as retry,
            self.assertRaises(Retry),
        ):
            self._sync(linear)

        assert 899 <= retry.call_args.kwargs["countdown"] <= 900
        assert linear.requests_by_token["linear-token"] == 1

    @parameterized.expand(
        [("connection_error", redis_exceptions.ConnectionError), ("timeout", redis_exceptions.TimeoutError)]
    )
    def test_a_redis_failure_on_the_issue_lock_retries(self, _name: str, error: type[Exception]) -> None:
        self._linked_issue(self.team, self._linear_integration(self.team), ["ENG-1"])
        redis_client = Mock()
        redis_client.lock.return_value.acquire.side_effect = error("Redis is unreachable")

        with (
            patch("products.error_tracking.backend.logic.linear_status_sync.get_client", return_value=redis_client),
            patch.object(process_linear_status_sync, "retry", side_effect=Retry()) as retry,
            self.assertRaises(Retry),
        ):
            self._sync(_FakeLinear({"ENG-1": "completed"}, "started"))

        assert isinstance(retry.call_args.kwargs["exc"], error)
