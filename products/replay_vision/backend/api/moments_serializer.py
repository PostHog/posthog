from rest_framework import serializers

from products.replay_vision.backend.moments import (
    DEFAULT_AFTER_SECONDS,
    DEFAULT_BEFORE_SECONDS,
    MAX_MOMENT_EVENTS,
    MAX_MOMENT_WINDOW_SECONDS,
    MIN_MOMENT_WINDOW_SECONDS,
)


class MomentEventSerializer(serializers.Serializer):
    """Mirrors `moments.MomentEvent` for OpenAPI generation; writes validate via the pydantic model."""

    event = serializers.CharField(
        max_length=400,
        help_text="Event name whose occurrences anchor moments.",
    )
    properties = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text="Property filters the occurrence must also match; standard PostHog property filter shapes.",
    )


class MomentsConfigSerializer(serializers.Serializer):
    """Mirrors `moments.MomentsConfig` for OpenAPI generation; writes validate via the pydantic model."""

    events = MomentEventSerializer(
        many=True,
        help_text=f"Focus events (1-{MAX_MOMENT_EVENTS}); a moment is scanned around each occurrence of any of them.",
    )
    before_seconds = serializers.IntegerField(
        required=False,
        min_value=MIN_MOMENT_WINDOW_SECONDS,
        max_value=MAX_MOMENT_WINDOW_SECONDS,
        help_text=f"Clip seconds included before the focus event. Defaults to {DEFAULT_BEFORE_SECONDS}.",
    )
    after_seconds = serializers.IntegerField(
        required=False,
        min_value=MIN_MOMENT_WINDOW_SECONDS,
        max_value=MAX_MOMENT_WINDOW_SECONDS,
        help_text=f"Clip seconds included after the focus event. Defaults to {DEFAULT_AFTER_SECONDS}.",
    )
