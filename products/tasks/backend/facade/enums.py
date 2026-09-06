"""Public choice sets for the tasks product's request serializers.

Kept in the facade so the OpenAPI enum-name override in ``posthog/settings/web.py`` can
point at a stable public path (never an internal module)."""

# The channel types a client may create. A subset of ``Channel.ChannelType`` — personal
# #me spaces are provisioned, never created through the write path — so it needs its own
# enum name to avoid colliding with other ``channel_type`` fields.
CHANNEL_WRITE_TYPE_CHOICES: list[str] = ["public", "private"]
