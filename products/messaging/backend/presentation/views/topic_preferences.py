from typing import Any

import structlog
from drf_spectacular.utils import OpenApiResponse
from rest_framework import exceptions, serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import ProjectSecretAPIKeyAuthentication
from posthog.event_usage import report_user_action
from posthog.permissions import is_authenticated_via_project_secret_api_key, legacy_scope_object_used
from posthog.rate_limit import PersonalOrProjectSecretApiKeyRateThrottle, ProjectSecretApiKeyTeamRateThrottle

from products.messaging.backend.facade.preferences import TopicsNotFound, set_preferences
from products.messaging.backend.presentation.views.message_templates import require_transactional_email_api

logger = structlog.get_logger(__name__)


class SetPreferencesSerializer(serializers.Serializer):
    # Workflows looks the recipient up by the untrimmed address, so a trimmed one would save consent elsewhere.
    identifier = serializers.CharField(
        max_length=512,
        trim_whitespace=False,
        help_text="The recipient's email address, exactly as Workflows sends to it. Matching is exact, so "
        "`Jane@example.com` and `jane@example.com` are two recipients.",
    )
    all_marketing = serializers.BooleanField(
        required=False,
        help_text="`false` opts the recipient out of every marketing topic. `true` lifts that opt-out. "
        "Applied before `topics`.",
    )
    topics = serializers.DictField(
        child=serializers.BooleanField(),
        required=False,
        help_text="Topic key to `false` to opt the recipient out of that topic, or `true` to opt them back in. "
        "Opting back in to one marketing topic after an all-marketing opt-out lifts that opt-out, so `all_marketing` "
        "becomes `true`, and keeps the other marketing topics opted out. "
        "Topics you leave out keep their current choice.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "all_marketing" not in attrs and not attrs.get("topics"):
            raise serializers.ValidationError("Set all_marketing, topics, or both.")
        return attrs


class TopicPreferencesSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text="The recipient the preferences belong to.")
    all_marketing = serializers.BooleanField(
        allow_null=True,
        help_text="`false` when the recipient opted out of all marketing, `true` when they opted back in, "
        "`null` when they never chose.",
    )
    topics = serializers.DictField(
        child=serializers.BooleanField(),
        help_text="Topic key to `false` (opted out) or `true` (opted in), for every topic the recipient chose. "
        "A topic without a choice is not listed.",
    )


class TopicPreferencesBurstThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "messaging_preferences_burst"
    rate = "600/minute"


class TopicPreferencesSustainedThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    scope = "messaging_preferences_sustained"
    rate = "20000/hour"


class TopicPreferencesTeamBurstThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "messaging_preferences_psak_team_burst"
    rate = "600/minute"


class TopicPreferencesTeamSustainedThrottle(ProjectSecretApiKeyTeamRateThrottle):
    scope = "messaging_preferences_psak_team_sustained"
    rate = "20000/hour"


class TopicPreferencesViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    # LEGACY_SCOPE_FALLBACKS lets `hog_flow:write` satisfy this scope too, with no end date.
    scope_object = "messaging_preference"
    permission_classes = [IsAuthenticated]
    authentication_classes = [ProjectSecretAPIKeyAuthentication]
    psak_allowed_actions = ["create"]

    def get_throttles(self) -> list[BaseThrottle]:
        if not is_authenticated_via_project_secret_api_key(self.request):
            return super().get_throttles()
        return [
            TopicPreferencesBurstThrottle(),
            TopicPreferencesSustainedThrottle(),
            TopicPreferencesTeamBurstThrottle(),
            TopicPreferencesTeamSustainedThrottle(),
        ]

    @validated_request(
        SetPreferencesSerializer,
        responses={
            200: OpenApiResponse(response=TopicPreferencesSerializer),
            401: OpenApiResponse(description="The request has no project secret API key."),
            404: OpenApiResponse(
                description="A topic key names no topic of this project, with the code `unknown_topic`. Nothing "
                "changed."
            ),
        },
        summary="Set a recipient's topic preferences",
        description=(
            "Opt one recipient out of topics, or back in, in one call. `all_marketing` applies first, then each "
            "topic in order, and the whole change is saved at once. The same change twice ends the same, but a retry "
            "that lands after a newer change undoes that change. Workflows sends skip a marketing topic the "
            "recipient opted out of. Needs a project secret API key with the `messaging_preference:write` scope, "
            "which cannot send email. A key with `hog_flow:write` also works, but that scope can send transactional "
            "email too."
        ),
    )
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        # The routing mixin adds session and personal API key authentication to every route. Preferences change
        # from the customer's server, so only its project secret API key can change them here.
        if not is_authenticated_via_project_secret_api_key(request):
            raise exceptions.NotAuthenticated()
        require_transactional_email_api(self.team)
        data = request.validated_data
        topics: dict[str, bool] = data.get("topics") or {}
        try:
            result = set_preferences(self.team_id, data["identifier"], data.get("all_marketing"), topics)
        except TopicsNotFound as e:
            self._report(request, data, outcome="unknown_topic")
            raise exceptions.NotFound(
                f"This project has no topic with the key {', '.join(e.keys)}.", code="unknown_topic"
            ) from None
        self._report(request, data, outcome="applied")
        return Response(TopicPreferencesSerializer(result).data)

    def _report(self, request: ValidatedRequest, data: dict[str, Any], *, outcome: str) -> None:
        try:
            report_user_action(
                request.user,
                "messaging preferences api set",
                {
                    "team_id": self.team_id,
                    "outcome": outcome,
                    "topic_count": len(data.get("topics") or {}),
                    "sets_all_marketing": "all_marketing" in data,
                    "authorized_by": self._authorized_by(request),
                },
                team=self.team,
                organization=self.organization,
            )
        except Exception as e:
            logger.warning("Failed to capture messaging preferences api event", error=str(e))

    def _authorized_by(self, request: ValidatedRequest) -> str:
        return legacy_scope_object_used(request, f"{self.scope_object}:write") or self.scope_object
