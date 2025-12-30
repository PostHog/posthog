from django.db import transaction
from django.db.models import QuerySet

import structlog
from rest_framework import serializers, viewsets
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.sdk_policy_config import SdkPolicyConfig, SdkPolicyConfigAssignment

logger = structlog.get_logger(__name__)


class SDKPolicyConfigAssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SdkPolicyConfigAssignment
        fields = [
            "id",
            "library",
        ]


class ErrorTrackingSDKPolicyConfigSerializer(serializers.ModelSerializer):
    assignments = SDKPolicyConfigAssignmentSerializer(many=True)

    class Meta:
        model = SdkPolicyConfig
        fields = [
            "id",
            "match_type",
            "sample_rate",
            "minimum_duration_milliseconds",
            "linked_feature_flag",
            "event_triggers",
            "url_triggers",
            "url_blocklist",
            "assignments",
        ]


class ErrorTrackingSDKPolicyConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = SdkPolicyConfig.objects.all()
    serializer_class = ErrorTrackingSDKPolicyConfigSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.prefetch_related("assignments").filter(team=self.team)
        if self.action == "list":
            context = self.request.query_params.get("context")
            queryset = queryset.filter(assignments__context=context, assignments__isnull=False).distinct()
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        if not queryset:
            with transaction.atomic():
                config = queryset.create(team=self.team)
                SdkPolicyConfigAssignment.objects.bulk_create(
                    [
                        SdkPolicyConfigAssignment(
                            team=self.team,
                            config=config,
                            context=SdkPolicyConfigAssignment.Context.ERROR_TRACKING,
                            library=None,
                        )
                    ]
                )
                serializer = self.get_serializer([config], many=True)
        else:
            serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
