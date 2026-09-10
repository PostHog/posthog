from rest_framework import serializers


class PulseResearchRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        max_length=500,
        help_text="A public-web research query. It is searched once and only public results are considered.",
    )


class PulseResearchCitationSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stable citation ID for this research call.")
    url = serializers.URLField(help_text="Validated public URL returned by the provider.")
    title = serializers.CharField(help_text="Bounded page title.")
    excerpt = serializers.CharField(help_text="Bounded extracted page evidence.")


class PulseResearchResponseSerializer(serializers.Serializer):
    citations = PulseResearchCitationSerializer(many=True, help_text="At most three bounded public citations.")
    degradation = serializers.ChoiceField(
        choices=["not_configured", "busy", "unavailable"],
        allow_null=True,
        required=False,
        help_text="Why public research was unavailable, when it could not run.",
    )
