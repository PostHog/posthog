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
            "total_weight",  # Used for priority scoring
            "signal_count",  # Used for occurrence count
            "relevant_user_count",
            "created_at",
            "updated_at",
            "artefact_count",
        ]
        read_only_fields = fields


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
