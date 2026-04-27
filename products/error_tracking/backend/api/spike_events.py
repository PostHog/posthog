from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingSpikeEvent


class ErrorTrackingSpikeEventIssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingIssue
        fields = ["id", "name", "description"]
        read_only_fields = fields


class ErrorTrackingSpikeEventSerializer(serializers.ModelSerializer):
    issue = ErrorTrackingSpikeEventIssueSerializer(read_only=True)

    class Meta:
        model = ErrorTrackingSpikeEvent
        fields = [
            "id",
            "issue",
            "detected_at",
            "computed_baseline",
            "current_bucket_value",
        ]
        read_only_fields = fields


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingSpikeEventViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingSpikeEventSerializer
    queryset = ErrorTrackingSpikeEvent.objects.all()

    ALLOWED_ORDER_FIELDS = [
        "detected_at",
        "-detected_at",
        "computed_baseline",
        "-computed_baseline",
        "current_bucket_value",
        "-current_bucket_value",
    ]

    def safely_get_queryset(self, queryset):
        qs = queryset.filter(team_id=self.team.id).select_related("issue")

        issue_ids_param = self.request.query_params.get("issue_ids")
        if issue_ids_param:
            ids = [uid.strip() for uid in issue_ids_param.split(",") if uid.strip()]
            if ids:
                qs = qs.filter(issue_id__in=ids)

        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from:
            qs = qs.filter(detected_at__gte=date_from)
        if date_to:
            qs = qs.filter(detected_at__lte=date_to)

        order_by = self.request.query_params.get("order_by")
        if order_by and order_by in self.ALLOWED_ORDER_FIELDS:
            qs = qs.order_by(order_by)
        else:
            qs = qs.order_by("-detected_at")

        return qs
