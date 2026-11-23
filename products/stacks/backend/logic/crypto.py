"""Encryption at rest for stack records and saved diffs, on the dedicated `STACKS_ENCRYPTION_KEYS`."""

from __future__ import annotations

import zlib

from django.conf import settings

from cryptography.fernet import Fernet, MultiFernet

from ..db import WRITER_DB
from ..models import StackDiff, StackRecordVersion, StackSecret


class StackKeysMissing(RuntimeError):
    pass


def _fernet() -> MultiFernet:
    keys = [key for key in settings.STACKS_ENCRYPTION_KEYS if key]
    if not keys:
        raise StackKeysMissing("STACKS_ENCRYPTION_KEYS is not set")
    return MultiFernet([Fernet(key.encode()) for key in keys])


def keys_ready() -> bool:
    """At least one key, and every key a valid Fernet key, so a typo fails readiness and never a write."""
    keys = [key for key in settings.STACKS_ENCRYPTION_KEYS if key]
    if not keys:
        return False
    try:
        for key in keys:
            Fernet(key.encode())
    except (ValueError, TypeError):
        return False
    return True


def encrypt(data: bytes) -> bytes:
    # Records are JSON and can be megabytes, so they compress well before encryption.
    return _fernet().encrypt(zlib.compress(data))


def decrypt(token: bytes | memoryview) -> bytes:
    return zlib.decompress(_fernet().decrypt(bytes(token)))


def rotate(token: bytes | memoryview) -> bytes:
    """Re-encrypt a token onto the primary key."""
    return _fernet().rotate(bytes(token))


def reencrypt_all() -> int:
    """Re-wrap every stored record, saved diff, description and secret onto the primary key.

    Each update is conditional on the bytes it read, so a row that a push cleared or rewrote meanwhile keeps
    the newer value.
    """
    rewritten = 0
    for model, field in (
        (StackRecordVersion, "encrypted_record"),
        (StackDiff, "encrypted_saved_diff"),
        (StackDiff, "encrypted_description"),
        (StackSecret, "encrypted_value"),
    ):
        manager = model.all_teams.using(WRITER_DB)
        for row_id, token in manager.exclude(**{field: None}).values_list("id", field).iterator():
            rewritten += manager.filter(id=row_id, **{field: bytes(token)}).update(**{field: rotate(token)})
    return rewritten
