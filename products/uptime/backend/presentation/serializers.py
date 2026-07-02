from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import DailyBucketDTO, MonitorDTO, MonitorSummaryDTO, OutageDTO, PingDTO


class MonitorSerializer(DataclassSerializer):
    class Meta:
        dataclass = MonitorDTO


class DailyBucketSerializer(DataclassSerializer):
    class Meta:
        dataclass = DailyBucketDTO


class MonitorSummarySerializer(DataclassSerializer):
    class Meta:
        dataclass = MonitorSummaryDTO


class PingSerializer(DataclassSerializer):
    class Meta:
        dataclass = PingDTO


class OutageSerializer(DataclassSerializer):
    class Meta:
        dataclass = OutageDTO


class CreateMonitorSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Human-readable name of the monitor.")
    url = serializers.URLField(max_length=2048, help_text="HTTP(S) URL to ping every 5 minutes.")


class UpdateMonitorSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False, help_text="New human-readable name of the monitor.")
    url = serializers.URLField(max_length=2048, required=False, help_text="New HTTP(S) URL to ping.")
