import time
from typing import Any

from django.conf import settings
from django.urls import reverse

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from prometheus_client import Counter, Histogram
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_team_action, report_user_action
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

from products.messaging.backend.facade.contracts import TransactionalEmailError
from products.messaging.backend.facade.supabase_auth_emails import (
    MAX_HOOK_BODY_BYTES,
    STARTER_EMAIL_TYPES,
    SupabaseAuthEmailSettings,
    SupabaseAuthEmailSettingsInvalid,
    SupabaseEmailActionType,
    SupabaseHookResult,
    create_starter_templates,
    delete_settings,
    get_settings,
    handle_send_email_hook,
    save_settings,
    template_workflow_ids,
)
from products.workflows.backend.facade.api import WorkflowAccessDenied, WorkflowNotFound
from products.workflows.backend.facade.workflows import get_workflow

logger = structlog.get_logger(__name__)

# pinned: feature flag key, a rename makes a new flag
SUPABASE_AUTH_EMAILS_FLAG = "workflows-supabase-auth-emails"

# Every hook call is counted here rather than as an analytics event, because calls scale with the sign-ups and
# log-ins of each customer's own app.
HOOK_CALLS = Counter(
    "messaging_supabase_auth_email_hook_total",
    "Supabase Send Email Hook calls, by the status PostHog answered and why a send failed.",
    labelnames=["status", "email_action_type", "error_code"],
)
# Supabase fails the sign-up when the hook takes over 5 seconds.
HOOK_DURATION = Histogram(
    "messaging_supabase_auth_email_hook_duration_seconds",
    "Time to verify a Supabase Send Email Hook call and send its emails.",
    buckets=(0.25, 0.5, 1, 2, 3, 4, 5, 7.5, 10),
)

# Current Supabase sends email sign-in codes as `magiclink`, so `email` only comes from older self-hosted versions.
# The hook still accepts it and an existing mapping still saves, but the mapping table doesn't offer it.
HIDDEN_EMAIL_TYPES = frozenset({SupabaseEmailActionType.EMAIL})


def supabase_auth_emails_enabled(team: Team) -> bool:
    return feature_enabled_or_false(
        SUPABASE_AUTH_EMAILS_FLAG,
        str(team.uuid),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        send_feature_flag_events=False,
    )


class SupabaseEmailTypeSerializer(serializers.Serializer):
    value = serializers.ChoiceField(
        choices=SupabaseEmailActionType.choices, help_text="The `email_action_type` Supabase sends for this email."
    )
    label = serializers.CharField(help_text="What the email is for, in words a person reads.")  # type: ignore[assignment]
    has_starter_template = serializers.BooleanField(
        help_text="Whether creating starter templates makes a template for this email."
    )


class SupabaseAuthEmailSettingsSerializer(serializers.Serializer):
    supabase_url = serializers.CharField(
        help_text="The Supabase project URL, such as https://abcdefgh.supabase.co. Confirmation links point at its "
        "/auth/v1/verify endpoint."
    )
    has_hook_secret = serializers.BooleanField(
        help_text="Whether a Send Email Hook secret is stored. The secret itself is never returned."
    )
    templates = serializers.DictField(
        child=serializers.UUIDField(),
        help_text="Supabase email action type (such as `signup` or `recovery`) to the transactional message "
        "template that sends it. An auth email with no template fails in Supabase.",
    )
    hook_url = serializers.CharField(
        help_text="The URL to paste into Supabase as the HTTPS endpoint of the Send Email Hook."
    )
    email_types = SupabaseEmailTypeSerializer(
        many=True, help_text="Every email Supabase can send through the hook, core auth emails first."
    )


class SupabaseAuthEmailSettingsUpdateSerializer(serializers.Serializer):
    supabase_url = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text="The Supabase project URL, such as https://abcdefgh.supabase.co, from the project's API settings in "
        "the Supabase dashboard. It must use https.",
    )
    hook_secret = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        max_length=500,
        help_text="The Send Email Hook secret, starting with v1,whsec_. Supabase generates it under Authentication, "
        "Hooks, Send Email hook. Leave it out to keep the stored secret.",
    )
    templates = serializers.DictField(
        child=serializers.UUIDField(),
        required=False,
        help_text="Supabase email action type to the id of the email template that sends it. Each template must be "
        "transactional and marked sensitive. This replaces the whole mapping: include every type to keep, and leave a "
        "type out to unmap it. A core auth email with no template fails in Supabase, and a notification with no "
        "template is skipped. "
        f"Valid action types: {', '.join(SupabaseEmailActionType.values)}.",
    )


class SupabaseAuthEmailsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Send a Supabase project's auth emails through transactional email templates."""

    scope_object = "hog_flow"
    scope_object_read_actions = ["get_settings"]
    scope_object_write_actions = ["update_settings", "disconnect", "starter_templates"]
    serializer_class = _FallbackSerializer

    def _require_flag(self) -> None:
        if not supabase_auth_emails_enabled(self.team):
            raise NotFound()

    def _require_editor(self) -> None:
        # Team-wide settings with no per-workflow object, so a grant on one workflow is not enough.
        if not self.user_access_control.check_access_level_for_resource("hog_flow", "editor"):
            raise PermissionDenied("You need workflow editor access to change the Supabase auth emails.")

    def _require_workflow_editor(self, templates: dict[str, Any]) -> None:
        # Whoever saves these settings can sign hook calls that send every mapped template, so they need the same
        # workflow access as sending each template directly. A save that keeps a mapping still counts.
        for hog_flow_id in template_workflow_ids(self.team_id, set(templates.values())):
            try:
                get_workflow(
                    team_id=self.team_id,
                    workflow_id=str(hog_flow_id),
                    user_access_control=self.user_access_control,
                    required_level="editor",
                )
            except WorkflowAccessDenied:
                raise PermissionDenied(
                    "You need editor access to the transactional email workflow of every mapped template."
                ) from None
            except WorkflowNotFound:
                continue

    def _response(self, current: SupabaseAuthEmailSettings) -> Response:
        hook_path = reverse("messaging_supabase_send_email_hook", kwargs={"team_id": self.team_id})
        data = {
            "supabase_url": current.supabase_url,
            "has_hook_secret": current.has_hook_secret,
            "templates": current.templates,
            "hook_url": f"{settings.SITE_URL}{hook_path}",
            "email_types": [
                {"value": t.value, "label": t.label, "has_starter_template": t in STARTER_EMAIL_TYPES}
                for t in SupabaseEmailActionType
                if t not in HIDDEN_EMAIL_TYPES
            ],
        }
        return Response(SupabaseAuthEmailSettingsSerializer(data).data)

    @extend_schema(
        responses={200: SupabaseAuthEmailSettingsSerializer},
        summary="Get the Supabase auth email settings",
    )
    @action(detail=False, methods=["GET"], url_path="settings")
    def get_settings(self, request: Request, **kwargs: Any) -> Response:
        self._require_flag()
        return self._response(get_settings(self.team_id))

    @validated_request(
        SupabaseAuthEmailSettingsUpdateSerializer,
        responses={
            200: OpenApiResponse(response=SupabaseAuthEmailSettingsSerializer, description="The saved settings"),
            400: OpenApiResponse(description="A field is invalid. The error names the field to fix."),
        },
        summary="Update the Supabase auth email settings",
    )
    @get_settings.mapping.patch
    def update_settings(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        self._require_flag()
        self._require_editor()
        self._require_workflow_editor(request.validated_data.get("templates", get_settings(self.team_id).templates))
        try:
            saved = save_settings(self.team_id, request.user.id, **request.validated_data)
        except SupabaseAuthEmailSettingsInvalid as e:
            raise exceptions.ValidationError({e.field: str(e)}) from None
        try:
            # pinned: analytics event name, renaming breaks dashboards
            report_user_action(
                request.user,
                "supabase auth emails settings saved",
                {
                    "fields": sorted(request.validated_data),
                    "has_hook_secret": saved.has_hook_secret,
                    "mapped_email_types": sorted(saved.templates),
                },
                team=self.team,
                request=request,
            )
        except Exception as e:
            logger.warning("Failed to capture Supabase auth email usage event", error=str(e))
        return self._response(saved)

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(response=SupabaseAuthEmailSettingsSerializer, description="The empty settings")
        },
        summary="Disconnect the Supabase project",
        description="Remove the project URL, hook secret and template mappings. The hook then refuses every call, so "
        "turn off the Send Email hook in Supabase first. The templates themselves stay.",
    )
    @get_settings.mapping.delete
    def disconnect(self, request: Request, **kwargs: Any) -> Response:
        self._require_flag()
        self._require_editor()
        cleared = delete_settings(self.team_id)
        try:
            # pinned: analytics event name, renaming breaks dashboards
            report_user_action(request.user, "supabase auth emails disconnected", {}, team=self.team, request=request)
        except Exception as e:
            logger.warning("Failed to capture Supabase auth email usage event", error=str(e))
        return self._response(cleared)

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(response=SupabaseAuthEmailSettingsSerializer, description="The saved settings"),
            400: OpenApiResponse(description="The team has no verified email sender"),
        },
        summary="Create starter templates for the Supabase auth emails",
        description="Create a transactional template for each core Supabase auth email that has no template yet, "
        "and map it. Needs a verified email sender.",
    )
    @action(detail=False, methods=["POST"])
    def starter_templates(self, request: Request, **kwargs: Any) -> Response:
        self._require_flag()
        self._require_editor()
        mapped_before = len(get_settings(self.team_id).templates)
        try:
            saved = create_starter_templates(self.team_id, request.user.id)
        except TransactionalEmailError as e:
            raise exceptions.ValidationError({"detail": str(e)}) from None
        try:
            # pinned: analytics event name, renaming breaks dashboards
            report_user_action(
                request.user,
                "supabase auth emails starter templates created",
                {"created_count": len(saved.templates) - mapped_before},
                team=self.team,
                request=request,
            )
        except Exception as e:
            logger.warning("Failed to capture Supabase auth email usage event", error=str(e))
        return self._response(saved)


class SupabaseSendEmailHookView(APIView):
    """Supabase's Send Email Hook. Supabase signs each request with the team's hook secret, so no session or API
    key applies here."""

    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    # Hosted Supabase projects share outbound IPs, so the default anonymous IP buckets would let one project's
    # sign-ups refuse another's. The HMAC check is cheap, like the other inbound webhooks, which aren't throttled.
    throttle_classes: list[type] = []

    @staticmethod
    def _answer(result: SupabaseHookResult, *, verified: bool) -> Response:
        if result.status < 300:
            # Supabase's hook contract fixes this body, and the hook is not part of the OpenAPI schema.
            return Response({}, status=200)  # nosemgrep: api-response-must-match-schema
        # Supabase replaces the message of any non-2xx answer with a generic one. It passes on an error body that
        # comes with a 200, and answers the client with its `http_code`. A request that isn't verified as
        # Supabase's gets the real status, so an unsigned caller never gets a 200.
        body = {"error": {"http_code": result.status, "message": result.message}}
        return Response(body, status=200 if verified and result.status != 401 else result.status)

    def post(self, request: Request, team_id: str) -> Response:
        try:
            if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_HOOK_BODY_BYTES:
                return self._answer(
                    SupabaseHookResult(status=413, message="The hook payload is too large."), verified=False
                )
        except ValueError:
            return self._answer(
                SupabaseHookResult(status=400, message="The hook payload isn't a Send Email Hook payload."),
                verified=False,
            )
        team = Team.objects.filter(id=team_id).first()
        # No flag check here: a config only exists if the flag was on when it was saved, and a flag that rolls back
        # or fails to evaluate would fail every connected project's sign-ups.
        if team is None:
            return self._answer(
                SupabaseHookResult(status=401, message="The hook signature doesn't match. Check the hook secret."),
                verified=False,
            )
        started = time.monotonic()
        result = handle_send_email_hook(team, request.body, request.headers)
        duration = time.monotonic() - started
        # The payload sets this, so an unknown value must not become a new metric series.
        action = result.email_action_type if result.email_action_type in SupabaseEmailActionType.values else "other"
        HOOK_DURATION.observe(duration)
        HOOK_CALLS.labels(status=str(result.status), email_action_type=action, error_code=result.error_code).inc()
        # A request that isn't verified as Supabase's could come from anyone, so it records no usage for the team.
        if result.status == 401:
            return self._answer(result, verified=False)
        if result.status < 300:
            return self._answer(result, verified=True)
        try:
            # Only failures, so the event volume doesn't grow with the customer's traffic. Each template tracks its sends.
            # The hook has no user, so the event is tracked against the team. A 401 here usually means a wrong secret.
            # pinned: analytics event name, renaming breaks dashboards
            report_team_action(
                team,
                "supabase auth email hook",
                {
                    "status": result.status,
                    "email_action_type": action,
                    "skipped": result.skipped,
                    "error_code": result.error_code,
                    "sent_count": result.sent_count,
                    "duration_ms": round(duration * 1000),
                },
            )
        except Exception as e:
            logger.warning("Failed to capture Supabase auth email usage event", error=str(e))
        return self._answer(result, verified=True)
