from rest_framework import serializers


class ImageSizeSerializer(serializers.Serializer):
    width = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=320,
        max_value=4000,
        help_text="Output width in pixels, from 320 to 4000. Omit or use null for automatic width.",
    )
    height = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=200,
        max_value=5000,
        help_text="Output height in pixels, from 200 to 5000. Omit or use null for automatic height. "
        "Content fits inside the requested size without stretching or cropping.",
    )
