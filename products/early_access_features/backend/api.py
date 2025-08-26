from typing import Any

from django.http import JsonResponse
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt

import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.feature_flag import FeatureFlagSerializer, MinimalFeatureFlagSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import get_token
from posthog.cdp.internal_events import InternalEventEvent, InternalEventPerson, produce_internal_event
from posthog.exceptions import generate_exception_response
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.team.team import Team
from posthog.models.utils import uuid7
from posthog.tasks.early_access_feature import send_events_for_early_access_feature_stage_change
from posthog.utils_cors import cors_response

from .models import EarlyAccessFeature

logger = structlog.get_logger(__name__)


class MinimalEarlyAccessFeatureSerializer(serializers.ModelSerializer):
    """
    A more minimal serializer, intended specificaly for non-generally-available features to be provided
    to posthog-js via the /early_access_features/ endpoint. Sync with posthog-js's FeaturePreview interface!
    """

    documentationUrl = serializers.URLField(source="documentation_url")
    flagKey = serializers.CharField(source="feature_flag.key", allow_null=True)

    class Meta:
        model = EarlyAccessFeature
        fields = [
            "id",
            "name",
            "description",
            "stage",
            "documentationUrl",
            "flagKey",
        ]
        read_only_fields = fields


class EarlyAccessFeatureSerializer(serializers.ModelSerializer):
    feature_flag = MinimalFeatureFlagSerializer(read_only=True)

    class Meta:
        model = EarlyAccessFeature
        fields = [
            "id",
            "feature_flag",
            "name",
            "description",
            "stage",
            "documentation_url",
            "created_at",
        ]
        read_only_fields = ["id", "feature_flag", "created_at"]

    def update(self, instance: EarlyAccessFeature, validated_data: Any) -> EarlyAccessFeature:
        stage = validated_data.get("stage", None)

        request = self.context["request"]
        user_data = UserBasicSerializer(request.user).data if request.user else None
        serialized_previous = MinimalEarlyAccessFeatureSerializer(instance).data

        if instance.stage != stage:
            send_events_for_early_access_feature_stage_change.delay(str(instance.id), instance.stage, stage)

        if instance.stage not in EarlyAccessFeature.ReleaseStage and stage in EarlyAccessFeature.ReleaseStage:
            super_conditions = lambda feature_flag_key: [
                {
                    "properties": [
                        {
                            "key": f"$feature_enrollment/{feature_flag_key}",
                            "type": "person",
                            "operator": "exact",
                            "value": ["true"],
                        },
                    ],
                    "rollout_percentage": 100,
                },
            ]

            related_feature_flag = instance.feature_flag
            if related_feature_flag:
                related_feature_flag_key = related_feature_flag.key
                serialized_data_filters = {
                    **related_feature_flag.filters,
                    "super_groups": super_conditions(related_feature_flag_key),
                }

                serializer = FeatureFlagSerializer(
                    related_feature_flag,
                    data={"filters": serialized_data_filters},
                    context=self.context,
                    partial=True,
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()
        elif stage is not None and (stage not in EarlyAccessFeature.ReleaseStage):
            related_feature_flag = instance.feature_flag
            if related_feature_flag:
                related_feature_flag.filters = {
                    **related_feature_flag.filters,
                    "super_groups": None,
                }
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
    feature_flag_id = serializers.IntegerField(required=False, write_only=True)
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = EarlyAccessFeature
        fields = [
            "id",
            "name",
            "description",
            "stage",
            "documentation_url",
            "created_at",
            "feature_flag_id",
            "feature_flag",
            "_create_in_folder",
        ]
        read_only_fields = ["id", "feature_flag", "created_at"]

    def validate(self, data):
        feature_flag_id = data.get("feature_flag_id", None)

        feature_flag = None
        if feature_flag_id:
            try:
                feature_flag = FeatureFlag.objects.get(pk=feature_flag_id)
            except FeatureFlag.DoesNotExist:
                raise serializers.ValidationError("Feature Flag with this ID does not exist")

            if feature_flag.features.count() > 0:
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
        super_conditions = lambda feature_flag_key: [
            {
                "properties": [
                    {
                        "key": f"$feature_enrollment/{feature_flag_key}",
                        "type": "person",
                        "operator": "exact",
                        "value": ["true"],
                    },
                ],
                "rollout_percentage": 100,
            },
        ]

        if feature_flag_id:
            # Modifying an existing feature flag
            feature_flag = FeatureFlag.objects.get(pk=feature_flag_id)
            feature_flag_key = feature_flag.key

            if validated_data.get("stage") in EarlyAccessFeature.ReleaseStage:
                serialized_data_filters = {
                    **feature_flag.filters,
                    "super_groups": super_conditions(feature_flag_key),
                }

                serializer = FeatureFlagSerializer(
                    feature_flag,
                    data={"filters": serialized_data_filters},
                    context=self.context,
                    partial=True,
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()
        else:
            feature_flag_key = slugify(validated_data["name"])

            filters = {
                "groups": default_condition,
            }

            if validated_data.get("stage") in EarlyAccessFeature.ReleaseStage:
                filters["super_groups"] = super_conditions(feature_flag_key)

            feature_flag_serializer = FeatureFlagSerializer(
                data={
                    "key": feature_flag_key,
                    "name": f"Feature Flag for Feature {validated_data['name']}",
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


class EarlyAccessFeatureViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
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
            related_feature_flag.filters = {
                **related_feature_flag.filters,
                "super_groups": None,
            }
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
                "API key not provided. You can find your project API key in PostHog project settings.",
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
                "Project API key invalid. You can find your project API key in PostHog project settings.",
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
