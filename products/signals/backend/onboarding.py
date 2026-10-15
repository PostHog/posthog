from __future__ import annotations

from typing import Any, cast

from django.db import models, transaction
from django.utils import timezone

import posthoganalytics
from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.event_usage import groups
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.user import User
from posthog.permissions import APIScopePermission, get_authenticator_scopes

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.facade.api import signal_emitting_scanner_ids
from products.signals.backend.models import (
    AutonomyPriority,
    SignalScoutConfig,
    SignalSourceConfig,
    SignalTeamConfig,
    signal_source_product_choices,
)
from products.signals.backend.onboarding_completion import InboxOnboardingReconciler
from products.signals.backend.scout_harness.create_access import can_create_scout
from products.signals.backend.scout_harness.views import ScoutCanonicalTeamAccessPermission
from products.signals.backend.scout_suggestions_api import ScoutSuggestionItemSerializer


class InboxOnboardingStep(models.TextChoices):
    SIGNALS = "signals", "Signals"
    SCOUTS = "scouts", "Scouts"
    GITHUB = "github", "GitHub"


class InboxOnboardingVariant(models.TextChoices):
    CONTROL = "control", "Control"
    TEST = "test", "Focused steps"


class InboxOnboardingExposureSerializer(serializers.Serializer):
    variant = serializers.ChoiceField(
        choices=InboxOnboardingVariant.choices,
        help_text="Assigned experiment variant at the eligible Inbox impression.",
    )


class InboxOnboardingSourceSerializer(serializers.Serializer):
    source_product = serializers.ChoiceField(
        choices=signal_source_product_choices(), help_text="Source product selected during setup."
    )
    source_type = serializers.ChoiceField(
        choices=SignalSourceConfig.SourceType.choices, help_text="Signal type selected during setup."
    )
    enabled = serializers.BooleanField(help_text="Whether this source should be enabled at activation.")


class InboxOnboardingDraftSerializer(serializers.Serializer):
    step = serializers.ChoiceField(choices=InboxOnboardingStep.choices, help_text="Step to resume after returning.")
    sources: serializers.ListSerializer[dict[str, object]] = serializers.ListSerializer(
        child=InboxOnboardingSourceSerializer(), max_length=50, help_text="Staged signal source choices."
    )
    scanner_ids = serializers.ListField(
        child=serializers.UUIDField(), max_length=100, help_text="Existing enabled scanners selected to emit signals."
    )
    suggestions: serializers.ListSerializer[dict[str, object]] = serializers.ListSerializer(
        child=ScoutSuggestionItemSerializer(), max_length=5, help_text="Selected scout suggestion drafts."
    )
    activation_scouts = serializers.ListField(
        child=serializers.CharField(max_length=200),
        max_length=50,
        required=False,
        help_text="Scouts enabled by an unfinished activation, retained to undo later deselections.",
    )
    automatic_implementation = serializers.BooleanField(help_text="Opt in to automatically creating pull requests.")
    implementation_priority = serializers.ChoiceField(
        choices=AutonomyPriority.choices,
        help_text="Lowest priority to implement automatically; P1 includes P0 and P1.",
    )

    def validate_suggestions(self, suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if any(len(item["draft_body"]) > 100_000 for item in suggestions):
            raise serializers.ValidationError("A scout draft is too long.")
        return suggestions


@extend_schema_serializer(many=False)
class InboxOnboardingStateSerializer(serializers.Serializer):
    draft = InboxOnboardingDraftSerializer(allow_null=True, help_text="Saved setup choices, without activating them.")
    completed_at = serializers.DateTimeField(allow_null=True, help_text="When verified setup completed.")
    variant = serializers.ChoiceField(
        choices=InboxOnboardingVariant.choices,
        allow_null=True,
        help_text="Variant recorded at the first eligible impression.",
    )


class InboxOnboardingViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    requires_resource_level_access = True
    queryset = SignalTeamConfig.objects.all()
    serializer_class = InboxOnboardingStateSerializer
    pagination_class = None

    def dangerously_get_required_scopes(self, request: Request, view: object) -> list[str]:
        return ["task:read"] if request.method in ("GET", "HEAD", "OPTIONS") else ["task:write"]

    def _check_scout_access(self, request: Request) -> None:
        permission = ScoutCanonicalTeamAccessPermission()
        if not permission.has_permission(request, self):
            raise PermissionDenied(permission.message)

    def _check_suggestion_access(self, request: Request, *, write: bool = False) -> None:
        self._check_scout_access(request)
        scopes = get_authenticator_scopes(request.successful_authenticator)
        required = {"signal_scout:write", "llm_skill:write"} if write else {"signal_scout:read"}
        if scopes is not None and "*" not in scopes:
            allowed = set(scopes)
            if "signal_scout:write" in allowed:
                allowed.add("signal_scout:read")
            if not required.issubset(allowed):
                raise PermissionDenied("Your API key does not have permission to access these scout choices.")
        canonical_team = self.team.parent_team or self.team
        user = cast(User, request.user)
        access = UserAccessControl(user=user, team=canonical_team)
        if not access.check_access_level_for_resource("signal_scout", "editor" if write else "viewer"):
            raise PermissionDenied("You do not have access to these scout choices.")
        if write and not can_create_scout(user, canonical_team):
            raise PermissionDenied("Saving scout choices requires editor access to skills.")

    def _state(self, config: SignalTeamConfig) -> dict[str, Any]:
        state = config.onboarding or {}
        if any((state.get("draft") or {}).get(key) for key in ("suggestions", "activation_scouts")):
            self._check_suggestion_access(self.request)
        return {"draft": state.get("draft"), "completed_at": state.get("completed_at"), "variant": state.get("variant")}

    @extend_schema(request=InboxOnboardingExposureSerializer, responses=InboxOnboardingStateSerializer)
    @action(detail=False, methods=["POST"])
    def expose(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = InboxOnboardingExposureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["variant"] == InboxOnboardingVariant.CONTROL:
            self._check_scout_access(request)
        config = get_or_create_team_extension(self.team, SignalTeamConfig)
        with transaction.atomic():
            config = SignalTeamConfig.objects.select_for_update().get(pk=config.pk, team_id=self.team_id)
            state = config.onboarding or {}
            if not state.get("exposed_at"):
                variant = serializer.validated_data["variant"]
                config.onboarding = {
                    **state,
                    "variant": variant,
                    "exposed_at": timezone.now().isoformat(),
                    "exposed_by": request.user.pk,
                }
                config.save(update_fields=["onboarding", "updated_at"])
                transaction.on_commit(lambda: self._report_exposure(cast(User, request.user), variant), robust=True)
        return Response(self._state(config))

    @extend_schema(request=None, responses=InboxOnboardingStateSerializer)
    @action(detail=False, methods=["POST"])
    def reconcile(self, request: Request, *args: object, **kwargs: object) -> Response:
        self._check_scout_access(request)
        InboxOnboardingReconciler(self.team_id).run()
        config = get_or_create_team_extension(self.team, SignalTeamConfig)
        return Response(self._state(config))

    @extend_schema(responses=InboxOnboardingStateSerializer)
    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        config = get_or_create_team_extension(self.team, SignalTeamConfig)
        return Response(self._state(config))

    @extend_schema(request=InboxOnboardingDraftSerializer, responses=InboxOnboardingStateSerializer)
    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = InboxOnboardingDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        config = get_or_create_team_extension(self.team, SignalTeamConfig)
        with transaction.atomic():
            config = SignalTeamConfig.objects.select_for_update().get(team_id=self.team_id, pk=config.pk)
            state = config.onboarding or {}
            if any(
                serializer.validated_data.get(key) or (state.get("draft") or {}).get(key)
                for key in ("suggestions", "activation_scouts")
            ):
                self._check_suggestion_access(request, write=True)
            if not state.get("completed_at"):
                config.onboarding = {**state, "draft": serializer.data}
                config.save(update_fields=["onboarding", "updated_at"])
        return Response(self._state(config))

    @extend_schema(request=InboxOnboardingDraftSerializer, responses=InboxOnboardingStateSerializer)
    @action(detail=False, methods=["POST"])
    def complete(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = InboxOnboardingDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        draft = serializer.validated_data
        config = get_or_create_team_extension(self.team, SignalTeamConfig)
        if (config.onboarding or {}).get("completed_at"):
            return Response(self._state(config))

        if any(
            draft.get(key) or ((config.onboarding or {}).get("draft") or {}).get(key)
            for key in ("suggestions", "activation_scouts")
        ):
            self._check_suggestion_access(request, write=True)
        if draft["suggestions"]:
            if not InboxOnboardingReconciler.scouts_can_emit(self.team.parent_team_id or self.team_id):
                raise serializers.ValidationError(
                    "Scout findings are disabled. Enable the scout source before activating."
                )

        if not InboxOnboardingReconciler(self.team_id).has_repository():
            raise serializers.ValidationError("Connect GitHub with access to at least one repository.")

        selected_source = False
        for source in draft["sources"]:
            persisted = SignalSourceConfig.objects.filter(
                team_id=self.team_id,
                source_product=source["source_product"],
                source_type=source["source_type"],
            ).first()
            if (persisted is None and source["enabled"]) or (
                persisted is not None and persisted.enabled != source["enabled"]
            ):
                raise serializers.ValidationError("Some signal source choices have not been saved. Retry activation.")
            selected_source = selected_source or source["enabled"]
        scanner_ids = [str(scanner_id) for scanner_id in draft["scanner_ids"]]
        if set(scanner_ids) != signal_emitting_scanner_ids(self.team_id, scanner_ids):
            raise serializers.ValidationError("Replay vision has not been enabled. Retry activation.")
        for suggestion in draft["suggestions"]:
            if (
                not SignalScoutConfig.objects.for_team(self.team.parent_team_id or self.team_id)
                .filter(skill_name=suggestion["skill_name"], enabled=True, emit=True)
                .exists()
            ):
                raise serializers.ValidationError("Some selected scouts have not been enabled. Retry activation.")
        if not (selected_source or draft["scanner_ids"] or draft["suggestions"]):
            raise serializers.ValidationError("Select at least one usable signal source or scout.")

        user = cast(User, request.user)
        with transaction.atomic():
            config = SignalTeamConfig.objects.select_for_update().get(team_id=self.team_id, pk=config.pk)
            state = config.onboarding or {}
            if not state.get("completed_at"):
                config.autostart_enabled = draft["automatic_implementation"]
                config.default_autostart_priority = draft["implementation_priority"]
                config.onboarding = {
                    **state,
                    "draft": serializer.data,
                    "completed_at": timezone.now().isoformat(),
                    "activated_by": user.pk,
                }
                config.save(
                    update_fields=["onboarding", "autostart_enabled", "default_autostart_priority", "updated_at"]
                )
                transaction.on_commit(lambda: self._report_completion(user, state.get("variant")), robust=True)
        return Response(self._state(config))

    def _capture(self, user: User, event: str, variant: str | None) -> None:
        posthoganalytics.capture(
            distinct_id=str(user.distinct_id),
            event=event,
            groups=groups(team=self.team),
            properties={"project_id": self.team_id, "variant": variant, "flow_version": "ui-first-v1"},
        )

    def _report_completion(self, user: User, variant: str | None) -> None:
        self._capture(user, "self-driving onboarding completed", variant)

    def _report_exposure(self, user: User, variant: str) -> None:
        self._capture(user, "self-driving onboarding exposed", variant)
        if variant == InboxOnboardingVariant.CONTROL:
            from products.signals.backend.tasks import (
                reconcile_inbox_onboarding,  # noqa: PLC0415 - avoid task imports during API initialization
            )

            reconcile_inbox_onboarding.delay(self.team_id)
