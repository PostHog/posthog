import pytest

from posthog.persons_db import persons_db_connection

from products.feature_flags.backend.models import FeatureFlagHashKeyOverrideV2

# django_db is what points posthog.persons_db at the migrated test persons database.
pytestmark = [pytest.mark.django_db, pytest.mark.persons_db_direct]

TABLE = FeatureFlagHashKeyOverrideV2._meta.db_table

# Django never emits DDL for this table (the model is unmanaged; rust/persons_migrations owns
# the schema), so nothing else makes the two agree.
PG_TYPE_BY_FIELD_TYPE = {
    "IntegerField": "integer",
    "BigIntegerField": "bigint",
    "CharField": "character varying",
    "DateTimeField": "timestamp with time zone",
}


def _columns() -> dict[str, tuple[str, str]]:
    with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = %s",
            (TABLE,),
        )
        return {name: (data_type, is_nullable) for name, data_type, is_nullable in cursor.fetchall()}


def _index_columns() -> dict[str, list[str]]:
    with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT i.relname, a.attname, k.ord
            FROM pg_index x
            JOIN pg_class i ON i.oid = x.indexrelid
            JOIN pg_class t ON t.oid = x.indrelid
            JOIN LATERAL unnest(x.indkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
            WHERE t.relname = %s
            ORDER BY i.relname, k.ord
            """,
            (TABLE,),
        )
        indexes: dict[str, list[str]] = {}
        for index_name, column_name, _ in cursor.fetchall():
            indexes.setdefault(index_name, []).append(column_name)
        return indexes


def test_model_matches_the_persons_db_table() -> None:
    columns = _columns()

    expected = {
        field.column: (PG_TYPE_BY_FIELD_TYPE[field.get_internal_type()], "NO")
        for field in FeatureFlagHashKeyOverrideV2._meta.fields
        if field.column
    }

    assert columns == expected


def test_primary_key_and_cleanup_index_exist() -> None:
    indexes = _index_columns()

    assert indexes[f"{TABLE}_pkey"] == ["team_id", "person_id", "feature_flag_id"]
    # The access path per-flag cleanup needs, and the reason v2 exists.
    assert ["team_id", "feature_flag_id"] in indexes.values()
