import base64
from collections.abc import Iterable

from django.conf import settings

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from posthog.auth import PersonalAPIKeyAuthentication

REDACTED_PAYLOAD_VALUE = '"********* (encrypted)"'


def _prepare_key(key: str | bytes) -> bytes:
    """Derive a Fernet key from raw key material.

    Pads (left, with NUL bytes) or truncates the input to the 32 bytes Fernet requires,
    then URL-safe base64-encodes it. The input is raw key material, not an already-encoded key.
    """
    key_bytes = key.encode() if isinstance(key, str) else key
    return base64.urlsafe_b64encode((b"\0" * max(32 - len(key_bytes), 0) + key_bytes)[:32])


class FlagPayloadCodec:
    """Symmetric Fernet encryption for feature flag payloads, with key rotation.

    A thin wrapper over ``MultiFernet``: the primary key encrypts new payloads while
    fallback keys decrypt older ones, so the keys in ``FLAGS_SECRET_KEYS`` can rotate
    without a hard cutover. Deliberately independent of Temporal's ``EncryptionCodec`` —
    flag payloads have their own key lifecycle (``FLAGS_SECRET_KEYS``) and need none of
    the Temporal ``PayloadCodec`` machinery (async ``encode``/``decode``, protobuf
    ``Payload``).
    """

    def __init__(self, primary: Fernet, fallbacks: Iterable[Fernet]) -> None:
        self.primary = primary
        self.fernet = MultiFernet([primary, *fallbacks])

    @classmethod
    def from_keys(
        cls,
        key: str | bytes,
        fallback_keys: Iterable[str | bytes],
        *,
        require_min_length: bool = True,
    ) -> "FlagPayloadCodec":
        """Build a codec from raw key material.

        Keys are padded or truncated to 32 bytes and base64-encoded as Fernet requires.
        The first key encrypts new payloads; fallback keys are only tried when decryption
        with the primary key fails — keeping old keys as fallbacks is what makes key
        rotation possible without a hard cutover.

        Args:
            key: The preferred encryption key.
            fallback_keys: Additional keys tried only when decrypting with key fails.
            require_min_length: When True, raise if any key is shorter than 32 bytes.
                Disable only in TEST or DEBUG, where short keys are padded.

        Raises:
            ValueError: If require_min_length is True and any key is under 32 bytes.
        """
        fallbacks = list(fallback_keys)
        if require_min_length and any(len(k if isinstance(k, bytes) else k.encode()) < 32 for k in (key, *fallbacks)):
            raise ValueError("Keys must be at least 32 bytes")
        return cls(Fernet(_prepare_key(key)), [Fernet(_prepare_key(k)) for k in fallbacks])

    def encrypt(self, data: bytes) -> bytes:
        return self.fernet.encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        return self.fernet.decrypt(data)

    def rotate(self, data: bytes) -> bytes:
        """Re-encrypt a token onto the primary key, decrypting it with any known key first."""
        return self.fernet.rotate(data)

    def is_encrypted_with_primary(self, data: bytes) -> bool:
        """Return True if data decrypts with the primary key alone (no fallback needed).

        Lets callers skip re-encrypting tokens already on the current key:
        ``MultiFernet.rotate`` emits fresh ciphertext regardless of which key a token
        is on, so without this check a re-encryption pass rewrites every row on rerun.
        """
        try:
            self.primary.decrypt(data)
        except InvalidToken:
            return False
        return True


def flag_payload_codec() -> FlagPayloadCodec:
    # FLAGS_SECRET_KEYS is ordered and always non-empty: the first key encrypts,
    # the rest are decrypt-only fallbacks.
    keys = settings.FLAGS_SECRET_KEYS
    return FlagPayloadCodec.from_keys(
        keys[0],
        keys[1:],
        require_min_length=not settings.TEST and not settings.DEBUG,
    )


def get_decrypted_flag_payloads_protected(request, encrypted_payloads: dict) -> dict:
    # We only decode encrypted flag payloads if the request is made with a personal API key
    is_personal_api_request = isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication)
    return get_decrypted_flag_payloads(encrypted_payloads, should_decrypt=is_personal_api_request)


def get_decrypted_flag_payloads(encrypted_payloads: dict, should_decrypt: bool) -> dict:
    # Build the codec once and share it across every payload rather than rebuilding
    # it per entry. When redacting we never decrypt, so skip building it at all.
    codec = flag_payload_codec() if should_decrypt else None
    return {
        key: get_decrypted_flag_payload(value, should_decrypt=should_decrypt, codec=codec)
        for key, value in (encrypted_payloads or {}).items()
    }


def get_decrypted_flag_payload(
    encrypted_payload: str | object, should_decrypt: bool, codec: FlagPayloadCodec | None = None
) -> str:
    if not should_decrypt:
        return REDACTED_PAYLOAD_VALUE
    codec = codec or flag_payload_codec()
    return codec.decrypt(str(encrypted_payload).encode("utf-8")).decode("utf-8")


def encrypt_flag_payloads(validated_data: dict):
    if not validated_data.get("has_encrypted_payloads", False):
        return

    if "filters" not in validated_data:
        return

    if "payloads" not in validated_data["filters"]:
        return

    payloads = validated_data["filters"]["payloads"]

    codec = flag_payload_codec()

    for key, value in payloads.items():
        try:
            payloads[key] = codec.encrypt(value.encode("utf-8")).decode("utf-8")
        except Exception as e:
            raise ValueError(f"Failed to encrypt payload for key {key}") from e
