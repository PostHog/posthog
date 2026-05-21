from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


class ErrorTrackingIssueAssignmentSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()

    @extend_schema_field({"oneOf": [{"type": "integer"}, {"type": "string"}], "nullable": True})
    def get_id(self, obj: Any) -> int | str | None:
        return obj.user_id if obj.user_id else str(obj.role_id) if obj.role_id else None

    @extend_schema_field(serializers.CharField())
    def get_type(self, obj: Any) -> str:
        return "role" if obj.role else "user"
