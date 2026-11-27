"""Let a logged-in user's agent draft a ticket to PostHog support, for the person to approve.

The agent shows the person the draft in chat. When the person approves it there, the agent sends it,
and the server posts it to PostHog support for the person.
"""

from __future__ import annotations

import re
import math
from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import Throttled
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import MCP_TRANSPORT_EVENT_SOURCES, get_event_source, report_user_action, sanitize_header_value
from posthog.models.user import User
from posthog.permissions import posthog_feature_flag_enabled
from posthog.rate_limit import PostHogSupportDraftCreateThrottle

from products.growth.backend.facade.posthog_support import (
    SupportDraftRefused,
    SupportTicketSendFailed,
    compose_ticket_message,
    draft_support_ticket,
    send_support_ticket,
)
from products.growth.backend.facade.posthog_support_types import (
    ANSWERED_FILING_REASONS,
    MAX_TICKETS_PER_TOPIC,
    SUPPORT_PANEL_URL,
    DraftedVia,
    DraftRefusal,
    FilingReason,
    SendFailure,
    SentSupportTicketResult,
    SupportDraft,
    TicketPermission,
    TicketTopic,
)

DRAFT_ID_PATTERN = r"[0-9a-f-]{36}"
# Any caller can set the MCP headers, and the ids end up in a ticket note the person cannot edit, so a
# value that could carry words is dropped.
MCP_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")


def _mcp_id(value: str | None) -> str | None:
    value = sanitize_header_value(value)
    return value if value and MCP_ID_PATTERN.fullmatch(value) else None


class PostHogSupportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="What went wrong.")


# The field caps add up to well under the support widget's 10,000-character message limit, with room
# for the headings and the note the server appends, so a valid draft always sends.
class PostHogSupportDraftCreateSerializer(serializers.Serializer):
    title = serializers.CharField(
        max_length=100,
        help_text=(
            "A short title that names the problem, such as 'Delete test events that contain customer emails'. "
            "It opens the ticket, and ticket lists show it, so don't start it with 'Request'."
        ),
    )
    request = serializers.CharField(
        max_length=2000,
        help_text=(
            "The whole ask, in the person's voice. Open with what happened in one sentence, with the numbers and "
            "dates. Then add the action they need in one sentence, or list every question the docs did not answer, "
            "numbered in the person's order, with every part of each question. When they heard your answer and "
            "still want a human, give your answer in one sentence, as yours."
        ),
    )
    details = serializers.CharField(
        max_length=3000,
        required=False,
        allow_blank=True,
        help_text=(
            "Markdown bullets of facts support needs: the project and the region, a link to each object involved, "
            "SDK and version, and every required detail for the kind of request, such as a deletion query and its "
            "count. Link each object on its name, such as '- Project: [Web app](<link>)', and put the "
            "region on its own line. Take links from _posthogUrl. No guesses."
        ),
    )
    already_checked = serializers.CharField(
        max_length=1500,
        required=False,
        allow_blank=True,
        help_text=(
            "Markdown bullets of what was already checked, each with its result. Start a docs check with 'Docs:' and "
            "link the page on its title, "
            "a lookup you ran in this conversation with '<your name> checked:', and a step the person took with "
            "'I tried:'. When filing_reason is user_disagrees_with_agent or user_asked_for_support, this is required: add the "
            "answer you already gave them, with a link to each docs page it came from. List only your checks that "
            "bear on the open questions, because support can look up the "
            "rest of your calls. Never write a number the person gave you as your own check."
        ),
    )
    error = serializers.CharField(
        max_length=1500,
        required=False,
        allow_blank=True,
        help_text=(
            "The exact text of an error the person saw, and its top frames. A lookup of yours that failed goes in "
            "already_checked. Remove any credential and say that you removed it."
        ),
    )
    topic = serializers.ChoiceField(
        choices=TicketTopic.choices,
        help_text=(
            "What the ticket as a whole is about. Only privacy, security, compliance, retention, deletion, DPA, BAA and "
            "billing tickets can be filed from here. Use other for everything else, and don't stretch a topic to fit: "
            "support sees the topic. A login problem is other, never security. Use privacy_or_security_deletion only when the person gave a privacy or security "
            "reason for the deletion. Use billing only when the ticket is about billing or usage, not for a billing "
            "question asked in passing."
        ),
    )
    filing_reason = serializers.ChoiceField(
        choices=FilingReason.choices,
        help_text=(
            "Why a human at PostHog should look at this. Your own conclusion that it is a PostHog bug is not a reason."
        ),
    )
    agent_name = serializers.RegexField(
        r"^[\w .\-]{1,40}$",
        required=False,
        allow_blank=True,
        help_text="Name of the agent or client drafting the ticket, such as Claude Code or Codex.",
    )

    def validate(self, data: dict[str, Any]) -> dict[str, Any]:
        if data["filing_reason"] in ANSWERED_FILING_REASONS and not data.get("already_checked"):
            raise serializers.ValidationError(
                {
                    "already_checked": "Add the answer you already gave them, with a link to each docs page it came from. "
                    "If you did not answer them, use needs_posthog_staff."
                }
            )
        data["message"] = compose_ticket_message(
            title=data["title"],
            request=data["request"],
            details=data.get("details"),
            already_checked=data.get("already_checked"),
            error=data.get("error"),
        )
        return data


class PostHogSupportDraftSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Draft id.")
    message = serializers.CharField(
        help_text="Ticket text as drafted. The sent ticket holds exactly this, then the note in ticket_context."
    )
    ticket_context = serializers.CharField(
        help_text="Note filed under the ticket for support, saying an agent drafted it and why."
    )
    expires_at = serializers.IntegerField(help_text="Unix time after which the draft is gone if nobody sent it.")
    can_send = serializers.BooleanField(
        help_text="True when the person's plan lets them send this ticket. Offer to send it only when this is true."
    )
    next_step = serializers.CharField(help_text="What to tell the person now.")


class PostHogSupportSentTicketSerializer(serializers.Serializer):
    ticket_id = serializers.CharField(help_text="Id of the ticket PostHog support received.")
    ticket_number = serializers.IntegerField(
        allow_null=True,
        help_text="The ticket's number, to give the person. Null when PostHog support did not return it.",
    )
    support_panel_url = serializers.CharField(help_text="Support panel in PostHog, where the person reads replies.")
    next_step = serializers.CharField(help_text="What to tell the person now.")


COMMUNITY_URL = "https://posthog.com/forum"
PAUSED_DETAIL = (
    "Nothing was sent to PostHog support, because PostHog has paused support tickets from agents for now. "
    f"Tell the person to try again later, or to ask in the support panel at {SUPPORT_PANEL_URL} if their plan "
    "includes support."
)
KILL_SWITCH_FLAG = "posthog-support-tickets-disabled"

COMMUNITY_SUPPORT = (
    f"community support is available at {COMMUNITY_URL}. The forum is public, so leave out personal data and secrets."
)

NEXT_STEP_BY_PERMISSION = {
    TicketPermission.ALLOWED: (
        "Nothing has been sent. Show the person the full message above and ask whether to send it to PostHog "
        "support. Call posthog-support-draft-send only after they say yes in this conversation. If they want "
        "a change, draft it again and show them the new version. Do not tell them the ticket was filed."
    ),
    TicketPermission.PLAN_UNKNOWN: (
        "Nothing has been sent. PostHog couldn't check their plan, so don't offer to send it from here. Show "
        f"them the message and tell them they can ask in the support panel at {SUPPORT_PANEL_URL}."
    ),
}

TOPIC_LIMIT_REFUSAL = (
    f"They already sent {MAX_TICKETS_PER_TOPIC} tickets on this topic in the last 72 hours. More tickets don't get a "
    f"faster reply. They can read those tickets, reply on them, and watch for replies in the support panel at {SUPPORT_PANEL_URL}."
)

DRAFT_REFUSALS = {
    DraftRefusal.TOPIC_EXCLUDED: (
        "PostHog support doesn't take tickets on this topic from an agent. The person can log in to PostHog in their "
        "browser and ask in the support widget in the right-hand sidebar, "
        f"at {SUPPORT_PANEL_URL}. If their plan doesn't include support, "
        f"{COMMUNITY_SUPPORT}"
    ),
    DraftRefusal.PLAN_EXCLUDES_SUPPORT: (
        "Their plan doesn't include support tickets for this topic. Any paid plan adds support. Without one, "
        f"{COMMUNITY_SUPPORT}"
    ),
    DraftRefusal.TOPIC_LIMIT: TOPIC_LIMIT_REFUSAL,
}

MAY_BE_SENT = (
    "The ticket may already be with PostHog support, so don't send it again. Ask the person to check "
    f"their tickets at {SUPPORT_PANEL_URL}."
)
# The MCP server passes `detail` to the agent only for a 4xx, so a failed send never uses a 5xx.
SEND_FAILURE_RESPONSES: dict[SendFailure, tuple[str, int]] = {
    SendFailure.NOT_FOUND: ("Draft not found or expired.", status.HTTP_404_NOT_FOUND),
    SendFailure.ALREADY_SENDING: (MAY_BE_SENT, status.HTTP_409_CONFLICT),
    SendFailure.TOO_MANY_ATTEMPTS: (
        "Nothing was sent, and this draft has no send attempts left. The person can ask in the support "
        f"panel at {SUPPORT_PANEL_URL}.",
        status.HTTP_409_CONFLICT,
    ),
    SendFailure.TOPIC_LIMIT: (f"Nothing was sent. {TOPIC_LIMIT_REFUSAL}", status.HTTP_403_FORBIDDEN),
    SendFailure.TOPIC_EXCLUDED: (
        f"Nothing was sent. {DRAFT_REFUSALS[DraftRefusal.TOPIC_EXCLUDED]}",
        status.HTTP_403_FORBIDDEN,
    ),
    SendFailure.PLAN_EXCLUDES_SUPPORT: (
        f"Nothing was sent. {DRAFT_REFUSALS[DraftRefusal.PLAN_EXCLUDES_SUPPORT]}",
        status.HTTP_403_FORBIDDEN,
    ),
    SendFailure.PLAN_UNKNOWN: (
        "Nothing was sent, because PostHog couldn't check their plan. They can ask in the support "
        f"panel at {SUPPORT_PANEL_URL}.",
        status.HTTP_424_FAILED_DEPENDENCY,
    ),
    SendFailure.NOT_SENT: (
        "Nothing was sent, because PostHog support couldn't take the ticket. Try again in a moment, "
        f"or the person can ask in the support panel at {SUPPORT_PANEL_URL}.",
        status.HTTP_424_FAILED_DEPENDENCY,
    ),
    SendFailure.OUTCOME_UNKNOWN: (MAY_BE_SENT, status.HTTP_409_CONFLICT),
}


class PostHogSupportViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "posthog_support"
    scope_object_write_actions = ["create_draft", "send_draft"]
    pagination_class = None

    def _paused(self) -> Response | None:
        if not posthog_feature_flag_enabled(
            KILL_SWITCH_FLAG,
            str(self._user.distinct_id or self._user.uuid),
            organization_id=self.team.organization_id,
            team_id=self.team_id,
            only_evaluate_locally=True,
        ):
            return None
        return Response({"detail": PAUSED_DETAIL}, status=status.HTTP_403_FORBIDDEN)

    def check_throttles(self, request: Request) -> None:
        if self.action == "create_draft":
            throttle = PostHogSupportDraftCreateThrottle()
            if not throttle.allow_request(request, self):
                wait = math.ceil(throttle.wait() or 0)
                hours = max(1, math.ceil(wait / 3600))
                throttled = Throttled(
                    detail=(
                        f"Nothing was drafted. PostHog allows {throttle.num_requests} drafts a day, so they can try "
                        f"again in about {hours} hour{'s' if hours > 1 else ''}."
                    ),
                )
                # Set after init so DRF doesn't append its own wait sentence. Without Retry-After, the MCP
                # client retries the refused draft with backoff before the agent sees why.
                throttled.wait = wait  # type: ignore[attr-defined]
                raise throttled
        super().check_throttles(request)

    @property
    def _user(self) -> User:
        return cast(User, self.request.user)

    def _draft_response(self, draft: SupportDraft, status_code: int = status.HTTP_200_OK) -> Response:
        data = PostHogSupportDraftSerializer(
            {
                "id": draft.id,
                "message": draft.message,
                "ticket_context": draft.ticket_context,
                "expires_at": draft.expires_at,
                "can_send": draft.permission == TicketPermission.ALLOWED,
                "next_step": NEXT_STEP_BY_PERMISSION.get(draft.permission, "Nothing has been sent."),
            }
        ).data
        return Response(data, status=status_code)

    def _sent_response(self, ticket: SentSupportTicketResult) -> Response:
        data = PostHogSupportSentTicketSerializer(
            {
                "ticket_id": ticket.ticket_id,
                "ticket_number": ticket.ticket_number,
                "support_panel_url": SUPPORT_PANEL_URL,
                "next_step": (
                    (
                        f"First give the person their ticket number, {ticket.ticket_number}, and tell them"
                        if ticket.ticket_number is not None
                        else "First tell the person"
                    )
                    + f" to watch for replies at {SUPPORT_PANEL_URL}, the support panel in the right-hand sidebar"
                    " of PostHog. They need to log in, and replies don't show up in this conversation. Don't"
                    " promise a response time."
                ),
            }
        ).data
        return Response(data, status=status.HTTP_200_OK)

    @validated_request(
        request_serializer=PostHogSupportDraftCreateSerializer,
        responses={
            201: OpenApiResponse(response=PostHogSupportDraftSerializer),
            403: OpenApiResponse(response=PostHogSupportErrorSerializer),
            429: OpenApiResponse(response=PostHogSupportErrorSerializer),
        },
        summary="Draft a PostHog support ticket for the person to approve",
        description=(
            "Saves a draft ticket to PostHog support. It does not send it. Refuses a topic that an agent can't file, "
            "and a plan without support for the topic, and says where the person can ask instead. The person approves it in chat, so "
            "the agent sends it with the send endpoint."
        ),
    )
    @action(methods=["POST"], detail=False, url_path="drafts")
    def create_draft(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        if paused := self._paused():
            return paused
        data = request.validated_data
        topic = TicketTopic(data["topic"])
        mcp_session_id = _mcp_id(request.headers.get("X-Posthog-Mcp-Session-Id"))
        mcp_conversation_id = _mcp_id(request.headers.get("X-Posthog-Mcp-Conversation-Id"))
        drafted_via = DraftedVia.MCP if get_event_source(request) in MCP_TRANSPORT_EVENT_SOURCES else DraftedVia.API
        try:
            draft = draft_support_ticket(
                user_id=self._user.pk,
                team_id=self.team_id,
                message=data["message"],
                topic=topic,
                filing_reason=FilingReason(data["filing_reason"]),
                drafted_via=drafted_via,
                mcp_session_id=mcp_session_id,
                mcp_conversation_id=mcp_conversation_id,
            )
        except SupportDraftRefused as refused:
            report_user_action(
                self._user,
                "posthog support draft refused",
                {"topic": topic.value, "filing_reason": data["filing_reason"], "reason": refused.refusal.value},
                team=self.team,
            )
            detail = f"Nothing was drafted. {DRAFT_REFUSALS[refused.refusal]}"
            return Response({"detail": detail}, status=status.HTTP_403_FORBIDDEN)
        report_user_action(
            self._user,
            "posthog support draft created",
            {
                "draft_id": draft.id,
                "topic": draft.topic,
                "filing_reason": draft.filing_reason,
                "agent_name": data.get("agent_name") or None,
                "authenticated_with": type(request.successful_authenticator).__name__,
                "drafted_via": drafted_via.value,
                # The MCP server records each tool call under these same ids, so support can follow a
                # ticket's draft id back to every call the agent made before it drafted the ticket.
                "mcp_session_id": mcp_session_id,
                "mcp_conversation_id": mcp_conversation_id,
            },
            team=self.team,
        )
        return self._draft_response(draft, status.HTTP_201_CREATED)

    @validated_request(
        responses={
            200: OpenApiResponse(response=PostHogSupportSentTicketSerializer),
            403: OpenApiResponse(response=PostHogSupportErrorSerializer),
            404: OpenApiResponse(response=PostHogSupportErrorSerializer),
            409: OpenApiResponse(response=PostHogSupportErrorSerializer),
            424: OpenApiResponse(response=PostHogSupportErrorSerializer),
        },
        summary="Send a drafted ticket to PostHog support after the person approved it",
        description=(
            "Posts the draft to PostHog support for the person, and returns the ticket. Call it only after the "
            "person saw the full ticket and approved sending it. A draft becomes at most one ticket: calling "
            "again returns the same ticket."
        ),
    )
    @action(methods=["POST"], detail=False, url_path=rf"drafts/(?P<draft_id>{DRAFT_ID_PATTERN})/send")
    def send_draft(self, request: ValidatedRequest, draft_id: str, *args: Any, **kwargs: Any) -> Response:
        if paused := self._paused():
            return paused
        try:
            ticket = send_support_ticket(user_id=self._user.pk, team_id=self.team_id, draft_id=draft_id)
        except SupportTicketSendFailed as failed:
            detail, status_code = SEND_FAILURE_RESPONSES[failed.failure]
            if failed.failure != SendFailure.NOT_FOUND:
                report_user_action(
                    self._user,
                    "posthog support draft send failed",
                    {
                        "draft_id": draft_id,
                        "topic": failed.topic,
                        "filing_reason": failed.filing_reason,
                        "reason": failed.failure.value,
                    },
                    team=self.team,
                )
            return Response({"detail": detail}, status=status_code)
        if ticket.newly_sent:
            report_user_action(
                self._user,
                "posthog support draft submitted",
                {
                    "draft_id": draft_id,
                    "topic": ticket.topic,
                    "filing_reason": ticket.filing_reason,
                    "ticket_id": ticket.ticket_id,
                },
                team=self.team,
            )
        return self._sent_response(ticket)
