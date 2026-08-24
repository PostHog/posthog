"""Server-minted scout chat tasks.

The Inbox scout surfaces ("Suggest a scout", fleet overview, recent signals) kick off a cloud
Task the user then chats with. The prompt templates and the task dispatch live here, server-side,
because the run endpoints gate arbitrary tasks on PostHog Desktop access: scout chat is entitled
through the generally-available Inbox instead, and the reserved ``SIGNALS_CHAT`` origin this
endpoint stamps is what proves that entitlement to the gate (the tasks write serializer rejects
the origin from API callers). See ``task_exempt_from_code_access`` in the tasks facade.
"""

import time

from django.core.cache import cache

from drf_spectacular.utils import OpenApiResponse
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission

from products.signals.backend.models import SignalScoutConfig
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.access import usage_limit_response

SCOUT_AUTHOR_PROMPT = """I'd like to make a new scout for this PostHog project.

Use the authoring-scouts skill from the PostHog MCP to guide creating a new signals scout.

First, take a quick scan of this PostHog project to ground your suggestions: skim its events, insights, dashboards, recently emitted signals, and the existing scout fleet so you understand what this product is and where automated monitoring would add value.

Then ask me what sort of scout I'd like to make, and offer a few concrete suggestions tailored to what you found (for example specific funnels, error or latency spikes, churn or activation signals, or revenue metrics worth watching) – and call out gaps the current fleet doesn't already cover. Once I pick a direction, walk me through authoring the scout end to end.

If the skill is unavailable, fall back to the signals-scout MCP tools directly (config list to see the existing fleet) plus the read-data and insight tools to scan the project."""

SCOUT_FLEET_OVERVIEW_PROMPT = """How is my scout fleet performing?

Use the exploring-scouts skill from the PostHog MCP to survey the signals scout fleet on this project and give me a high-level overview:

- The fleet: which scouts exist, enabled vs disabled, and their cadences
- Recent run health: success rate, failures and timeouts, anything stuck
- Output: which scouts emitted signals recently, emit rate, signal-to-noise
- Memory: notable scratchpad entries the fleet has learned
- Recommendations: anything misconfigured, noisy, or worth tuning

Lead with a short overall verdict, then per-scout notes only where something is notable. If the skill is unavailable, fall back to the signals-scout MCP tools directly (config list, runs list, scratchpad search)."""

SCOUT_RECENT_SIGNALS_PROMPT = """What signals have my scouts emitted recently?

Use the exploring-scouts skill from the PostHog MCP to pull the most recent scout runs that emitted findings and walk me through the signals:

- What each signal says, in plain language
- Which scout emitted it, when, and its severity/confidence where available
- Whether it looks genuinely actionable or like noise

Group by scout, newest first. Close with a short note on overall signal quality and any scouts that look noisy or suspiciously silent. If the skill is unavailable, fall back to the signals-scout MCP tools directly (runs list with emitted filter, run emissions)."""

SCOUT_CHAT_TEMPLATES: dict[str, tuple[str, str]] = {
    "author_scout": ("Suggest a scout", SCOUT_AUTHOR_PROMPT),
    "fleet_overview": ("How is my scout troop performing?", SCOUT_FLEET_OVERVIEW_PROMPT),
    "recent_signals": ("What signals were emitted recently?", SCOUT_RECENT_SIGNALS_PROMPT),
}
SCOUT_CHAT_DAILY_ATTEMPT_CAP = 15


class ScoutChatBurstRateThrottle(UserRateThrottle):
    scope = "signals_scout_chat_burst"
    rate = "2/hour"


class ScoutChatSustainedRateThrottle(UserRateThrottle):
    scope = "signals_scout_chat_day"
    rate = "5/day"


class ScoutChatTaskCreateSerializer(serializers.Serializer):
    chat_type = serializers.ChoiceField(
        choices=sorted(SCOUT_CHAT_TEMPLATES),
        help_text=(
            "Which scout chat to start: `author_scout` (guided scout authoring), `fleet_overview` "
            "(health of the scout fleet), or `recent_signals` (walk through recently emitted "
            "signals). The prompt template is owned server-side."
        ),
    )


class ScoutChatTaskSerializer(serializers.Serializer):
    task_id = serializers.UUIDField(help_text="The created chat task. Open it on the task detail page to continue.")


class SignalScoutChatTaskViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Kick off a scout chat task from one of the fixed Inbox templates.

    Creates a repo-less interactive cloud task with the reserved ``SIGNALS_CHAT`` origin and
    starts its run, mirroring what the Inbox previously did client-side through the generic
    task endpoints.
    """

    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    serializer_class = ScoutChatTaskSerializer
    pagination_class = None
    throttle_classes = [ScoutChatBurstRateThrottle, ScoutChatSustainedRateThrottle]
    # No model backs this endpoint; a queryset is still required by the team/org viewset mixin
    # and `create` never reads it.
    queryset = SignalScoutConfig.objects.unscoped()

    @validated_request(
        request_serializer=ScoutChatTaskCreateSerializer,
        responses={
            201: OpenApiResponse(response=ScoutChatTaskSerializer, description="Chat task created and run started"),
            403: OpenApiResponse(description="Organization has not approved AI data processing"),
            429: OpenApiResponse(description="Team is over its posthog_code usage limit"),
        },
        summary="Start a scout chat task",
        description=(
            "Create and run a cloud task for one of the fixed scout chat templates (suggest a "
            "scout, fleet overview, recent signals). The prompt is server-owned; the response "
            "carries the task id to navigate to."
        ),
    )
    def create(self, request, **kwargs):
        if self.team.organization.is_ai_data_processing_approved is not True:
            return Response(
                {"error": "Enable AI data processing for this organization to start a scout chat."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if limit_response := usage_limit_response(request.user, self.team_id):
            return limit_response

        window = int(time.time()) // 86400
        key = f"signals_scout_chat_attempts:{request.user.id}:{window}"
        cache.add(key, 0, timeout=86400)
        try:
            attempts = cache.incr(key)
        except ValueError:
            attempts = 1
        if attempts > SCOUT_CHAT_DAILY_ATTEMPT_CAP:
            raise exceptions.Throttled(detail="You've reached today's limit for scout chats. Try again tomorrow.")

        title, prompt = SCOUT_CHAT_TEMPLATES[request.validated_data["chat_type"]]
        # Repo-less on purpose: these chats read PostHog data over MCP and never touch code.
        # create_pr=False marks the session non-PR-opening, and the pending user message is
        # self-delivered by the agent server on boot so the interactive run has a first turn.
        created = tasks_facade.create_and_run_task(
            team=self.team,
            title=title,
            description=prompt,
            origin_product=tasks_facade.TaskOriginProduct.SIGNALS_CHAT,
            user_id=request.user.id,
            repository=None,
            create_pr=False,
            mode="interactive",
            pending_user_message=prompt,
        )
        return Response(ScoutChatTaskSerializer({"task_id": created.task_id}).data, status=status.HTTP_201_CREATED)
