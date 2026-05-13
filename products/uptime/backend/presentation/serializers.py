from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import MonitorDTO, PingDTO, SuggestedUrlDTO


class MonitorSerializer(DataclassSerializer):
    class Meta:
        dataclass = MonitorDTO


class CreateMonitorSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Human-readable name of the monitor.")
    url = serializers.URLField(max_length=2048, help_text="HTTP(S) URL to ping every 5 minutes.")


class BulkCreateMonitorItemSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Human-readable name of the monitor.")
    url = serializers.URLField(max_length=2048, help_text="HTTP(S) URL to ping every 5 minutes.")


class BulkCreateMonitorSerializer(serializers.Serializer):
    monitors = BulkCreateMonitorItemSerializer(
        many=True,
        allow_empty=False,
        help_text="List of monitors to create. All-or-nothing: created atomically.",
    )


class SuggestedUrlSerializer(DataclassSerializer):
    class Meta:
        dataclass = SuggestedUrlDTO


class PingSerializer(DataclassSerializer):
    class Meta:
        dataclass = PingDTO
