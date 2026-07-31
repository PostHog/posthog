from rest_framework import serializers


class SecureConnectionSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Stable identifier for this connection.")
    name = serializers.CharField(help_text="Name advertised by the connection proxy.")
    connection_type = serializers.CharField(help_text="Type of service exposed by this connection.")
    connection_status = serializers.CharField(help_text="Current status reported by the connection service.")


class SecureConnectionStatusSerializer(serializers.Serializer):
    connection_state = serializers.ChoiceField(
        choices=["not_configured", "waiting", "connected"],
        help_text="Current setup state for this project's secure connection.",
    )
    connections = SecureConnectionSerializer(
        many=True,
        help_text="Services currently advertised through the secure connection.",
    )


class SecureConnectionEnrollmentSerializer(serializers.Serializer):
    enrollment_key = serializers.CharField(help_text="One-time response credential used to enroll a connection proxy.")
    advertisement_token = serializers.CharField(
        help_text="Tenant-scoped credential used by the proxy to report its available services."
    )
    tenant_id = serializers.UUIDField(help_text="Tenant identifier used by the connection proxy.")
    control_url = serializers.URLField(help_text="Control server URL used by the connection proxy.")


class SecureConnectionTestSerializer(serializers.Serializer):
    success = serializers.BooleanField(help_text="Whether at least one active connection was found.")
    detail = serializers.CharField(help_text="Result of the connection check.")
