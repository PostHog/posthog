# These serializers live outside api/ on purpose: the hogql_queries runners need them,
# and any `api.*` import executes api/__init__.py, whose viewset imports circle back into
# the runners (api/query.py imports ErrorTrackingQueryRunner).
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueAssignment


class ErrorTrackingIssueAssignmentSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingIssueAssignment
        fields = ["id", "type"]

    @extend_schema_field({"oneOf": [{"type": "integer"}, {"type": "string"}], "nullable": True})
    def get_id(self, obj):
        return obj.user_id if obj.user_id else str(obj.role_id) if obj.role_id else None

    @extend_schema_field(serializers.CharField())
    def get_type(self, obj):
        return "role" if obj.role else "user"


_FIRST_SEEN_FIELD = serializers.DateTimeField()


class ErrorTrackingIssuePreviewSerializer(serializers.ModelSerializer):
    first_seen = serializers.SerializerMethodField()
    assignee = ErrorTrackingIssueAssignmentSerializer(source="assignment")

    class Meta:
        model = ErrorTrackingIssue
        fields = ["id", "status", "name", "description", "first_seen", "assignee"]

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_first_seen(self, obj):
        # The caller resolves first_seen for every issue in one query and passes the result in.
        first_seen = self.context["first_seen_by_issue"].get(obj.id)
        return _FIRST_SEEN_FIELD.to_representation(first_seen) if first_seen else None
