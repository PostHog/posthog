from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from products.error_tracking.backend.models import ErrorTrackingIssueAssignment


class ErrorTrackingIssueAssignmentSerializer(serializers.ModelSerializer):
    id = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingIssueAssignment
        fields = ["id", "type"]

    @extend_schema_field({"oneOf": [{"type": "integer"}, {"type": "string"}], "nullable": True})
    def get_id(self, obj: ErrorTrackingIssueAssignment) -> int | str | None:
        return obj.user_id if obj.user_id else str(obj.role_id) if obj.role_id else None

    @extend_schema_field(serializers.CharField())
    def get_type(self, obj: ErrorTrackingIssueAssignment) -> str:
        return "role" if obj.role else "user"
