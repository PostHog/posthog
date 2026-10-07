from typing import Any, Optional, cast

from django.db import models

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.cdp.validation import HogFunctionFiltersSerializer
from posthog.event_usage import report_user_action
from posthog.helpers.impersonation import is_impersonated
from posthog.models import User
from posthog.models.activity_logging.activity_log import Detail, log_activity

from products.workflows.backend.facade.contracts import WorkflowTemplate
from products.workflows.backend.facade.enums import HogFlowTemplateExitCondition, HogFlowTemplateScope
from products.workflows.backend.facade.templates import (
    WorkflowTemplateNotFound,
    create_template,
    delete_template,
    function_template_exists,
    get_global_template,
    get_template,
    list_global_templates,
    list_templates,
    update_template,
)
from products.workflows.backend.presentation.views.hog_flow_fields import (
    HogFlowMaskingSerializer,
    HogFlowVariableSerializer,
)

logger = structlog.get_logger(__name__)


# NOTE: We allow unauthenticated access to global hog flow templates, never put anything secret in them
class PreventGlobalTemplateDatabaseOperations(BasePermission):
    message = "Global workflow templates are stored in code and cannot be modified via the database."

    def has_permission(self, request: Request, view) -> bool:
        if request.method in SAFE_METHODS:
            return True

        # Block creation of global templates in the database
        if request.method == "POST":
            scope = request.data.get("scope")
            if scope == HogFlowTemplateScope.GLOBAL:
                return False

        return True

    def has_object_permission(self, request: Request, view, obj: WorkflowTemplate) -> bool:
        if request.method in SAFE_METHODS:
            return True

        # Block all modifications to global templates (stored in DB or files)
        # This includes updating team templates to global scope
        if obj.scope == HogFlowTemplateScope.GLOBAL or request.data.get("scope") == HogFlowTemplateScope.GLOBAL:
            return False

        return True


class HogFlowTemplateActionSerializer(serializers.Serializer):
    """
    Custom action serializer for templates that skips input validation
    (since templates should have default/empty values).
    """

    id = serializers.CharField()
    name = serializers.CharField(max_length=400)
    description = serializers.CharField(allow_blank=True, default="")
    on_error = serializers.ChoiceField(
        choices=["continue", "abort"],
        required=False,
        allow_null=True,
        help_text="On failure: continue (skip the action and proceed) or abort (stop the run).",
    )
    created_at = serializers.IntegerField(required=False)
    updated_at = serializers.IntegerField(required=False)
    filters = HogFunctionFiltersSerializer(required=False, default=None, allow_null=True)
    type = serializers.CharField(max_length=100)
    config = serializers.JSONField()
    output_variable = serializers.JSONField(required=False, allow_null=True)

    def to_internal_value(self, data):
        self.initial_data = data
        return super().to_internal_value(data)

    def validate(self, data):
        trigger_is_function = False
        if data.get("type") == "trigger":
            if data.get("config", {}).get("type") in ["webhook", "manual", "tracking_pixel", "schedule"]:
                trigger_is_function = True
            elif data.get("config", {}).get("type") == "event":
                filters = data.get("config", {}).get("filters", {})
                if filters:
                    serializer = HogFunctionFiltersSerializer(data=filters, context=self.context)
                    serializer.is_valid(raise_exception=True)
                    data["config"]["filters"] = serializer.validated_data
            else:
                raise serializers.ValidationError({"config": "Invalid trigger type"})

        # For templates, we skip the input validation since we allow default/empty values and reset inputs anyway
        # Instead, we just verify the template exists
        if "function" in data.get("type", "") or trigger_is_function:
            template_id = data.get("config", {}).get("template_id", "")
            if not function_template_exists(template_id):
                raise serializers.ValidationError({"template_id": "Template not found"})

        conditions = data.get("config", {}).get("conditions", [])
        single_condition = data.get("config", {}).get("condition", None)
        if conditions and single_condition:
            raise serializers.ValidationError({"config": "Cannot specify both 'conditions' and 'condition' fields"})
        if single_condition:
            conditions = [single_condition]

        if conditions:
            for condition in conditions:
                filters = condition.get("filters")
                if filters is not None:
                    if "events" in filters:
                        raise serializers.ValidationError("Event filters are not allowed in conditionals")

                    serializer = HogFunctionFiltersSerializer(data=filters, context=self.context)
                    serializer.is_valid(raise_exception=True)
                    condition["filters"] = serializer.validated_data

        return data


class HogFlowTemplateStartsOnSerializer(serializers.Serializer):
    class Kind(models.TextChoices):
        EVENT = "event", "Event"
        NO_EVENT = "no_event", "No event"
        SCHEDULE = "schedule", "Schedule"

    kind = serializers.ChoiceField(
        choices=Kind.choices,
        help_text="Whether the template starts on an event, an absence of events, or a schedule.",
    )
    events = serializers.ListField(
        child=serializers.CharField(),
        help_text="Event names that can drive the template, in order of preference. Empty for schedules.",
    )
    detail = serializers.CharField(allow_blank=True, help_text="Short qualifier shown with the template's trigger.")


class HogFlowTemplateSerializer(serializers.Serializer):
    """
    Serializer for creating hog flow templates.
    Validates and sanitizes the workflow before creating it as a template.
    """

    id = serializers.UUIDField(read_only=True, help_text="ID of the template.")
    name = serializers.CharField(max_length=400, help_text="Template name.")
    description = serializers.CharField(
        allow_blank=True, required=False, style={"base_template": "textarea.html"}, help_text="Template description."
    )
    image_url = serializers.CharField(
        max_length=8201,
        allow_blank=True,
        allow_null=True,
        required=False,
        help_text="URL of the image shown on the template card.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(), required=False, default=list, help_text="Tags for filtering templates."
    )
    starts_on = HogFlowTemplateStartsOnSerializer(
        read_only=True,
        allow_null=True,
        default=None,
        help_text="What starts a global email template. Null for other templates.",
    )
    scope = serializers.ChoiceField(
        choices=HogFlowTemplateScope.choices,
        help_text="Who can use the template: this project only, or every project in the organization.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the template was created.")
    created_by = serializers.SerializerMethodField()
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the template was last updated.")
    trigger = serializers.JSONField(
        required=False, help_text="Trigger config. Set from the config of the trigger action on save."
    )
    trigger_masking = HogFlowMaskingSerializer(required=False, allow_null=True)
    conversion = serializers.JSONField(required=False, allow_null=True, help_text="Conversion goal config.")
    exit_condition = serializers.ChoiceField(
        choices=HogFlowTemplateExitCondition.choices,
        required=False,
        help_text="When a person exits a workflow created from the template.",
    )
    edges = serializers.JSONField(required=False, help_text="Connections between the actions.")
    actions = serializers.ListField(child=HogFlowTemplateActionSerializer(), required=True)
    abort_action = serializers.CharField(
        max_length=400, allow_blank=True, allow_null=True, required=False, help_text="ID of the abort action."
    )
    variables = HogFlowVariableSerializer(required=False)

    @extend_schema_field({"type": "object", "nullable": True})
    def get_created_by(self, obj):
        if obj.created_by:
            from posthog.api.shared import UserBasicSerializer  # noqa: PLC0415

            return UserBasicSerializer(obj.created_by).data
        return None

    def validate(self, data):
        instance = cast(Optional[WorkflowTemplate], self.instance)

        name = data.get("name")
        if name is None:
            if not instance or not instance.name:
                raise serializers.ValidationError({"name": "Name is required"})
        elif not name.strip():
            raise serializers.ValidationError({"name": "Name cannot be empty"})

        actions = data.get("actions", instance.actions if instance else [])

        # Validate actions using our custom serializer (which skips input validation)
        for action_data in actions:
            serializer = HogFlowTemplateActionSerializer(data=action_data, context=self.context)
            serializer.is_valid(raise_exception=True)

        trigger_actions = [action for action in actions if action.get("type") == "trigger"]
        if len(trigger_actions) != 1:
            raise serializers.ValidationError({"actions": "Exactly one trigger action is required"})
        data["trigger"] = trigger_actions[0]["config"]

        data.pop("id", None)
        data.pop("team_id", None)
        data.pop("created_at", None)
        data.pop("updated_at", None)
        data.pop("created_by", None)
        data.pop("status", None)
        data.pop("version", None)

        return data


# Without a queryset drf-spectacular cannot read the id type from the model, so the detail routes declare it.
_TEMPLATE_ID_PARAMETER = OpenApiParameter(
    "id", OpenApiTypes.UUID, OpenApiParameter.PATH, description="A UUID string identifying this hog flow template."
)


@extend_schema(extensions={"x-product": "workflows"})
@extend_schema_view(
    retrieve=extend_schema(parameters=[_TEMPLATE_ID_PARAMETER]),
    update=extend_schema(parameters=[_TEMPLATE_ID_PARAMETER]),
    partial_update=extend_schema(parameters=[_TEMPLATE_ID_PARAMETER]),
    destroy=extend_schema(parameters=[_TEMPLATE_ID_PARAMETER]),
    logs=extend_schema(parameters=[_TEMPLATE_ID_PARAMETER]),
)
class HogFlowTemplateViewSet(TeamAndOrgViewSetMixin, LogEntryMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    serializer_class = HogFlowTemplateSerializer
    permission_classes = [PreventGlobalTemplateDatabaseOperations]
    log_source = "hog_flow_template"
    app_source = "hog_flow_template"
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def dangerously_get_object(self) -> WorkflowTemplate:
        # Team and org scoping happens in the facade lookup, as the model has no fail-closed manager.
        template = get_template(
            team_id=self.team_id, organization_id=self.organization.id, template_id=str(self.kwargs["pk"])
        )
        if template is None:
            raise NotFound()
        self.check_object_permissions(self.request, template)
        return template

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Override list to include global templates from files alongside team templates from DB.
        """
        # Get team templates from database (unpaginated first)
        db_templates = self.get_serializer(
            list_templates(team_id=self.team_id, organization_id=self.organization.id), many=True
        ).data

        # Load global templates from files
        try:
            file_templates = list_global_templates()
        except Exception as e:
            logger.warning("Failed to load global templates from files", error=str(e))
            file_templates = []

        # Combine both sources (file templates first so they appear at top)
        all_templates = list(file_templates) + list(db_templates)

        # Now paginate the combined list
        page = self.paginate_queryset(all_templates)
        if page is not None:
            return self.get_paginated_response(page)

        return Response(all_templates)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Check file-based global templates first, then DB team templates.
        The DB lookup excludes all global templates, so this only returns team templates from DB.
        """
        template_id: str = kwargs["pk"]

        # Check if it's a global template from files
        file_template = get_global_template(template_id)
        if file_template:
            return Response(file_template)

        # Not in files, check DB for team templates
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        template = create_template(
            team_id=self.team_id, created_by_id=cast(User, request.user).id, fields=serializer.validated_data
        )
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
            item_id=template.id,
            scope="HogFlowTemplate",
            activity="created",
            detail=Detail(name=template.name, type="standard"),
        )

        try:
            # report_user_action injects source and MCP-client properties so template usage is
            # attributable per channel (web builder vs MCP vs raw API).
            report_user_action(
                request.user,
                "hog_flow_template_created",
                {
                    "workflow_template_id": str(template.id),
                    "workflow_template_name": template.name,
                    "edges_count": len(template.edges or []),
                    "actions_count": len(template.actions or []),
                    "team_id": str(self.team_id),
                    "organization_id": str(self.organization.id),
                    "scope": template.scope,
                },
                team=self.team,
                request=request,
            )
        except Exception as e:
            logger.warning("Failed to capture hog_flow_template_created event", error=str(e))

        return Response(self.get_serializer(template).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        template = self.get_object()
        serializer = self.get_serializer(template, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=cast(User, request.user),
            was_impersonated=is_impersonated(request),
            item_id=template.id,
            scope="HogFlowTemplate",
            activity="updated",
            detail=Detail(name=template.name, type="standard"),
        )
        try:
            updated = update_template(
                template_id=template.id,
                team_id=self.team_id,
                organization_id=self.organization.id,
                fields=serializer.validated_data,
            )
        except WorkflowTemplateNotFound:
            raise NotFound()
        return Response(self.get_serializer(updated).data)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        template = self.get_object()
        # Authentication is enforced, so user cannot be AnonymousUser
        user = cast(User, request.user)
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team_id,
            user=user,
            was_impersonated=is_impersonated(request),
            item_id=template.id,
            scope="HogFlowTemplate",
            activity="deleted",
            detail=Detail(name=template.name, type="standard"),
        )

        delete_template(template_id=template.id, team_id=self.team_id, organization_id=self.organization.id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublicHogFlowTemplateViewSet(
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Public endpoint for global hogflow templates that doesn't require authentication.
    Global templates are now loaded from code files instead of the database.
    """

    permission_classes = [permissions.AllowAny]
    serializer_class = HogFlowTemplateSerializer

    def list(self, request, *args, **kwargs):
        """
        Load and return global templates from files.
        """
        try:
            templates = list_global_templates()
            # Sort by updated_at descending (most recent first)
            templates.sort(key=lambda t: t.get("updated_at", ""), reverse=True)

            # Return paginated response
            page = self.paginate_queryset(templates)
            if page is not None:
                return self.get_paginated_response(page)

            return Response(templates)
        except Exception:
            logger.exception("Failed to load global templates from files")
            return Response({"error": "Failed to load global templates"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
