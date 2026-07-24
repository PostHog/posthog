from typing import Any, Optional

import structlog
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.api.hog_flow import HogFlowConfigFunctionInputsSerializer
from products.workflows.backend.models import HogFlowActionTemplate
from products.workflows.backend.services.action_template_usage import (
    HogFlowReference,
    get_hog_flows_referencing_action_templates,
)

logger = structlog.get_logger(__name__)


@extend_schema_field(
    {
        "type": "object",
        "description": (
            "Function inputs keyed by the catalog template's input schema keys, each wrapped as "
            '{"value": ...}. String values support hog templating like {person.properties.email}. '
            'Secret inputs are stored encrypted and read back as the marker {"secret": true}; send the '
            "marker back unchanged to keep the stored value, or send a new value to replace it."
        ),
        "additionalProperties": {
            "type": "object",
            "properties": {
                "value": {"description": "The input value; shape depends on the input schema type."},
                "secret": {
                    "type": "boolean",
                    "description": "Read marker meaning a secret value is stored server-side.",
                },
            },
        },
    }
)
class ActionTemplateInputsField(serializers.JSONField):
    pass


@extend_schema_field(
    {
        "type": "array",
        "items": {"type": "object"},
        "description": (
            "Optional mappings for catalog templates that use per-event mappings; same shape as a "
            "workflow function action's config.mappings."
        ),
    }
)
class ActionTemplateMappingsField(serializers.JSONField):
    pass


class HogFlowActionTemplateSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    inputs = ActionTemplateInputsField(required=False, default=dict)
    mappings = ActionTemplateMappingsField(required=False, allow_null=True)
    usage_count = serializers.SerializerMethodField(
        help_text="Number of non-archived workflows with a step linked to this template (drafts included)."
    )

    class Meta:
        model = HogFlowActionTemplate
        fields = [
            "id",
            "name",
            "description",
            "template_id",
            "inputs",
            "mappings",
            "created_at",
            "updated_at",
            "created_by",
            "deleted",
            "usage_count",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "created_by", "usage_count"]
        extra_kwargs = {
            "name": {"help_text": "Human-readable template name shown in the library and step selector."},
            "description": {"help_text": "What the template is for and when to use it."},
            "template_id": {
                "help_text": (
                    "The catalog hog function template this configuration is for, e.g. 'template-webhook'. "
                    "Immutable after creation — changing it would swap the function under every linked workflow step."
                )
            },
            "deleted": {
                "help_text": (
                    "Soft-delete flag. Setting it to true is rejected while any non-archived workflow "
                    "still links to this template."
                )
            },
        }

    def _get_catalog_template(self, template_id: str) -> Optional[HogFunctionTemplate]:
        # Per-request cache: list responses would otherwise refetch the same catalog row per item.
        cache: dict[str, Optional[HogFunctionTemplate]] = self.context.setdefault("_catalog_template_cache", {})
        if template_id not in cache:
            cache[template_id] = HogFunctionTemplate.get_template(template_id)
        return cache[template_id]

    @extend_schema_field(serializers.IntegerField)
    def get_usage_count(self, instance: HogFlowActionTemplate) -> int:
        usage_map = self.context.get("_action_template_usage_map")
        if usage_map is None:
            usage_map = get_hog_flows_referencing_action_templates(team_id=instance.team_id)
            self.context["_action_template_usage_map"] = usage_map
        return len(usage_map.get(str(instance.id), []))

    def validate(self, attrs: dict) -> dict:
        template_id = attrs.get("template_id") or (self.instance.template_id if self.instance else None)
        if self.instance and "template_id" in attrs and attrs["template_id"] != self.instance.template_id:
            raise serializers.ValidationError(
                {"template_id": "The catalog template of a saved action template cannot be changed."}
            )
        if not template_id:
            raise serializers.ValidationError({"template_id": "This field is required."})

        catalog_template = self._get_catalog_template(template_id)
        if not catalog_template:
            raise serializers.ValidationError({"template_id": "Template not found"})
        if catalog_template.type != "destination":
            raise serializers.ValidationError(
                {"template_id": "Saved action templates are only supported for destination templates."}
            )

        if "inputs" in attrs:
            inputs_serializer = HogFlowConfigFunctionInputsSerializer(
                data={"inputs_schema": catalog_template.inputs_schema, "inputs": attrs.get("inputs") or {}},
                context={
                    "function_type": catalog_template.type,
                    # Secrets round-trip: a {"secret": true} marker (or omitted secret input) resolves
                    # back to the stored encrypted value, exactly like HogFunctionSerializer.
                    "encrypted_inputs": self.instance.encrypted_inputs or {} if self.instance else {},
                },
            )
            inputs_serializer.is_valid(raise_exception=True)
            attrs["inputs"] = inputs_serializer.validated_data.get("inputs", {})

        if attrs.get("deleted") is True and self.instance and not self.instance.deleted:
            references = get_hog_flows_referencing_action_templates(
                team_id=self.instance.team_id, template_ids=[str(self.instance.id)]
            ).get(str(self.instance.id), [])
            if references:
                names = ", ".join(ref.name for ref in references[:5])
                suffix = "…" if len(references) > 5 else ""
                raise serializers.ValidationError(
                    {
                        "deleted": (
                            f"This template is used by {len(references)} workflow(s): {names}{suffix}. "
                            "Unlink or customize those steps first."
                        )
                    }
                )

        return attrs

    def _split_secret_inputs(self, template_id: str, inputs: dict) -> tuple[dict, dict]:
        catalog_template = self._get_catalog_template(template_id)
        secret_keys = {
            str(schema["key"])
            for schema in (catalog_template.inputs_schema if catalog_template else None) or []
            if schema.get("secret")
        }
        plain = {key: value for key, value in inputs.items() if key not in secret_keys}
        secret = {key: value for key, value in inputs.items() if key in secret_keys}
        return plain, secret

    def create(self, validated_data: dict) -> HogFlowActionTemplate:
        request = self.context["request"]
        team_id = self.context["team_id"]

        inputs, encrypted_inputs = self._split_secret_inputs(
            validated_data["template_id"], validated_data.pop("inputs", {}) or {}
        )
        return HogFlowActionTemplate.objects.create(
            **validated_data,
            inputs=inputs,
            encrypted_inputs=encrypted_inputs,
            team_id=team_id,
            created_by=request.user,
        )

    def update(self, instance: HogFlowActionTemplate, validated_data: dict) -> HogFlowActionTemplate:
        if "inputs" in validated_data:
            inputs, encrypted_inputs = self._split_secret_inputs(
                instance.template_id, validated_data.pop("inputs") or {}
            )
            validated_data["inputs"] = inputs
            validated_data["encrypted_inputs"] = encrypted_inputs
        return super().update(instance, validated_data)

    def to_representation(self, instance: HogFlowActionTemplate) -> dict:
        data = super().to_representation(instance)
        catalog_template = self._get_catalog_template(instance.template_id)
        inputs = data.get("inputs") or {}
        encrypted_inputs = instance.encrypted_inputs or {}
        for schema in (catalog_template.inputs_schema if catalog_template else None) or []:
            if schema.get("secret") and encrypted_inputs.get(schema["key"]):
                # Marker to indicate to the user that a secret is set without exposing it
                inputs[schema["key"]] = {"secret": True}
        data["inputs"] = inputs
        return data


class HogFlowActionTemplateUsageReferenceSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Workflow (HogFlow) id.")
    name = serializers.CharField(help_text="Workflow name.")
    status = serializers.CharField(help_text="Workflow status: draft or active.")


class HogFlowActionTemplateUsageSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Number of non-archived workflows linking to this template.")
    hog_flows = serializers.ListField(
        child=HogFlowActionTemplateUsageReferenceSerializer(),
        help_text="The workflows with a step linked to this template (drafts included).",
    )


class HogFlowActionTemplateViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "hog_flow"
    permission_classes = [IsAuthenticated]
    serializer_class = HogFlowActionTemplateSerializer
    # unscoped() only seeds the base queryset (the fail-closed manager raises at import time with no
    # team context); actual scoping happens per request via safely_get_queryset + the mixin's
    # parents-lookup team filter.
    queryset = HogFlowActionTemplate.objects.unscoped()

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(team_id=self.team_id, deleted=False).select_related("created_by")
        if self.action == "list":
            template_id = self.request.query_params.get("template_id")
            if template_id:
                queryset = queryset.filter(template_id=template_id)
        return queryset.order_by("-updated_at")

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "template_id",
                type=str,
                description="Only return saved templates for this catalog template id, e.g. 'template-webhook'.",
                required=False,
            )
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(responses={200: HogFlowActionTemplateUsageSerializer})
    @action(detail=True, methods=["GET"])
    def usage(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        references: list[HogFlowReference] = get_hog_flows_referencing_action_templates(
            team_id=self.team_id, template_ids=[str(instance.id)]
        ).get(str(instance.id), [])
        serializer = HogFlowActionTemplateUsageSerializer(
            {
                "count": len(references),
                "hog_flows": [{"id": ref.id, "name": ref.name, "status": ref.status} for ref in references],
            }
        )
        return Response(serializer.data)
