from rest_framework import serializers


class ReplayVisionErrorSerializer(serializers.Serializer):
    """The shape every Replay Vision error response uses, so generated clients read one key."""

    detail = serializers.CharField(help_text="Human-readable explanation of why the request was refused.")
