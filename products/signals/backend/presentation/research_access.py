from rest_framework import serializers

from products.signals.backend.facade.enums import ResearchAccessMode


class ResearchAccessSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=ResearchAccessMode.choices, help_text="Research available to this project.")
    blocker = serializers.CharField(
        allow_null=True, help_text="Machine-readable prerequisite preventing research, or null when research can run."
    )
