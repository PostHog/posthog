from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import MonitorDTO, PingDTO


class MonitorSerializer(DataclassSerializer):
    class Meta:
        dataclass = MonitorDTO


class CreateMonitorSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Human-readable name of the monitor.")
    url = serializers.URLField(max_length=2048, help_text="HTTP(S) URL to ping every 5 minutes.")


class PingSerializer(DataclassSerializer):
    class Meta:
        dataclass = PingDTO
