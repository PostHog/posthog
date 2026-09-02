from rest_framework import serializers


class ErrorTrackingRuleReorderRequestSerializer(serializers.Serializer):
    orders = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Mapping from rule ID to its new evaluation order.",
    )
