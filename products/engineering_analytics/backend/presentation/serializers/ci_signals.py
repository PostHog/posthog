"""Payloads for the atomic CI Signals configuration endpoint."""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from products.engineering_analytics.backend.facade.contracts import CISignalsConfig


class CISignalsConfigSerializer(DataclassSerializer):
    class Meta:
        dataclass = CISignalsConfig
        extra_kwargs = {
            "configured": {"help_text": "Whether this project has ever configured CI signals."},
            "enabled": {"help_text": "Whether every CI signal detector is enabled."},
            "sync_status": {
                "help_text": "Aggregate sync status for pull requests, workflow runs, and workflow jobs.",
                "allow_null": True,
            },
        }


class CISignalsConfigUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(help_text="Enable or disable every CI signal detector atomically.")
