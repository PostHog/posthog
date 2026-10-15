from types import SimpleNamespace
from typing import Any, cast

import pytest

from django.test import override_settings

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.masking import (
    ambiguous_masked_columns,
    mask_table_columns,
    mask_table_if_configured,
    mask_value,
    resolve_masked_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException


class TestMaskValue:
    @parameterized.expand(
        [
            ("same_team_same_value", (1, "a@example.com"), (1, "a@example.com"), True),
            ("other_team", (1, "a@example.com"), (2, "a@example.com"), False),
            ("other_value", (1, "a@example.com"), (1, "b@example.com"), False),
        ]
    )
    def test_digest_equality(self, _name: str, left: tuple[int, str], right: tuple[int, str], equal: bool) -> None:
        assert (mask_value(*left) == mask_value(*right)) is equal

    def test_null_stays_null(self) -> None:
        assert mask_value(1, None) is None

    def test_digest_depends_on_the_server_secret(self) -> None:
        with override_settings(ENCRYPTION_SALT_KEYS=["a" * 32]):
            first = mask_value(1, "secret")
        with override_settings(ENCRYPTION_SALT_KEYS=["b" * 32]):
            second = mask_value(1, "secret")
        assert first != second

    @parameterized.expand(
        [
            ("no_key", [], False),
            ("public_default_key_outside_development", ["00beef0000beef0000beef0000beef00"], False),
            ("public_default_key_in_development", ["00beef0000beef0000beef0000beef00"], True),
        ]
    )
    def test_key_checks(self, _name: str, keys: list[str], debug: bool) -> None:
        with override_settings(ENCRYPTION_SALT_KEYS=keys, DEBUG=debug, TEST=False):
            if debug:
                assert mask_value(1, "secret") is not None
            else:
                with pytest.raises(NonRetryableException):
                    mask_value(1, "secret")


class TestResolveMaskedColumns:
    @parameterized.expand(
        [
            ("drops_key_and_cursor", ["a", "b", "c"], ["a"], "b", {"c"}),
            ("folds_case_before_matching_the_key", ["ID", "Email"], ["id"], None, {"email"}),
            ("unset", None, ["id"], None, set()),
        ]
    )
    def test_resolve(
        self,
        _name: str,
        masked: list[str] | None,
        primary_keys: list[str],
        incremental_field: str | None,
        expected: set[str],
    ) -> None:
        assert resolve_masked_columns(masked, primary_keys, incremental_field) == expected


class TestAmbiguousMaskedColumns:
    @parameterized.expand(
        [
            ("collision", ["Email"], ["email", "Email", "id"], ["Email"]),
            ("no_collision", ["email"], ["email", "id", "name"], []),
        ]
    )
    def test_ambiguous(self, _name: str, masked: list[str], source_columns: list[str], expected: list[str]) -> None:
        assert ambiguous_masked_columns(masked, source_columns) == expected


class TestMaskTableColumns:
    def _table(self) -> pa.Table:
        return pa.table({"id": [1, 2], "email": ["a@example.com", None], "visits": [7, 8]})

    def test_masks_listed_columns_as_strings_and_leaves_the_rest(self) -> None:
        # "Visits" is the source casing of a column the pipeline already normalized.
        table = mask_table_columns(self._table(), ["email", "Visits"], team_id=3)

        assert table.column("email").to_pylist() == [mask_value(3, "a@example.com"), None]
        assert table.column("visits").to_pylist() == [mask_value(3, 7), mask_value(3, 8)]
        assert table.schema.field("visits").type == pa.string()
        assert table.column("id").to_pylist() == [1, 2]

    def test_key_and_cursor_are_never_masked(self) -> None:
        table = mask_table_columns(
            self._table(), ["id", "visits", "email"], team_id=3, primary_keys=["id"], incremental_field="visits"
        )

        assert table.column("id").to_pylist() == [1, 2]
        assert table.column("visits").to_pylist() == [7, 8]
        assert table.column("email").to_pylist() == [mask_value(3, "a@example.com"), None]


class TestMaskTableIfConfigured:
    @pytest.mark.parametrize(
        "masked,source_column_names",
        [
            pytest.param(["id"], ["id", "email"], id="mask_on_a_key_resolved_at_sync_time"),
            pytest.param(["Email"], ["id", "Email", "email"], id="source_column_added_with_a_colliding_name"),
        ],
    )
    async def test_fails_the_sync(self, masked: list[str], source_column_names: list[str]) -> None:
        schema = cast(Any, SimpleNamespace(masked_columns=masked, incremental_field=None, team_id=3))
        resource = cast(Any, SimpleNamespace(primary_keys=["id"]))

        with pytest.raises(NonRetryableException):
            await mask_table_if_configured(pa.table({"id": [1]}), schema, resource, source_column_names)
