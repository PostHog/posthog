from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import JsonResponse
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt

import structlog
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import get_token
from posthog.cdp.internal_events import InternalEventEvent, InternalEventPerson, produce_internal_event
from posthog.exceptions import generate_exception_response
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.utils import uuid7
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControl, UserAccessControlSerializerMixin
from posthog.tasks.early_access_feature import send_events_for_early_access_feature_stage_change
from posthog.utils_cors import cors_response

from products.feature_flags.backend.api.feature_flag import (
    FeatureFlagSerializer,
    MinimalFeatureFlagSerializer,
    assert_feature_flag_write_scope,
)
from products.feature_flags.backend.facade.api import apply_default_evaluation_contexts
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.models.rbac.role import Role

from .models import EarlyAccessFeature

logger = structlog.get_logger(__name__)


def _set_enrollment_filters(existing: dict, *, enrolled: bool | None, **overrides: Any) -> dict:
    filters = {**existing, "feature_enrollment": enrolled, **overrides}
    filters.pop("super_groups", None)
    return filters


def assert_feature_flag_rbac_access(
    user_access_control: UserAccessControl | None,
    *,
    feature_flag: FeatureFlag | None = None,
) -> None:
    """Early access feature writes create or mutate a linked feature flag through the FeatureFlag
    serializer directly, bypassing the FeatureFlag viewset's RBAC gate. Enforce the same feature_flag
    access control here so early_access_feature editor access can't be used to write feature flags a
    user otherwise couldn't. Pass ``feature_flag`` to check editing that object; omit it to check
    creating a new flag (resource level). Fails open when access controls aren't enabled — the checks
    resolve to the default editor level."""
    if user_access_control is None:
        return
    has_access = (
        user_access_control.check_access_level_for_object(feature_flag, "editor")
        if feature_flag is not None
        else user_access_control.check_access_level_for_resource("feature_flag", "editor")
    )
    if not has_access:
        raise PermissionDenied("You don't have sufficient permissions to modify the linked feature flag.")


class MinimalEarlyAccessFeatureSerializer(serializers.ModelSerializer):
    """
    A more minimal serializer, intended specificaly for non-generally-available features to be provided
    to posthog-js via the /early_access_features/ endpoint. Sync with posthog-js's FeaturePreview interface!

    The assignee only carries a display name (no user ID or email): the endpoint is public
    (project-token auth), so consumers like posthog.com's roadmap can attribute a feature to
    its owner without exposing anything else about the person or role.
    """

    documentationUrl = serializers.URLField(source="documentation_url")
    flagKey = serializers.CharField(source="feature_flag.key", allow_null=True)
    payload = serializers.SerializerMethodField()
    assignee = serializers.SerializerMethodField()

    class Meta:
        model = EarlyAccessFeature
        fields = [
            "id",
            "name",
            "description",
            "stage",
            "documentationUrl",
            "flagKey",
            "payload",
            "assignee",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.DictField(help_text="Feature flag payload for this early access feature"))
    def get_payload(self, obj):
        return obj.payload if obj.payload else {}

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "description": "Display name of the person or role this feature is assigned to, e.g. "
            '{"type": "user", "name": "Ada Lovelace"} or {"type": "role", "name": "Data Modeling"}.',
            "properties": {
                "type": {"type": "string", "enum": ["user", "role"]},
                "name": {"type": "string"},
            },
        }
    )
    def get_assignee(self, obj):
        # Callers serializing many features should select_related assigned_user/assigned_role;
        # for unassigned features the *_id checks avoid touching the relations entirely.
        if obj.assigned_user_id and obj.assigned_user:
            name = f"{obj.assigned_user.first_name} {obj.assigned_user.last_name}".strip()
            # Users without a set name (common for SSO/invited accounts) would otherwise
            # surface an "assigned but nameless" payload, which is worse than no assignee;
            # treat them as unassigned rather than exposing a blank name.
            if name:
                return {"type": "user", "name": name}
            return None
        if obj.assigned_role_id and obj.assigned_role:
            return {"type": "role", "name": obj.assigned_role.name}
        return None


class EarlyAccessFeatureSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    feature_flag = MinimalFeatureFlagSerializer(read_only=True)
    name = serializers.CharField(
        max_length=200,
        help_text="The name of the early access feature.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="A longer description of what this early access feature does, shown to users in the opt-in UI.",
    )
    stage = serializers.ChoiceField(
        choices=EarlyAccessFeature.Stage.choices,
        help_text="Lifecycle stage. Valid values: draft, concept, alpha, beta, general-availability, archived. Moving to an active stage (alpha/beta/general-availability) enables the feature flag for opted-in users.",
    )
    documentation_url = serializers.URLField(
        max_length=800,
        required=False,
        allow_blank=True,
        help_text="URL to external documentation for this feature. Shown to users in the opt-in UI.",
    )
    payload = serializers.SerializerMethodField()
    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="The user who created this early access feature. Null for features created before creator tracking was added.",
    )
    assignee = serializers.SerializerMethodField()

    class Meta:
        model = EarlyAccessFeature
        fields = [
            "id",
            "feature_flag",
            "name",
            "description",
            "stage",
            "documentation_url",
            "payload",
            "created_at",
            "created_by",
            "assignee",
            "user_access_level",
        ]
        read_only_fields = ["id", "feature_flag", "created_at", "created_by"]

    @extend_schema_field(serializers.DictField(help_text="Feature flag payload for this early access feature"))
    def get_payload(self, obj):
        return obj.payload if obj.payload else {}

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "description": 'The person or role responsible for this feature, e.g. {"type": "user", "id": 123} or '
            '{"type": "role", "id": "<role uuid>"}. Defaults to the creator. Send null to unassign.',
            "properties": {
                "type": {"type": "string", "enum": ["user", "role"]},
                "id": {"oneOf": [{"type": "integer"}, {"type": "string"}]},
            },
        }
    )
    def get_assignee(self, obj):
        if obj.assigned_user_id:
            return {"type": "user", "id": obj.assigned_user_id}
        if obj.assigned_role_id:
            return {"type": "role", "id": str(obj.assigned_role_id)}
        return None

    def _validated_assignee_fields(self, assignee: Any) -> dict:
        """Convert an assignee payload ({"type": "user"|"role", "id": ...} or None) into model field values,
        validating that the referenced user/role belongs to this team's organization."""
        if assignee is None:
            return {"assigned_user_id": None, "assigned_role_id": None}
        if (
            not isinstance(assignee, dict)
            or assignee.get("type") not in ("user", "role")
            or assignee.get("id") in (None, "")
        ):
            raise serializers.ValidationError(
                {"assignee": 'Expected null or an object of shape {"type": "user" | "role", "id": ...}.'}
            )
        organization = self.context["get_organization"]()
        try:
            if assignee["type"] == "user":
                if not OrganizationMembership.objects.filter(
                    user_id=assignee["id"], organization=organization
                ).exists():
                    raise serializers.ValidationError(
                        {"assignee": "Assignee user does not belong to this organization."}
                    )
                return {"assigned_user_id": assignee["id"], "assigned_role_id": None}
            if not Role.objects.filter(id=assignee["id"], organization=organization).exists():
                raise serializers.ValidationError({"assignee": "Assignee role does not belong to this organization."})
            return {"assigned_user_id": None, "assigned_role_id": assignee["id"]}
        except (ValueError, TypeError, DjangoValidationError):
            raise serializers.ValidationError({"assignee": "Assignee ID is invalid."})

    def update(self, instance: EarlyAccessFeature, validated_data: Any) -> EarlyAccessFeature:
        # Handle payload separately since SerializerMethodField is read-only
        if "payload" in self.initial_data:
            payload_value = self.initial_data.get("payload")
            validated_data["payload"] = payload_value if payload_value else {}
        # Same for assignee, which also diverges from the model fields (assigned_user/assigned_role)
        if "assignee" in self.initial_data:
            validated_data.update(self._validated_assignee_fields(self.initial_data.get("assignee")))
        stage = validated_data.get("stage", None)
        rollout_to_all = self.initial_data.get("rollout_to_all", False)

        request = self.context["request"]
        user_data = UserBasicSerializer(request.user).data if request.user else None
        serialized_previous = MinimalEarlyAccessFeatureSerializer(instance).data

        if instance.stage != stage:
            send_events_for_early_access_feature_stage_change.delay(str(instance.id), instance.stage, stage)

        # The branches below each mutate the linked flag's enrollment filters, so they require
        # feature_flag:write. A stage change that writes no flag row is intentionally not gated.
        if instance.stage != stage and stage == EarlyAccessFeature.Stage.GENERAL_AVAILABILITY and rollout_to_all:
            related_feature_flag = instance.feature_flag
            if related_feature_flag:
                assert_feature_flag_write_scope(
                    request,
                    action="early_access_feature.stage_change",
                    resource_scope="early_access_feature:write",
                    team_id=instance.team_id,
                    feature_flag_id=related_feature_flag.id,
                )
                assert_feature_flag_rbac_access(self.user_access_control, feature_flag=related_feature_flag)
                serialized_data_filters = _set_enrollment_filters(
                    related_feature_flag.filters,
                    enrolled=None,
                    groups=[{"properties": [], "rollout_percentage": 100}],
                )

                serializer = FeatureFlagSerializer(
                    related_feature_flag,
                    data={"filters": serialized_data_filters},
                    context=self.context,
                    partial=True,
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()
        elif instance.stage not in EarlyAccessFeature.ActiveStage and stage in EarlyAccessFeature.ActiveStage:
            related_feature_flag = instance.feature_flag
            if related_feature_flag:
                assert_feature_flag_write_scope(
                    request,
                    action="early_access_feature.stage_change",
                    resource_scope="early_access_feature:write",
                    team_id=instance.team_id,
                    feature_flag_id=related_feature_flag.id,
                )
                assert_feature_flag_rbac_access(self.user_access_control, feature_flag=related_feature_flag)
                serialized_data_filters = _set_enrollment_filters(related_feature_flag.filters, enrolled=True)

                serializer = FeatureFlagSerializer(
                    related_feature_flag,
                    data={"filters": serialized_data_filters},
                    context=self.context,
                    partial=True,
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()
        elif stage is not None and (stage not in EarlyAccessFeature.ActiveStage):
            related_feature_flag = instance.feature_flag
            if related_feature_flag:
                assert_feature_flag_write_scope(
                    request,
                    action="early_access_feature.stage_change",
                    resource_scope="early_access_feature:write",
                    team_id=instance.team_id,
                    feature_flag_id=related_feature_flag.id,
                )
                assert_feature_flag_rbac_access(self.user_access_control, feature_flag=related_feature_flag)
                related_feature_flag.filters = _set_enrollment_filters(related_feature_flag.filters, enrolled=None)
                related_feature_flag.save()

        updated_instance = super().update(instance, validated_data)

        serialized_next = MinimalEarlyAccessFeatureSerializer(updated_instance).data
        produce_internal_event(
            team_id=instance.team_id,
            event=InternalEventEvent(
                event="$early_access_feature_updated",
                distinct_id=str(uuid7()),
                properties={
                    "previous": serialized_previous,
                    "next": serialized_next,
                },
            ),
            person=(
                InternalEventPerson(
                    id=user_data["id"],
                    properties=user_data,
                )
                if user_data
                else None
            ),
        )

        return updated_instance


class EarlyAccessFeatureSerializerCreateOnly(EarlyAccessFeatureSerializer):
    feature_flag_id = serializers.IntegerField(
        required=False,
        write_only=True,
        help_text="Optional ID of an existing feature flag to link. If omitted, a new flag is auto-created from the feature name. The flag must not already be linked to another feature, must not be group-based, and must not be multivariate.",
    )
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

    # Override payload to allow writing (parent uses SerializerMethodField which is read-only)
    payload = serializers.JSONField(
        required=False,
        allow_null=False,
        default=dict,
        help_text="Arbitrary JSON metadata associated with this feature.",
    )  # type: ignore

    class Meta:
        model = EarlyAccessFeature
        fields = [
            "id",
            "name",
            "description",
            "stage",
            "documentation_url",
            "payload",
            "created_at",
            "created_by",
            "assignee",
            "feature_flag_id",
            "feature_flag",
            "_create_in_folder",
            "user_access_level",
        ]
        read_only_fields = ["id", "feature_flag", "created_at", "created_by"]

    def validate(self, data):
        feature_flag_id = data.get("feature_flag_id", None)

        feature_flag = None
        if feature_flag_id:
            try:
                feature_flag = FeatureFlag.objects.get(pk=feature_flag_id, team_id=self.context["team_id"])
            except FeatureFlag.DoesNotExist:
                raise serializers.ValidationError("Feature Flag with this ID does not exist")

            if feature_flag.features.exists():
                raise serializers.ValidationError(
                    f"Linked feature flag {feature_flag.key} already has a feature attached to it."
                )

            if feature_flag.aggregation_group_type_index is not None:
                raise serializers.ValidationError(
                    "Group-based feature flags are not supported for Early Access Features."
                )

            if len(feature_flag.variants) > 0:
                raise serializers.ValidationError(
                    "Multivariate feature flags are not supported for Early Access Features."
                )

        return data

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]

        request = self.context["request"]
        validated_data["created_by"] = request.user if request.user.is_authenticated else None
        if "assignee" in self.initial_data:
            validated_data.update(self._validated_assignee_fields(self.initial_data.get("assignee")))
        elif validated_data["created_by"] is not None:
            # By default, the feature is assigned to whoever created it
            validated_data["assigned_user_id"] = validated_data["created_by"].id

        feature_flag_id = validated_data.get("feature_flag_id", None)

        default_condition = [
            {"properties": [], "rollout_percentage": 0, "variant": None},
        ]

        if feature_flag_id:
            feature_flag = FeatureFlag.objects.get(pk=feature_flag_id, team_id=self.context["team_id"])

            # Only require feature_flag:write when we actually mutate the linked flag (active
            # stage). Linking an existing flag without changing it is not a flag write.
            if validated_data.get("stage") in EarlyAccessFeature.ActiveStage:
                assert_feature_flag_write_scope(
                    self.context["request"],
                    action="early_access_feature.create",
                    resource_scope="early_access_feature:write",
                    team_id=self.context["team_id"],
                    feature_flag_id=feature_flag.id,
                )
                assert_feature_flag_rbac_access(self.user_access_control, feature_flag=feature_flag)
                serialized_data_filters = _set_enrollment_filters(feature_flag.filters, enrolled=True)

                serializer = FeatureFlagSerializer(
                    feature_flag,
                    data={"filters": serialized_data_filters},
                    context=self.context,
                    partial=True,
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()
        else:
            # No existing flag: we create one, which is a flag write.
            assert_feature_flag_write_scope(
                self.context["request"],
                action="early_access_feature.create",
                resource_scope="early_access_feature:write",
                team_id=self.context["team_id"],
            )
            assert_feature_flag_rbac_access(self.user_access_control)
            feature_flag_key = slugify(validated_data["name"])

            filters: dict[str, Any] = {
                "groups": default_condition,
            }

            if validated_data.get("stage") in EarlyAccessFeature.ActiveStage:
                filters["feature_enrollment"] = True

            feature_flag_data: dict[str, Any] = {
                "key": feature_flag_key,
                "name": f"Feature Flag for Early Access Feature {validated_data['name']}",
                "filters": filters,
                "creation_context": "early_access_features",
            }
            apply_default_evaluation_contexts(
                feature_flag_data, self.context["get_team"](), self.context["request"].user
            )

            feature_flag_serializer = FeatureFlagSerializer(
                data=feature_flag_data,
                context=self.context,
            )

            feature_flag_serializer.is_valid(raise_exception=True)
            feature_flag = feature_flag_serializer.save()

        validated_data["feature_flag_id"] = feature_flag.id
        feature: EarlyAccessFeature = super().create(validated_data)
        return feature


class EarlyAccessFeatureViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "early_access_feature"
    queryset = EarlyAccessFeature.objects.select_related(
        "feature_flag", "created_by", "assigned_user", "assigned_role"
    ).all()

    def get_serializer_class(self) -> type[serializers.Serializer]:
        if self.request.method == "POST":
            return EarlyAccessFeatureSerializerCreateOnly
        else:
            return EarlyAccessFeatureSerializer

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        related_feature_flag = instance.feature_flag

        if related_feature_flag:
            assert_feature_flag_write_scope(
                request,
                action="early_access_feature.destroy",
                team_id=instance.team_id,
                feature_flag_id=related_feature_flag.id,
                resource_scope="early_access_feature:write",
            )
            assert_feature_flag_rbac_access(self.user_access_control, feature_flag=related_feature_flag)
            related_feature_flag.filters = _set_enrollment_filters(related_feature_flag.filters, enrolled=None)
            related_feature_flag.save()

        return super().destroy(request, *args, **kwargs)


@csrf_exempt
def early_access_features(request: Request):
    token = get_token(None, request)
    stages = request.GET.getlist("stage", [EarlyAccessFeature.Stage.BETA])

    if not token:
        return cors_response(
            request,
            generate_exception_response(
                "early_access_features",
                "Project token not provided. You can find your project token in PostHog project settings.",
                type="authentication_error",
                code="missing_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    team = Team.objects.get_team_from_cache_or_token(token)
    if team is None:
        return cors_response(
            request,
            generate_exception_response(
                "decide",
                "Project token invalid. You can find your project token in PostHog project settings.",
                type="authentication_error",
                code="invalid_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    early_access_features = MinimalEarlyAccessFeatureSerializer(
        EarlyAccessFeature.objects.filter(team__project_id=team.project_id, stage__in=stages).select_related(
            "feature_flag", "assigned_user", "assigned_role"
        ),
        many=True,
    ).data

    return cors_response(request, JsonResponse({"earlyAccessFeatures": early_access_features}))
