from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404

from drf_spectacular.utils import extend_schema_field
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request

from posthog.schema import RecordingsQuery

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action

from products.replay_vision.backend.models.replay_scanner import (
    ReplayScanner,
    SamplingMode,
    ScannerModel,
    ScannerProvider,
    ScannerType,
)
from products.replay_vision.backend.models.replay_scanner_template import ReplayScannerTemplate


@extend_schema_field(
    {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string"},
            "allow_inconclusive": {"type": "boolean"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "multi_label": {"type": "boolean"},
            "allow_freeform_tags": {"type": "boolean"},
            "scale": {
                "type": "object",
                "required": ["min", "max"],
                "properties": {
                    "min": {"type": "number"},
                    "max": {"type": "number"},
                    "label": {"type": "string"},
                },
            },
            "length": {"type": "string", "enum": ["short", "medium", "long"]},
        },
        "additionalProperties": False,
    }
)
class ScannerTemplateConfigField(serializers.JSONField):
    pass


class ReplayScannerTemplateSerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True, help_text="Name shown in the scanner template picker.")
    description = serializers.CharField(
        read_only=True,
        help_text="Description shown in the scanner template picker.",
    )
    scanner_type = serializers.ChoiceField(
        read_only=True,
        choices=ScannerType.choices,
        help_text="Scanner type restored when this template is selected.",
    )
    scanner_config = ScannerTemplateConfigField(
        read_only=True,
        help_text="Type-specific scanner prompt and output configuration restored by this template.",
    )
    query = extend_schema_field(RecordingsQuery)(  # type: ignore[arg-type, type-var]
        serializers.JSONField(
            read_only=True,
            help_text="Recording filters restored when this template is selected.",
        )
    )
    sampling_rate = serializers.FloatField(
        read_only=True,
        help_text="Recording sampling rate restored when this template is selected.",
    )
    sampling_mode = serializers.ChoiceField(
        read_only=True,
        choices=SamplingMode.choices,
        help_text="Session coverage mode restored when this template is selected.",
    )
    provider = serializers.ChoiceField(
        read_only=True,
        choices=ScannerProvider.choices,
        help_text="AI provider restored when this template is selected.",
    )
    model = serializers.ChoiceField(
        read_only=True,
        choices=ScannerModel.choices,
        help_text="AI model restored when this template is selected.",
    )
    emits_signals = serializers.BooleanField(
        read_only=True,
        help_text="Whether scanners created from this template emit PostHog Signals.",
    )
    source_scanner = serializers.UUIDField(
        source="source_scanner_id",
        read_only=True,
        allow_null=True,
        help_text="Scanner this template was last saved from, or null if that scanner was deleted.",
    )
    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who first saved this template.",
    )

    class Meta:
        model = ReplayScannerTemplate
        fields = [
            "id",
            "name",
            "description",
            "scanner_type",
            "scanner_config",
            "query",
            "sampling_rate",
            "sampling_mode",
            "provider",
            "model",
            "emits_signals",
            "source_scanner",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ReplayScannerTemplateViewSet(
    TeamAndOrgViewSetMixin,
    mixins.DestroyModelMixin,
    viewsets.ReadOnlyModelViewSet,
):
    scope_object = "replay_scanner"
    serializer_class = ReplayScannerTemplateSerializer
    # `objects` is fail-closed and has no team context at import time; `safely_get_queryset`
    # re-scopes through the manager once the request's team scope is set.
    queryset = ReplayScannerTemplate.objects.unscoped()
    http_method_names = ["get", "delete", "head", "options"]

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str]:
        if self.action == "destroy":
            return ["replay_scanner:write", "session_recording:read"]
        return ["replay_scanner:read", "session_recording:read"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Reading scanner templates requires session recording access.")
        if self.action == "destroy" and not self.user_access_control.check_access_level_for_resource(
            "replay_scanner", required_level="editor"
        ):
            raise PermissionDenied("Deleting scanner templates requires scanner edit access.")

    def safely_get_queryset(self, queryset: QuerySet[ReplayScannerTemplate]) -> QuerySet[ReplayScannerTemplate]:
        # A template exposes its source scanner's prompt and recording filters, so gate it by that
        # scanner's object-level access. Orphaned templates (source scanner deleted) have no scanner
        # left to check against, so only their creator keeps seeing them: the scanner may have been
        # access-restricted, and deletion must not widen who can read its prompt.
        accessible_scanner_ids = self.user_access_control.filter_queryset_by_access_level(
            ReplayScanner.objects.filter(team_id=self.team_id)
        ).values_list("id", flat=True)
        # The scoped manager resolves the request's canonical team, so environment URLs
        # can't diverge from where the rows are stored (unlike a manual team_id filter).
        return (
            ReplayScannerTemplate.objects.all()
            .filter(
                Q(source_scanner_id__in=accessible_scanner_ids)
                | Q(source_scanner_id__isnull=True, created_by=self.request.user)
            )
            .select_related("created_by")
            .order_by("name", "id")
        )

    def dangerously_get_object(self) -> ReplayScannerTemplate:
        try:
            template_id = UUID(self.kwargs["pk"])
        except ValueError:
            raise NotFound()
        return get_object_or_404(self.get_queryset(), id=template_id)

    def perform_destroy(self, instance: ReplayScannerTemplate) -> None:
        # Deleting a template destroys it for the whole team, so a scanner-linked template
        # additionally requires edit access on that scanner, not just the resource-wide level.
        if instance.source_scanner is not None and not self.user_access_control.check_access_level_for_object(
            instance.source_scanner, "editor"
        ):
            raise PermissionDenied("Deleting this template requires edit access to its source scanner.")
        template_id = str(instance.id)
        super().perform_destroy(instance)
        report_user_action(
            self.request.user,
            "replay_vision_scanner_template_deleted",
            {"template_id": template_id},
            team=self.team,
            request=self.request,
        )
