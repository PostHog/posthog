import pytest

from django.test import override_settings

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.masking import (
    mask_table_columns,
    mask_value,
    resolve_masked_columns,
)


class TestMaskValue:
    def test_deterministic_across_calls(self):
        # The whole point: a rerun must reproduce the digest, or PK merges duplicate every sync.
        assert mask_value(1, "4111111111111111") == mask_value(1, "4111111111111111")

    def test_scoped_per_team(self):
        # Drop team_id from the message and two teams' equal values collide — a tenant-isolation break.
        assert mask_value(1, "a@x.com") != mask_value(2, "a@x.com")

    def test_distinct_values_differ(self):
        assert mask_value(1, "a") != mask_value(1, "b")

    def test_null_passthrough(self):
        # Hashing null would turn every NULL into one constant digest, destroying nullability.
        assert mask_value(1, None) is None

    def test_fails_closed_without_key(self):
        # A refactor that fails open here would silently write unkeyed (brute-forceable) digests
        # on any deployment with the setting unset.
        with override_settings(ENCRYPTION_SALT_KEYS=[]):
            with pytest.raises(ValueError):
                mask_value(1, "secret")

    @parameterized.expand([("str", "secret"), ("int", 42), ("float", 3.14)])
    def test_one_way_hex_digest(self, _name, value):
        digest = mask_value(7, value)
        assert digest is not None and len(digest) == 64 and digest != str(value)


class TestResolveMaskedColumns:
    def test_excludes_pk_and_incremental(self):
        assert resolve_masked_columns(["a", "b", "c"], primary_keys=["a"], incremental_field="b") == {"c"}

    def test_excludes_pk_case_insensitively(self):
        # A cased mask entry must still protect a PK stored in a different case, or the CDC/pipeline
        # paths would hash the merge key and corrupt UPDATE/DELETE processing.
        assert resolve_masked_columns(["ID", "Email"], primary_keys=["id"]) == {"email"}

    def test_empty_when_unset(self):
        assert resolve_masked_columns(None) == set()


class TestMaskTableColumns:
    def _table(self) -> pa.Table:
        return pa.table({"id": [1, 2], "email": ["a@x.com", "b@x.com"], "name": ["A", "B"]})

    def test_masks_only_listed_columns_as_strings(self):
        table = mask_table_columns(self._table(), ["email"], team_id=3)
        assert table.column("email").to_pylist() == [mask_value(3, "a@x.com"), mask_value(3, "b@x.com")]
        assert table.schema.field("email").type == pa.string()
        assert table.column("name").to_pylist() == ["A", "B"]
        assert table.column("id").to_pylist() == [1, 2]

    def test_none_config_is_identity(self):
        original = self._table()
        assert mask_table_columns(original, None, team_id=3) is original

    def test_protected_columns_never_masked(self):
        # Masking the PK / cursor would corrupt merges and incremental advancement.
        table = mask_table_columns(
            self._table(), ["id", "name", "email"], team_id=3, primary_keys=["id"], incremental_field="name"
        )
        assert table.column("id").to_pylist() == [1, 2]
        assert table.column("name").to_pylist() == ["A", "B"]
        assert table.column("email").to_pylist() == [mask_value(3, "a@x.com"), mask_value(3, "b@x.com")]

    def test_matches_source_name_after_normalization(self):
        # Config holds source-style "Email"; the table column is already normalized to "email".
        table = mask_table_columns(self._table(), ["Email"], team_id=3)
        assert table.column("email").to_pylist() == [mask_value(3, "a@x.com"), mask_value(3, "b@x.com")]
