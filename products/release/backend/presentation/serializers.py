"""DRF serializers for release."""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import ReleaseDTO


class ReleaseSerializer(DataclassSerializer):
    class Meta:
        dataclass = ReleaseDTO


class WriteReleaseSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, help_text="Name of the feature.")
    description = serializers.CharField(
        allow_blank=True, required=False, help_text="What the feature does for the people who get it."
    )
    owner_id = serializers.IntegerField(
        allow_null=True, required=False, help_text="ID of the user who owns the release of this feature."
    )
    feature_flag_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="IDs of the feature flags that gate this feature.",
    )
