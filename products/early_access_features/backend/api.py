from typing import Any

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
from products.feature_flags.backend.models.feature_flag import FeatureFlag

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
    """

    documentationUrl = serializers.URLField(source="documentation_url")
    flagKey = serializers.CharField(source="feature_flag.key", allow_null=True)
    payload = serializers.SerializerMethodField()

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
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.DictField(help_text="Feature flag payload for this early access feature"))
    def get_payload(self, obj):
        return obj.payload if obj.payload else {}


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
            "user_access_level",
        ]
        read_only_fields = ["id", "feature_flag", "created_at"]

    @extend_schema_field(serializers.DictField(help_text="Feature flag payload for this early access feature"))
    def get_payload(self, obj):
        return obj.payload if obj.payload else {}

    def update(self, instance: EarlyAccessFeature, validated_data: Any) -> EarlyAccessFeature:
        # Handle payload separately since SerializerMethodField is read-only
        if "payload" in self.initial_data:
            payload_value = self.initial_data.get("payload")
            validated_data["payload"] = payload_value if payload_value else {}
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
            "feature_flag_id",
            "feature_flag",
            "_create_in_folder",
            "user_access_level",
        ]
        read_only_fields = ["id", "feature_flag", "created_at"]

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

            feature_flag_serializer = FeatureFlagSerializer(
                data={
                    "key": feature_flag_key,
                    "name": f"Feature Flag for Early Access Feature {validated_data['name']}",
                    "filters": filters,
                    "creation_context": "early_access_features",
                },
                context=self.context,
            )

            feature_flag_serializer.is_valid(raise_exception=True)
            feature_flag = feature_flag_serializer.save()

        validated_data["feature_flag_id"] = feature_flag.id
        feature: EarlyAccessFeature = super().create(validated_data)
        return feature


class EarlyAccessFeatureViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    scope_object = "early_access_feature"
    queryset = EarlyAccessFeature.objects.select_related("feature_flag").all()

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
            "feature_flag"
        ),
        many=True,
    ).data

    return cors_response(request, JsonResponse({"earlyAccessFeatures": early_access_features}))


# devex: coverage reporter demo touch — remove before merge
# The body lines below are never exercised by a test, so diff-cover should flag them
# as uncovered changed lines (the def line runs at import and stays covered).
def _devex_coverage_demo(value: int) -> int:
    doubled = value * 2
    if doubled > 1000:
        return 1000
    return doubled
