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


class ErrorTrackingIssuePreviewSerializer(serializers.ModelSerializer):
    first_seen = serializers.DateTimeField()
    assignee = ErrorTrackingIssueAssignmentSerializer(source="assignment")

    class Meta:
        model = ErrorTrackingIssue
        fields = ["id", "status", "name", "description", "first_seen", "assignee"]
