from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingSpikeEvent


class ErrorTrackingSpikeEventSerializer(serializers.ModelSerializer):
    issue_id = serializers.UUIDField(source="issue.id")
    issue_name = serializers.CharField(source="issue.name", default=None, allow_null=True)
    issue_description = serializers.CharField(source="issue.description", default=None, allow_null=True)

    class Meta:
        model = ErrorTrackingSpikeEvent
        fields = [
            "id",
            "issue_id",
            "detected_at",
            "computed_baseline",
            "current_bucket_value",
            "issue_name",
            "issue_description",
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

        issue_ids = self.request.query_params.get("issue_ids")
        issue_id = self.request.query_params.get("issue_id")
        if issue_ids:
            ids = [uid.strip() for uid in issue_ids.split(",") if uid.strip()]
            qs = qs.filter(issue_id__in=ids)
        elif issue_id:
            qs = qs.filter(issue_id=issue_id)

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
