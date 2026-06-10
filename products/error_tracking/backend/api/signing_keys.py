import base64
import hashlib

import structlog
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingSigningKey

logger = structlog.get_logger(__name__)


def derive_key_id(public_key_raw: bytes) -> str:
    """Stable short fingerprint of a raw 32-byte Ed25519 public key.

    Must match the SDK's derivation (posthog-python exception_signing.derive_key_id) so a
    signature's key id resolves to the stored key: base64url(sha256(raw_pubkey))[:16].
    """
    digest = hashlib.sha256(public_key_raw).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")[:16]


def _validate_ed25519_public_key_pem(pem: str) -> bytes:
    """Parse a PEM Ed25519 public key and return its raw 32 bytes; raise on anything else."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        key = serialization.load_pem_public_key(pem.encode("utf-8"))
    except Exception as e:
        raise serializers.ValidationError("Could not parse a PEM public key.") from e
    if not isinstance(key, Ed25519PublicKey):
        raise serializers.ValidationError("Public key must be an Ed25519 key.")
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


class ErrorTrackingSigningKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingSigningKey
        fields = ["id", "key_id", "public_key", "label", "revoked", "created_at", "last_used_at"]
        # key_id is derived server-side; public_key is write-once at creation.
        read_only_fields = ["id", "key_id", "created_at", "last_used_at"]

    def get_fields(self):
        fields = super().get_fields()
        # The key itself is immutable: make public_key read-only on update so DRF skips both its
        # validation and population, instead of silently accepting then dropping it.
        if self.instance is not None:
            fields["public_key"].read_only = True
        return fields

    def validate_public_key(self, value: str) -> str:
        # Validate once and stash the raw bytes for create() to derive the key_id from.
        self._public_key_raw = _validate_ed25519_public_key_pem(value)
        return value

    def create(self, validated_data):
        validated_data["key_id"] = derive_key_id(self._public_key_raw)
        validated_data["team_id"] = self.context["get_team"]().id
        request = self.context.get("request")
        if request is not None and getattr(request, "user", None) and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        return super().create(validated_data)


class ErrorTrackingSigningKeyViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingSigningKey.objects.all()
    serializer_class = ErrorTrackingSigningKeySerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id).order_by("-created_at")
