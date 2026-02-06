import json

from rest_framework import serializers

from .models import SignalReport, SignalReportArtefact


class SignalReportSerializer(serializers.ModelSerializer):
    artefact_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = SignalReport
        fields = [
            "id",
            "title",
            "summary",
            "status",
            "total_weight",
            "signal_count",
            "relevant_user_count",
            "created_at",
            "updated_at",
            "artefact_count",
        ]
        read_only_fields = fields


class SignalReportDebugSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField(allow_null=True)
    summary = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    total_weight = serializers.FloatField()
    signal_count = serializers.IntegerField()
    relevant_user_count = serializers.IntegerField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    pipeline_metadata = serializers.JSONField(allow_null=True)
    segments = serializers.ListField(child=serializers.DictField())
    sessions = serializers.ListField(child=serializers.DictField())


class SignalReportArtefactSerializer(serializers.ModelSerializer):
    content = serializers.SerializerMethodField()

    class Meta:
        model = SignalReportArtefact
        fields = ["id", "type", "content", "created_at"]
        read_only_fields = fields

    def get_content(self, obj: SignalReportArtefact) -> dict:
        """Parse JSON from content BinaryField."""
        try:
            content = bytes(obj.content) if isinstance(obj.content, memoryview) else obj.content
            return json.loads(content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
