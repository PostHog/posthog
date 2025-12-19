import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.sdk_policy_config import SdkPolicyConfig

logger = structlog.get_logger(__name__)


class ErrorTrackingSDKPolicyConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SdkPolicyConfig
        fields = [
            "id",
            "match_type",
            "sample_rate",
            "minimum_duration_milliseconds",
            "linked_feature_flag",
            "events_trigger",
            "url_trigger",
            "url_blocklist",
        ]


class ErrorTrackingSDKPolicyConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"

    @action(methods=["GET"], detail=False)
    def config(self, request, **kwargs):
        config = SdkPolicyConfig.objects.get_or_create(team_id=self.team.id)
        serializer = ErrorTrackingSDKPolicyConfigSerializer(config)
        return Response(serializer.data, status=status.HTTP_200_OK)
