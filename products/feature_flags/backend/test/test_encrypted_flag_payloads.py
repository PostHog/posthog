import pytest

from cryptography.fernet import InvalidToken

from products.feature_flags.backend.encrypted_flag_payloads import FlagPayloadCodec


def test_from_keys_round_trip():
    """from_keys produces an encryptor that round-trips and encrypts with the primary key only."""
    codec = FlagPayloadCodec.from_keys(b"a" * 32, [b"b" * 32])
    payload = b"flag-payload"

    token = codec.encrypt(payload)

    assert codec.decrypt(token) == payload
    # Encryption uses the primary key only: an encryptor holding just the primary key decrypts
    # the token, while one holding only the fallback key cannot.
    assert FlagPayloadCodec.from_keys(b"a" * 32, []).decrypt(token) == payload
    with pytest.raises(InvalidToken):
        FlagPayloadCodec.from_keys(b"b" * 32, []).decrypt(token)


def test_from_keys_decrypts_with_fallback_then_rotates():
    """A token from an old key decrypts via fallback, and rotate() re-encrypts under the new primary key.

    This is the rotation path reencrypt_flag_payloads relies on: keep the old key as a
    fallback, rotate every payload, then the new key alone suffices and the old key can be dropped.
    """
    old = FlagPayloadCodec.from_keys(b"o" * 32, [])
    rotated = FlagPayloadCodec.from_keys(b"n" * 32, [b"o" * 32])

    token = old.encrypt(b"flag-payload")
    assert rotated.decrypt(token) == b"flag-payload"

    new_token = rotated.rotate(token)

    new_only = FlagPayloadCodec.from_keys(b"n" * 32, [])
    assert new_only.decrypt(new_token) == b"flag-payload"
    with pytest.raises(InvalidToken):
        FlagPayloadCodec.from_keys(b"o" * 32, []).decrypt(new_token)


def test_is_encrypted_with_primary():
    """is_encrypted_with_primary is True only when the token decrypts on the primary key alone."""
    rotated = FlagPayloadCodec.from_keys(b"n" * 32, [b"o" * 32])
    old = FlagPayloadCodec.from_keys(b"o" * 32, [])

    on_primary = rotated.encrypt(b"flag-payload")
    on_fallback = old.encrypt(b"flag-payload")

    assert rotated.is_encrypted_with_primary(on_primary) is True
    assert rotated.is_encrypted_with_primary(on_fallback) is False


@pytest.mark.parametrize("require_min_length,raises", [(True, True), (False, False)])
def test_from_keys_min_length_enforcement(require_min_length: bool, raises: bool):
    if raises:
        with pytest.raises(ValueError):
            FlagPayloadCodec.from_keys(b"short", [], require_min_length=require_min_length)
    else:
        FlagPayloadCodec.from_keys(b"short", [], require_min_length=require_min_length)
