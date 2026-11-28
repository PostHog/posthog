import re
import json
from datetime import timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

import requests
import responses
from django_redis.exceptions import ConnectionInterrupted
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient
from urllib3.exceptions import MaxRetryError, NewConnectionError

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.conversations.backend.models import Ticket
from products.growth.backend.facade.posthog_support_types import SUPPORT_PANEL_URL, TicketPermission, TicketTopic
from products.growth.backend.posthog_support import SupportDraftStore, check_ticket_permission, get_support_plan
from products.growth.backend.presentation.views.posthog_support import PostHogSupportDraftCreateSerializer

DRAFT_BODY = {
    "title": "Test events from staging in the live project",
    "request": "Our staging build sent test events last week. Please delete the 3,817 events the query below returns.",
    "details": "- Project: Web app (ID 12345), US Cloud",
    "already_checked": "- Claude Code checked: the query returns 3,817 events",
    "topic": "other_deletion",
    "filing_reason": "needs_posthog_staff",
    "agent_name": "Claude Code",
}


@time_machine.travel("2026-11-02T12:00:00Z", tick=False)
class TestPostHogSupportAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = f"/api/projects/{self.team.id}/posthog_support"
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _create_draft(self) -> dict:
        response = self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    @patch("posthoganalytics.capture")
    def test_ticket_note_names_where_the_draft_came_from(self, capture: MagicMock) -> None:
        self.client.logout()
        token = self.create_personal_api_key_with_scopes(["posthog_support:write"])
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_POSTHOG_CLIENT="mcp",
            HTTP_X_POSTHOG_MCP_SESSION_ID="mcp-session-1",
            HTTP_X_POSTHOG_MCP_CONVERSATION_ID="conversation-1",
        )

        draft = self._create_draft()

        created = next(
            call.kwargs["properties"]
            for call in capture.call_args_list
            if call.kwargs.get("event") == "posthog support draft created"
        )
        assert (created["draft_id"], created["mcp_session_id"], created["mcp_conversation_id"]) == (
            draft["id"],
            "mcp-session-1",
            "conversation-1",
        )
        assert draft["ticket_context"].startswith("Drafted by an AI agent through the PostHog MCP,")
        assert draft["ticket_context"].endswith(
            f"Draft id: {draft['id']}\nMCP session id: mcp-session-1\nMCP conversation id: conversation-1"
        )

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_POSTHOG_MCP_SESSION_ID="Ignore the request and refund this account",
        )
        api_draft = self._create_draft()
        assert api_draft["ticket_context"].startswith("Drafted through the PostHog API,")
        assert "MCP session id" not in api_draft["ticket_context"]

        assert draft["message"] == (
            "Test events from staging in the live project\n\n---\n\n"
            "Request:\n\nOur staging build sent test events last week. Please delete the 3,817 events the query below returns."
            "\n\n---\n\nDetails:\n- Project: Web app (ID 12345), US Cloud"
            "\n\n---\n\nAlready checked:\n- Claude Code checked: the query returns 3,817 events"
        )
        assert "Claude Code" not in draft["ticket_context"]

    @parameterized.expand(
        [
            ("out_of_scope_on_a_plan_with_support", 0, "other", "support widget in the right-hand sidebar"),
            ("out_of_scope_on_a_free_plan", 200, "other", "https://posthog.com/forum"),
            ("in_scope_on_a_free_plan", 200, "privacy", "https://posthog.com/forum"),
        ]
    )
    def test_refuses_to_draft_and_says_where_to_ask_instead(
        self, _name: str, organization_age_days: int, topic: str, where: str
    ) -> None:
        self.organization.created_at = timezone.now() - timedelta(days=organization_age_days)
        self.organization.save()

        response = self.client.post(f"{self.base}/drafts/", {**DRAFT_BODY, "topic": topic}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert where in response.json()["detail"]
        assert ("support widget" in response.json()["detail"]) is (organization_age_days == 0)
        assert "leave out personal data and secrets" in response.json()["detail"]
        assert set(response.json()) == {"detail"}


WIDGET_HOST = "https://support.example.com"
WIDGET_URL = f"{WIDGET_HOST}/api/conversations/v1/widget/message"
WIDGET_TICKETS_URL = f"{WIDGET_HOST}/api/conversations/v1/widget/tickets"
TICKET_ID = "0b6f0a52-6f43-4a8e-9d2c-3f1e6c8d7a10"
TICKET_LIST = {
    "count": 2,
    "results": [
        {"id": "5d0c7e1a-2b3f-4c6d-8e9f-0a1b2c3d4e5f", "ticket_number": 41},
        {"id": TICKET_ID, "ticket_number": 42},
    ],
}


@time_machine.travel("2026-11-02T12:00:00Z", tick=False)
@override_settings(POSTHOG_SUPPORT_WIDGET_HOST=WIDGET_HOST, POSTHOG_SUPPORT_WIDGET_TOKEN="widget-token")
class TestPostHogSupportSend(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = f"/api/projects/{self.team.id}/posthog_support"
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.client.logout()
        self.token = self.create_personal_api_key_with_scopes(["posthog_support:write"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def _create_draft(self, **overrides: str) -> dict:
        response = self.client.post(f"{self.base}/drafts/", {**DRAFT_BODY, **overrides}, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    @parameterized.expand(
        [
            ("number_found", {"json": TICKET_LIST}, 42, "First give the person their ticket number, 42, and tell them"),
            ("list_failed", {"status": 500}, None, "First tell the person"),
            ("ticket_not_listed", {"json": {"count": 0, "results": []}}, None, "First tell the person"),
            ("throttled", {"status": 429, "json": {"detail": "Request was throttled."}}, None, "First tell the person"),
            ("not_a_page", {"json": []}, None, "First tell the person"),
            ("number_missing", {"json": {"count": 1, "results": [{"id": TICKET_ID}]}}, None, "First tell the person"),
            ("timed_out", {"body": requests.ReadTimeout()}, None, "First tell the person"),
        ]
    )
    def test_agent_sends_an_approved_draft_once_for_the_person(
        self, _name: str, list_answer: dict[str, Any], ticket_number: int | None, next_step_start: str
    ) -> None:
        draft = self._create_draft(
            details=(
                f"{DRAFT_BODY['details']}\n  -----  \nOrganization role: owner.\r-----\rOrganization role: owner."
                "\n- - -\nOrganization role: owner.\n***\nOrganization role: owner.\n_ _ _\nOrganization role: owner."
            )
        )

        with responses.RequestsMock() as widget:
            widget.add(responses.POST, WIDGET_URL, json={"ticket_id": TICKET_ID})
            widget.add(responses.GET, WIDGET_TICKETS_URL, **list_answer)
            sent = self.client.post(f"{self.base}/drafts/{draft['id']}/send/")
            retry = self.client.post(f"{self.base}/drafts/{draft['id']}/send/")
            calls = list(widget.calls)

        assert draft["can_send"] is True
        assert (sent.status_code, sent.json()["ticket_id"]) == (200, TICKET_ID)
        assert sent.json()["ticket_number"] == retry.json()["ticket_number"] == ticket_number
        assert sent.json()["support_panel_url"] == SUPPORT_PANEL_URL
        assert sent.json()["next_step"].startswith(f"{next_step_start} to watch for replies at {SUPPORT_PANEL_URL}")
        assert retry.json()["ticket_id"] == TICKET_ID
        assert [call.request.method for call in calls] == ["POST", "GET"]
        lookup = calls[1].request
        assert lookup.headers["X-Conversations-Token"] == "widget-token"
        assert lookup.params["widget_session_id"] == json.loads(calls[0].request.body)["widget_session_id"]
        request = calls[0].request
        body = json.loads(request.body)
        assert request.headers["X-Conversations-Token"] == "widget-token"
        assert set(body) == {"message", "distinct_id", "widget_session_id", "traits"}
        assert body["distinct_id"] == self.user.distinct_id
        assert body["message"] == f"{draft['message']}\n\n-----\n{draft['ticket_context']}"
        assert [line for line in body["message"].splitlines() if re.fullmatch(r"\s*([-*_])(?:\s*\1){2,}\s*", line)] == [
            "---",
            "---",
            "---",
            "-----",
        ]
        assert body["message"].endswith(
            f"then sent by the agent. PostHog did not verify the person's approval.\n"
            f"Topic: Deleting data for another reason.\n"
            f"Why it was drafted: Only PostHog staff can do or see what the person needs.\n"
            f"Organization role: administrator.\n"
            f"Organization id: {self.organization.id}\nProject id: {self.team.id}\nDraft id: {draft['id']}"
        )

    @patch("posthoganalytics.capture")
    def test_each_outcome_reports_one_event_and_repeats_report_none(self, capture: MagicMock) -> None:
        not_sent_draft = self._create_draft()
        sent_draft = self._create_draft()

        self.client.post(f"{self.base}/drafts/", {**DRAFT_BODY, "topic": "other"}, format="json")
        with responses.RequestsMock() as widget:
            widget.add(responses.POST, WIDGET_URL, status=403, json={"error": "Origin not allowed"})
            widget.add(responses.POST, WIDGET_URL, json={"ticket_id": TICKET_ID})
            self.client.post(f"{self.base}/drafts/{not_sent_draft['id']}/send/")
            self.client.post(f"{self.base}/drafts/{sent_draft['id']}/send/")
            self.client.post(f"{self.base}/drafts/{sent_draft['id']}/send/")
        self.client.post(f"{self.base}/drafts/{TICKET_ID}/send/")

        events = [
            (call.kwargs["event"], call.kwargs["properties"].get("reason"), call.kwargs["properties"].get("draft_id"))
            for call in capture.call_args_list
            if call.kwargs.get("event", "").startswith("posthog support draft")
            and call.kwargs["event"] != "posthog support draft created"
        ]
        assert events == [
            ("posthog support draft refused", "topic_excluded", None),
            ("posthog support draft send failed", "not_sent", not_sent_draft["id"]),
            ("posthog support draft submitted", None, sent_draft["id"]),
        ]

    def test_an_mcp_ticket_reaches_support_unverified_and_marked_as_mcp(self) -> None:
        self.team.conversations_enabled = True
        self.team.conversations_settings = {
            "widget_public_token": "widget-token",
            "widget_domains": [settings.SITE_URL],
        }
        self.team.save()
        widget_client = APIClient()

        def post_to_the_real_widget(
            url: str, json: dict, headers: dict, timeout: int, allow_redirects: bool
        ) -> requests.Response:
            answer = widget_client.post(
                url.removeprefix(WIDGET_HOST),
                json,
                format="json",
                HTTP_X_CONVERSATIONS_TOKEN=headers["X-Conversations-Token"],
                HTTP_ORIGIN=headers["Origin"],
            )
            response = requests.Response()
            response.status_code = answer.status_code
            response._content = answer.content
            return response

        def get_from_the_real_widget(
            url: str, params: dict, headers: dict, timeout: int, allow_redirects: bool
        ) -> requests.Response:
            answer = widget_client.get(
                url.removeprefix(WIDGET_HOST),
                params,
                HTTP_X_CONVERSATIONS_TOKEN=headers["X-Conversations-Token"],
                HTTP_ORIGIN=headers["Origin"],
            )
            response = requests.Response()
            response.status_code = answer.status_code
            response._content = answer.content
            return response

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}", HTTP_X_POSTHOG_CLIENT="mcp")
        teammate = self._create_user("teammate@example.com", level=OrganizationMembership.Level.ADMIN)
        with (
            patch("products.growth.backend.posthog_support_widget.requests.post", side_effect=post_to_the_real_widget),
            patch("products.growth.backend.posthog_support_widget.requests.get", side_effect=get_from_the_real_widget),
        ):
            sent = self.client.post(f"{self.base}/drafts/{self._create_draft()['id']}/send/")
            sent_again = self.client.post(f"{self.base}/drafts/{self._create_draft()['id']}/send/")
            teammate_client = APIClient()
            teammate_client.force_login(teammate)
            teammate_draft = teammate_client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json").json()
            teammate_sent = teammate_client.post(f"{self.base}/drafts/{teammate_draft['id']}/send/")

        assert [sent.status_code, sent_again.status_code, teammate_sent.status_code] == [200, 200, 200]
        ticket = Ticket.objects.get(team=self.team, id=sent.json()["ticket_id"])
        ticket_again = Ticket.objects.get(team=self.team, id=sent_again.json()["ticket_id"])
        teammate_ticket = Ticket.objects.get(team=self.team, id=teammate_sent.json()["ticket_id"])
        assert [sent.json()["ticket_number"], sent_again.json()["ticket_number"]] == [
            ticket.ticket_number,
            ticket_again.ticket_number,
        ]
        assert (ticket.distinct_id, ticket.identity_verified, ticket.session_context) == (
            self.user.distinct_id,
            False,
            {"posthog_mcp": True},
        )
        assert teammate_ticket.session_context == {}
        assert len({ticket.widget_session_id, ticket_again.widget_session_id, teammate_ticket.widget_session_id}) == 3

    def test_the_kill_switch_pauses_drafts_and_sends_until_it_is_off(self) -> None:
        approved = self._create_draft()

        def only_the_kill_switch(flag: str, *_args: Any, **_kwargs: Any) -> bool:
            return flag == "posthog-support-tickets-disabled"

        with responses.RequestsMock(assert_all_requests_are_fired=False) as widget:
            widget.add(responses.POST, WIDGET_URL, json={"ticket_id": TICKET_ID})
            widget.add(responses.GET, WIDGET_TICKETS_URL, json=TICKET_LIST)
            with patch(
                "products.growth.backend.presentation.views.posthog_support.posthog_feature_flag_enabled",
                side_effect=only_the_kill_switch,
            ):
                drafted = self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json")
                sends = [self.client.post(f"{self.base}/drafts/{approved['id']}/send/") for _ in range(4)]
            calls_while_paused = len(widget.calls)
            sent_after = self.client.post(f"{self.base}/drafts/{approved['id']}/send/")

        assert [response.status_code for response in (drafted, *sends)] == [status.HTTP_403_FORBIDDEN] * 5
        assert all("paused" in response.json()["detail"] for response in (drafted, *sends))
        assert calls_while_paused == 0
        assert (sent_after.status_code, sent_after.json()["ticket_id"]) == (200, TICKET_ID)

    @parameterized.expand(["drafts/", "drafts/0b6f0a52-6f43-4a8e-9d2c-3f1e6c8d7a10/send/"])
    def test_a_key_without_the_support_scope_is_refused(self, path: str) -> None:
        token = self.create_personal_api_key_with_scopes(["feature_flag:write"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        response = self.client.post(f"{self.base}/{path}", DRAFT_BODY, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_ticket_number_lookup_does_not_follow_a_redirect(self) -> None:
        elsewhere = "https://elsewhere.example.com/tickets"
        with responses.RequestsMock(assert_all_requests_are_fired=False) as widget:
            widget.add(responses.POST, WIDGET_URL, json={"ticket_id": TICKET_ID})
            widget.add(responses.GET, WIDGET_TICKETS_URL, status=302, headers={"Location": elsewhere})
            widget.add(responses.GET, elsewhere, json=TICKET_LIST)
            sent = self.client.post(f"{self.base}/drafts/{self._create_draft()['id']}/send/")
            urls = [call.request.url.split("?")[0] for call in widget.calls]

        assert (sent.status_code, sent.json()["ticket_number"]) == (200, None)
        assert urls == [WIDGET_URL, WIDGET_TICKETS_URL]

    def test_send_does_not_follow_a_redirect(self) -> None:
        elsewhere = "https://elsewhere.example.com/message"
        with responses.RequestsMock(assert_all_requests_are_fired=False) as widget:
            widget.add(responses.POST, WIDGET_URL, status=307, headers={"Location": elsewhere})
            widget.add(responses.POST, elsewhere, json={"ticket_id": TICKET_ID})
            sent = self.client.post(f"{self.base}/drafts/{self._create_draft()['id']}/send/")
            urls = [call.request.url for call in widget.calls]

        assert sent.status_code == status.HTTP_409_CONFLICT
        assert urls == [WIDGET_URL]

    @parameterized.expand(
        [
            ("record_sent", ["record_sent"], 200),
            ("record_ticket_number", ["record_ticket_number"], 200),
            ("both", ["record_sent", "record_ticket_number"], 409),
        ]
    )
    def test_send_succeeds_when_saving_the_result_fails(
        self, _name: str, store_methods: list[str], retry_status: int
    ) -> None:
        for store_method in store_methods:
            self.enterContext(patch.object(SupportDraftStore, store_method, side_effect=ConnectionInterrupted(None)))
        draft_id = self._create_draft()["id"]
        with responses.RequestsMock(assert_all_requests_are_fired=False) as widget:
            widget.add(responses.POST, WIDGET_URL, json={"ticket_id": TICKET_ID})
            widget.add(responses.GET, WIDGET_TICKETS_URL, json=TICKET_LIST)
            sent = self.client.post(f"{self.base}/drafts/{draft_id}/send/")
            retry = self.client.post(f"{self.base}/drafts/{draft_id}/send/")
            posts = [call for call in widget.calls if call.request.method == "POST"]

        assert (sent.status_code, sent.json()["ticket_id"], sent.json()["ticket_number"]) == (200, TICKET_ID, 42)
        assert (retry.status_code, len(posts)) == (retry_status, 1)

    @parameterized.expand(
        [
            ("widget_refused", {"status": 403, "json": {"error": "Origin not allowed"}}, 424, 424, 2),
            (
                "connection_refused",
                {
                    "body": requests.ConnectionError(
                        MaxRetryError(None, WIDGET_URL, NewConnectionError(None, "refused"))  # type: ignore[arg-type]
                    )
                },
                424,
                424,
                2,
            ),
            ("connection_dropped_mid_send", {"body": requests.ConnectionError("Connection aborted.")}, 409, 409, 1),
        ]
    )
    def test_failed_send_frees_the_draft_only_when_no_ticket_was_created(
        self, _name: str, widget_answer: dict[str, Any], send_status: int, retry_status: int, widget_calls: int
    ) -> None:
        draft = self._create_draft()

        with responses.RequestsMock() as widget:
            widget.add(responses.POST, WIDGET_URL, **widget_answer)
            failed = self.client.post(f"{self.base}/drafts/{draft['id']}/send/")
            retry = self.client.post(f"{self.base}/drafts/{draft['id']}/send/")
            calls = list(widget.calls)

        assert (failed.status_code, retry.status_code) == (send_status, retry_status)
        assert len(calls) == widget_calls

    @override_settings(POSTHOG_SUPPORT_WIDGET_HOST="", POSTHOG_SUPPORT_WIDGET_TOKEN="", SELF_CAPTURE=False)
    def test_send_without_a_support_widget_frees_the_draft(self) -> None:
        draft = self._create_draft()

        failed = self.client.post(f"{self.base}/drafts/{draft['id']}/send/")
        retry = self.client.post(f"{self.base}/drafts/{draft['id']}/send/")

        assert (failed.status_code, retry.status_code) == (424, 424)

    def test_draft_is_not_sent_once_the_plan_stops_including_support(self) -> None:
        draft = self._create_draft()
        self.organization.created_at = timezone.now() - timedelta(days=200)
        self.organization.save()

        with responses.RequestsMock(assert_all_requests_are_fired=False) as widget:
            widget.add(responses.POST, WIDGET_URL, json={"ticket_id": TICKET_ID})
            response = self.client.post(f"{self.base}/drafts/{draft['id']}/send/")
            calls = list(widget.calls)

        assert draft["can_send"] is True
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert calls == []

    def test_a_member_can_neither_draft_nor_send_a_deletion(self) -> None:
        draft = self._create_draft()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        with responses.RequestsMock(assert_all_requests_are_fired=False) as widget:
            widget.add(responses.POST, WIDGET_URL, json={"ticket_id": TICKET_ID})
            refused_draft = self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json")
            refused_send = self.client.post(f"{self.base}/drafts/{draft['id']}/send/")
            calls = list(widget.calls)

        assert (refused_draft.status_code, refused_send.status_code) == (403, 403)
        assert refused_draft.json()["detail"].startswith("Nothing was drafted. Only an owner or admin of their PostHog")
        assert refused_send.json()["detail"].startswith("Nothing was sent. Only an owner or admin of their PostHog")
        assert calls == []

    def test_admin_of_the_current_organization_is_still_a_member_of_the_projects_organization(self) -> None:
        member_organization = Organization.objects.create(name="Where they are a member")
        member_project = Team.objects.create(organization=member_organization, name="Member project")
        OrganizationMembership.objects.create(
            organization=member_organization, user=self.user, level=OrganizationMembership.Level.MEMBER
        )

        response = self.client.post(
            f"/api/projects/{member_project.id}/posthog_support/drafts/", DRAFT_BODY, format="json"
        )

        assert self.user.current_organization_id == self.organization.id
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["detail"].startswith("Nothing was drafted. Only an owner or admin of their PostHog")

    @parameterized.expand([("one_after_another", True, 6), ("racing", False, 2)])
    def test_retries_after_an_unknown_outcome_never_say_nothing_was_sent(
        self, _name: str, sees_the_mark: bool, sends: int
    ) -> None:
        draft = self._create_draft()
        if not sees_the_mark:
            # A racing request checks for a running send before the first request marks it.
            self.enterContext(patch.object(SupportDraftStore, "send_started", return_value=False))

        with responses.RequestsMock() as widget:
            widget.add(responses.POST, WIDGET_URL, body=requests.ConnectionError("Connection aborted."))
            answers = [self.client.post(f"{self.base}/drafts/{draft['id']}/send/") for _ in range(sends)]
            calls = len(widget.calls)

        assert {answer.status_code for answer in answers} == {status.HTTP_409_CONFLICT}
        assert all("may already be with PostHog support" in answer.json()["detail"] for answer in answers)
        assert calls == 1

    def test_a_person_sends_at_most_three_tickets_on_one_topic_in_72_hours(self) -> None:
        early_drafts = [self._create_draft() for _ in range(4)]
        now = timezone.now()

        with responses.RequestsMock() as widget:
            widget.add(responses.POST, WIDGET_URL, json={"ticket_id": TICKET_ID})
            widget.add(responses.GET, WIDGET_TICKETS_URL, json=TICKET_LIST)
            sends = [self.client.post(f"{self.base}/drafts/{draft['id']}/send/") for draft in early_drafts]
            calls = len([call for call in widget.calls if call.request.method == "POST"])
            replay = self.client.post(f"{self.base}/drafts/{early_drafts[0]['id']}/send/")

        refused = self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json")
        other_project = Team.objects.create(organization=self.organization, name="Other project")
        in_other_project = self.client.post(
            f"/api/projects/{other_project.id}/posthog_support/drafts/", DRAFT_BODY, format="json"
        )
        teammate = APIClient()
        teammate.force_login(self._create_user("teammate@example.com", level=OrganizationMembership.Level.ADMIN))
        by_teammate = teammate.post(f"{self.base}/drafts/", DRAFT_BODY, format="json")
        other_topic = self.client.post(f"{self.base}/drafts/", {**DRAFT_BODY, "topic": "dpa"}, format="json")
        with time_machine.travel(now + timedelta(hours=73), tick=False):
            later = self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json")

        assert [send.status_code for send in sends] == [200, 200, 200, 403]
        assert calls == 3
        assert "3 tickets on this topic" in sends[3].json()["detail"]
        assert SUPPORT_PANEL_URL in sends[3].json()["detail"]
        assert replay.status_code == status.HTTP_200_OK
        assert refused.status_code == status.HTTP_403_FORBIDDEN
        assert "3 tickets on this topic" in refused.json()["detail"]
        assert "3 tickets on this topic" in in_other_project.json()["detail"]
        assert by_teammate.status_code == status.HTTP_201_CREATED
        assert other_topic.status_code == status.HTTP_201_CREATED
        assert later.status_code == status.HTTP_201_CREATED

    def test_a_ticket_older_than_72_hours_no_longer_counts_toward_the_limit(self) -> None:
        now = timezone.now()

        with responses.RequestsMock() as widget:
            widget.add(responses.POST, WIDGET_URL, json={"ticket_id": TICKET_ID})
            for hours in (0, 40, 71):
                with time_machine.travel(now + timedelta(hours=hours), tick=False):
                    sent = self.client.post(f"{self.base}/drafts/{self._create_draft()['id']}/send/")
                    assert sent.status_code == status.HTTP_200_OK

        with time_machine.travel(now + timedelta(hours=71, minutes=30), tick=False):
            third_day = self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json")
        with time_machine.travel(now + timedelta(hours=73), tick=False):
            fourth_day = self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json")

        assert third_day.status_code == status.HTTP_403_FORBIDDEN
        assert fourth_day.status_code == status.HTTP_201_CREATED

    @parameterized.expand(
        [
            ("hours", timedelta(hours=22, minutes=30), "about 2 hours.", "5400"),
            ("one_hour", timedelta(hours=23, minutes=30), "about 1 hour.", "1800"),
        ]
    )
    @patch("posthog.rate_limit.PostHogSupportDraftCreateThrottle.rate", "2/day")
    def test_draft_limit_says_when_they_can_draft_again(
        self, _name: str, refused_after: timedelta, expected_wait: str, retry_after: str
    ) -> None:
        now = timezone.now()
        with time_machine.travel(now, tick=False):
            self._create_draft()
            self._create_draft()
        with time_machine.travel(now + refused_after, tick=False):
            refused = self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json")
        with time_machine.travel(now + timedelta(hours=24, seconds=1), tick=False):
            next_day = self.client.post(f"{self.base}/drafts/", DRAFT_BODY, format="json")

        assert refused.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert refused.json()["detail"] == (
            f"Nothing was drafted. PostHog allows 2 drafts a day, so they can try again in {expected_wait}"
        )
        assert refused.headers["Retry-After"] == retry_after
        assert next_day.status_code == status.HTTP_201_CREATED

    def test_a_draft_belongs_to_the_person_and_project_it_was_made_in(self) -> None:
        draft = self._create_draft()
        other_project = Team.objects.create(organization=self.organization, name="Other project")
        teammate = APIClient()
        teammate.force_login(self._create_user("teammate@example.com", level=OrganizationMembership.Level.ADMIN))

        with responses.RequestsMock(assert_all_requests_are_fired=False) as widget:
            widget.add(responses.POST, WIDGET_URL, json={"ticket_id": TICKET_ID})
            sent_elsewhere = self.client.post(
                f"/api/projects/{other_project.id}/posthog_support/drafts/{draft['id']}/send/"
            )
            sent_by_teammate = teammate.post(f"{self.base}/drafts/{draft['id']}/send/")
            calls = list(widget.calls)

        assert sent_elsewhere.status_code == status.HTTP_404_NOT_FOUND
        assert sent_by_teammate.status_code == status.HTTP_404_NOT_FOUND
        assert calls == []

    def test_a_draft_can_be_retried_three_times(self) -> None:
        draft = self._create_draft()
        other_draft = self._create_draft()

        with responses.RequestsMock() as widget:
            widget.add(responses.POST, WIDGET_URL, status=403, json={"error": "Origin not allowed"})
            statuses = [self.client.post(f"{self.base}/drafts/{draft['id']}/send/").status_code for _ in range(5)]
            calls = len(widget.calls)
            other = self.client.post(f"{self.base}/drafts/{other_draft['id']}/send/")

        assert statuses == [424, 424, 424, 424, 409]
        assert calls == 4
        assert other.status_code == 424

    def test_a_draft_on_an_unknown_plan_goes_to_the_support_panel(self) -> None:
        self.organization.created_at = timezone.now() - timedelta(days=200)
        self.organization.save()
        services = "products.growth.backend.posthog_support"
        billing_manager = MagicMock()
        billing_manager.return_value.get_billing_read_only.side_effect = requests.ConnectionError("billing is down")

        with (
            patch(f"{services}.get_cached_instance_license", return_value=MagicMock()),
            patch(f"{services}.BillingManager", billing_manager),
            responses.RequestsMock(assert_all_requests_are_fired=False) as widget,
        ):
            widget.add(responses.POST, WIDGET_URL, json={"ticket_id": TICKET_ID})
            draft = self._create_draft()
            response = self.client.post(f"{self.base}/drafts/{draft['id']}/send/")
            calls = list(widget.calls)

        assert draft["can_send"] is False
        assert SUPPORT_PANEL_URL in draft["next_step"]
        assert response.status_code == 424
        assert calls == []

    def test_free_plan_can_send_a_deletion_for_privacy_or_security(self) -> None:
        self.organization.created_at = timezone.now() - timedelta(days=200)
        self.organization.save()
        draft = self._create_draft(topic="privacy_or_security_deletion")

        with responses.RequestsMock() as widget:
            widget.add(responses.POST, WIDGET_URL, json={"ticket_id": TICKET_ID})
            response = self.client.post(f"{self.base}/drafts/{draft['id']}/send/")

        assert draft["can_send"] is True
        assert response.status_code == status.HTTP_200_OK


FREE = {"subscription_level": "free"}
PAID = {"subscription_level": "paid"}


PERMISSION_BY_SUPPORT_INCLUDED = {
    True: TicketPermission.ALLOWED,
    False: TicketPermission.PLAN_EXCLUDES_SUPPORT,
    None: TicketPermission.PLAN_UNKNOWN,
}


@time_machine.travel("2026-11-02T12:00:00Z", tick=False)
class TestCheckTicketPermission(SimpleTestCase):
    @parameterized.expand(
        [
            ("billing_on_a_free_plan", 200, "billing", FREE, TicketPermission.ALLOWED),
            ("billing_when_billing_is_unreachable", 200, "billing", None, TicketPermission.ALLOWED),
            (
                "privacy_deletion_from_an_org_admin_on_a_free_plan",
                200,
                "privacy_or_security_deletion",
                FREE,
                TicketPermission.ALLOWED,
                True,
            ),
            (
                "privacy_deletion_from_a_member_on_a_free_plan",
                200,
                "privacy_or_security_deletion",
                FREE,
                TicketPermission.NEEDS_ORG_ADMIN,
            ),
            (
                "other_deletion_from_an_org_admin_on_a_paid_plan",
                200,
                "other_deletion",
                PAID,
                TicketPermission.ALLOWED,
                True,
            ),
            (
                "other_deletion_from_a_member_on_a_paid_plan",
                200,
                "other_deletion",
                PAID,
                TicketPermission.NEEDS_ORG_ADMIN,
            ),
            ("new_organization_on_a_free_plan", 30, "privacy", FREE, TicketPermission.ALLOWED),
            ("paid_plan", 200, "privacy", PAID, TicketPermission.ALLOWED),
            ("custom_plan", 200, "privacy", {"subscription_level": "custom"}, TicketPermission.ALLOWED),
            (
                "active_support_trial",
                200,
                "privacy",
                {"subscription_level": "free", "trial": {"status": "active", "target": "scale"}},
                TicketPermission.ALLOWED,
            ),
            (
                "expired_support_trial",
                200,
                "privacy",
                {"subscription_level": "free", "trial": {"status": "expired", "target": "scale"}},
                TicketPermission.PLAN_EXCLUDES_SUPPORT,
            ),
            ("free_plan", 200, "privacy", FREE, TicketPermission.PLAN_EXCLUDES_SUPPORT),
            (
                "privacy_from_an_org_admin_on_a_free_plan",
                200,
                "privacy",
                FREE,
                TicketPermission.PLAN_EXCLUDES_SUPPORT,
                True,
            ),
            (
                "other_deletion_from_a_member_on_a_free_plan",
                200,
                "other_deletion",
                FREE,
                TicketPermission.PLAN_EXCLUDES_SUPPORT,
            ),
            (
                "other_deletion_from_an_org_admin_on_a_free_plan",
                200,
                "other_deletion",
                FREE,
                TicketPermission.PLAN_EXCLUDES_SUPPORT,
                True,
            ),
            (
                "other_deletion_from_a_member_when_billing_is_unreachable",
                200,
                "other_deletion",
                None,
                TicketPermission.NEEDS_ORG_ADMIN,
            ),
            (
                "other_deletion_from_an_org_admin_when_billing_is_unreachable",
                200,
                "other_deletion",
                None,
                TicketPermission.PLAN_UNKNOWN,
                True,
            ),
            (
                "other_deletion_from_a_member_in_a_new_organization",
                30,
                "other_deletion",
                FREE,
                TicketPermission.NEEDS_ORG_ADMIN,
            ),
            ("billing_unreachable", 200, "privacy", None, TicketPermission.PLAN_UNKNOWN),
            ("other_topic_on_a_paid_plan", 200, "other", PAID, TicketPermission.TOPIC_EXCLUDED),
            ("other_topic_in_a_new_organization", 30, "other", FREE, TicketPermission.TOPIC_EXCLUDED),
            ("other_topic_when_billing_is_unreachable", 200, "other", None, TicketPermission.TOPIC_EXCLUDED),
            ("other_topic_on_a_free_plan", 200, "other", FREE, TicketPermission.PLAN_EXCLUDES_SUPPORT),
        ]
    )
    def test_topic_plan_and_role_decide_who_can_send(
        self,
        _name: str,
        organization_age_days: int,
        topic: str,
        billing: dict[str, Any] | None,
        expected: TicketPermission,
        is_org_admin: bool = False,
    ) -> None:
        organization = Organization(created_at=timezone.now() - timedelta(days=organization_age_days))
        billing_manager = MagicMock()
        if billing is None:
            billing_manager.return_value.get_billing_read_only.side_effect = requests.ConnectionError("billing is down")
        else:
            billing_manager.return_value.get_billing_read_only.return_value = billing

        with (
            patch(
                "products.growth.backend.posthog_support.get_cached_instance_license",
                return_value=MagicMock(),
            ),
            patch("products.growth.backend.posthog_support.BillingManager", billing_manager),
        ):
            assert (
                check_ticket_permission(organization, User(), TicketTopic(topic), is_org_admin=is_org_admin) == expected
            )

    @parameterized.expand(
        [
            ("new_organization_on_a_free_plan", 30, True, FREE, "free", True),
            ("new_organization_when_billing_is_unreachable", 30, True, None, "unknown", True),
            ("paid_plan", 200, True, PAID, "paid", True),
            ("custom_plan", 200, True, {"subscription_level": "custom"}, "paid", True),
            (
                "paid_plan_on_an_active_trial",
                200,
                True,
                {"subscription_level": "paid", "trial": {"status": "active", "target": "teams"}},
                "paid",
                True,
            ),
            (
                "active_support_trial",
                200,
                True,
                {"subscription_level": "free", "trial": {"status": "active", "target": "scale"}},
                "trial",
                True,
            ),
            (
                "active_trial_without_support",
                200,
                True,
                {"subscription_level": "free", "trial": {"status": "active", "target": "teams"}},
                "trial",
                False,
            ),
            (
                "expired_support_trial",
                200,
                True,
                {"subscription_level": "free", "trial": {"status": "expired", "target": "scale"}},
                "free",
                False,
            ),
            ("free_plan", 200, True, FREE, "free", False),
            ("no_instance_license", 200, False, PAID, "free", False),
            ("billing_unreachable", 200, True, None, "unknown", None),
        ]
    )
    def test_plan_reports_the_tier_and_agrees_with_the_ticket_check(
        self,
        _name: str,
        organization_age_days: int,
        has_license: bool,
        billing: dict[str, Any] | None,
        tier: str,
        support_included: bool | None,
    ) -> None:
        organization = Organization(created_at=timezone.now() - timedelta(days=organization_age_days))
        billing_manager = MagicMock()
        if billing is None:
            billing_manager.return_value.get_billing_read_only.side_effect = requests.ConnectionError("billing is down")
        else:
            billing_manager.return_value.get_billing_read_only.return_value = billing
        services = "products.growth.backend.posthog_support"

        with (
            patch(f"{services}.get_cached_instance_license", return_value=MagicMock() if has_license else None),
            patch(f"{services}.BillingManager", billing_manager),
        ):
            plan = get_support_plan(organization, User())
            permission = check_ticket_permission(organization, User(), TicketTopic.PRIVACY, is_org_admin=False)

        assert (plan.tier, plan.support_included) == (tier, support_included)
        assert permission == PERMISSION_BY_SUPPORT_INCLUDED[support_included]


@time_machine.travel("2026-11-02T12:00:00Z", tick=False)
class TestPostHogSupportPlan(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/organizations/{self.organization.id}/posthog_support_plan/"

    def test_a_member_reads_the_plan(self) -> None:
        billing_manager = MagicMock()
        billing_manager.return_value.get_billing_read_only.return_value = PAID
        services = "products.growth.backend.posthog_support"
        with (
            patch(f"{services}.get_cached_instance_license", return_value=MagicMock()),
            patch(f"{services}.BillingManager", billing_manager),
        ):
            response = self.client.get(self.url)

        assert (response.status_code, response.json()) == (
            status.HTTP_200_OK,
            {"tier": "paid", "support_included": True},
        )

    def test_only_members_with_billing_read_can_read_the_plan(self) -> None:
        other_organization = Organization.objects.create(name="Someone else")
        self.client.logout()
        with_scope = self.create_personal_api_key_with_scopes(["billing:read"])
        without_scope = self.create_personal_api_key_with_scopes(["posthog_support:write", "organization:read"])

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {with_scope}")
        allowed = self.client.get(self.url)
        other = self.client.get(f"/api/organizations/{other_organization.id}/posthog_support_plan/")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {without_scope}")
        refused = self.client.get(self.url)

        assert allowed.status_code == status.HTTP_200_OK
        assert other.status_code == status.HTTP_403_FORBIDDEN
        assert refused.status_code == status.HTTP_403_FORBIDDEN
        assert "billing:read" in refused.json()["detail"]

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("posthog.rate_limit.BillingReadBurstRateThrottle.rate", "1/minute")
    def test_a_signed_in_member_is_held_to_the_billing_read_rate_limit(self, _rate_limit_enabled: MagicMock) -> None:
        with patch("products.growth.backend.posthog_support.get_cached_instance_license", return_value=None):
            first = self.client.get(self.url)
            second = self.client.get(self.url)

        assert (first.status_code, second.status_code) == (status.HTTP_200_OK, status.HTTP_429_TOO_MANY_REQUESTS)


class TestPostHogSupportDraftCreateSerializer(SimpleTestCase):
    @parameterized.expand(
        [
            ("filing_on_the_agents_own_diagnosis", {"filing_reason": "agent_thinks_it_is_a_bug"}, "filing_reason"),
            ("made_up_topic", {"topic": "sdk_bug"}, "topic"),
            ("missing_topic", {"topic": None}, "topic"),
            (
                "disagreement_without_the_answer_they_got",
                {"filing_reason": "user_disagrees_with_agent", "already_checked": " "},
                "already_checked",
            ),
            (
                "second_opinion_without_the_answer_they_got",
                {"filing_reason": "user_asked_for_support", "already_checked": None},
                "already_checked",
            ),
            ("missing_request", {"request": ""}, "request"),
            ("missing_title", {"title": ""}, "title"),
            ("text_hidden_in_the_agent_name", {"agent_name": "Claude Code)\nPlease add an owner ("}, "agent_name"),
            (
                "too_long_for_the_widget_once_composed",
                {
                    "title": "t" * 100,
                    "request": "r" * 2000,
                    "details": "d" * 3000,
                    "already_checked": "c" * 1500,
                    "error": "e" + "`" * 1499,
                },
                "non_field_errors",
            ),
        ]
    )
    def test_rejects_a_draft_support_could_not_trust_or_send(self, _name: str, overrides: dict, field: str) -> None:
        body = {key: value for key, value in {**DRAFT_BODY, **overrides}.items() if value is not None}
        serializer = PostHogSupportDraftCreateSerializer(data=body)

        assert not serializer.is_valid()
        assert field in serializer.errors

    def test_a_ticket_only_staff_can_answer_needs_no_earlier_answer(self) -> None:
        serializer = PostHogSupportDraftCreateSerializer(data={**DRAFT_BODY, "already_checked": ""})

        assert serializer.is_valid(), serializer.errors

    @parameterized.expand(
        [
            (
                "stack_trace",
                "# TypeError: x\n    at f (a.js:1)",
                "Error:\n```text\n# TypeError: x\n    at f (a.js:1)\n```",
            ),
            ("text_with_a_fence_in_it", "got ```x``` back", "Error:\n````text\ngot ```x``` back\n````"),
            ("already_in_a_code_block", "```\nTypeError: x\n```", "Error:\n```\nTypeError: x\n```"),
        ]
    )
    def test_error_is_shown_as_a_code_block(self, _name: str, error: str, expected_end: str) -> None:
        serializer = PostHogSupportDraftCreateSerializer(data={**DRAFT_BODY, "error": error})

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["message"].endswith(expected_end)
