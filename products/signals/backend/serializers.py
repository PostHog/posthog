import json

from rest_framework import serializers

from .models import SignalReport, SignalReportArtefact, SignalSourceConfig


class SignalSourceConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SignalSourceConfig
        fields = [
            "id",
            "source_product",
            "source_type",
            "enabled",
            "config",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs: dict) -> dict:
        source_product = attrs.get("source_product", getattr(self.instance, "source_product", None))
        config = attrs.get("config", {})
        if source_product == SignalSourceConfig.SourceProduct.SESSION_REPLAY and config:
            recording_filters = config.get("recording_filters")
            if recording_filters is not None and not isinstance(recording_filters, dict):
                raise serializers.ValidationError({"config": "recording_filters must be a JSON object"})
        return attrs


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
        try:
            return json.loads(obj.content)
        except (json.JSONDecodeError, ValueError):
            return {}
