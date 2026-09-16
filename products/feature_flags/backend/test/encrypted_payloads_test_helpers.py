from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.db import connection

from products.feature_flags.backend.models.feature_flag import ENCRYPTED_PAYLOADS_CONSTRAINT, FeatureFlag


@contextmanager
def encrypted_payloads_constraint_dropped() -> Iterator[None]:
    """Drop encrypted_payloads_require_remote_config, then restore it NOT VALID.

    Migration 0021 adds the constraint NOT VALID, so a row written before it survives with
    has_encrypted_payloads true and is_remote_configuration false or NULL. The constraint
    rejects that shape, so a test that needs such a row builds it in here.
    pg_get_constraintdef reads the live definition, so the restored constraint cannot drift
    from the migration.
    """
    with connection.cursor() as cursor:
        _flush_deferred_constraint_triggers(cursor)
        cursor.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
            [ENCRYPTED_PAYLOADS_CONSTRAINT],
        )
        definition = cursor.fetchone()[0]
        cursor.execute(f"ALTER TABLE posthog_featureflag DROP CONSTRAINT {ENCRYPTED_PAYLOADS_CONSTRAINT}")
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            _flush_deferred_constraint_triggers(cursor)
            cursor.execute(
                f"ALTER TABLE posthog_featureflag ADD CONSTRAINT {ENCRYPTED_PAYLOADS_CONSTRAINT} {definition} NOT VALID"
            )


def create_pre_constraint_encrypted_flag(**kwargs: Any) -> FeatureFlag:
    """Create an encrypted flag whose is_remote_configuration the constraint would reject."""
    with encrypted_payloads_constraint_dropped():
        return FeatureFlag.objects.create(has_encrypted_payloads=True, **kwargs)


def _flush_deferred_constraint_triggers(cursor: Any) -> None:
    # Postgres refuses to alter a table with the pending trigger events fixture inserts queue.
    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
