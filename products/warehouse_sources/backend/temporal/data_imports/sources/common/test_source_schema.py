from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    _select_incremental_field,
    build_default_schemas,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _field(name: str, field_type: IncrementalFieldType = IncrementalFieldType.DateTime) -> IncrementalField:
    return {"label": name, "type": field_type, "field": name, "field_type": field_type, "nullable": False}


class TestSelectIncrementalField:
    @parameterized.expand(
        [
            ("empty", [], None),
            ("single", ["created_at"], "created_at"),
            ("prefers_updated_at", ["created_at", "updated_at", "id"], "updated_at"),
            ("prefers_modified_over_created", ["created_at", "modified_at"], "modified_at"),
            ("updated_beats_modified", ["modified_at", "updated_at"], "updated_at"),
            ("falls_back_to_first_when_no_known", ["id", "seq"], "id"),
            ("case_insensitive", ["CreatedAt", "UpdatedAt"], "UpdatedAt"),
        ]
    )
    def test_selection(self, _name: str, field_names: list[str], expected: str | None) -> None:
        chosen = _select_incremental_field([_field(n) for n in field_names])
        assert (chosen["field"] if chosen else None) == expected


class TestBuildDefaultSchemas:
    def test_incremental_when_supported_with_field(self) -> None:
        schemas = build_default_schemas(
            [
                SourceSchema(
                    name="orders",
                    supports_incremental=True,
                    supports_append=True,
                    incremental_fields=[_field("created_at"), _field("updated_at")],
                    detected_primary_keys=["id"],
                )
            ]
        )
        assert schemas == [
            {
                "name": "orders",
                "should_sync": True,
                "sync_type": "incremental",
                "incremental_field": "updated_at",
                "incremental_field_type": "datetime",
                "primary_key_columns": ["id"],
            }
        ]

    def test_append_when_only_append_supported(self) -> None:
        schemas = build_default_schemas(
            [
                SourceSchema(
                    name="events",
                    supports_incremental=False,
                    supports_append=True,
                    incremental_fields=[_field("created_at")],
                )
            ]
        )
        assert schemas[0]["sync_type"] == "append"
        assert schemas[0]["incremental_field"] == "created_at"
        assert "primary_key_columns" not in schemas[0]

    @parameterized.expand(
        [
            ("no_incremental_support", False, False, []),
            ("incremental_support_but_no_field", True, True, []),
        ]
    )
    def test_full_refresh_fallback(
        self, _name: str, supports_incremental: bool, supports_append: bool, fields: list
    ) -> None:
        schemas = build_default_schemas(
            [
                SourceSchema(
                    name="dim_table",
                    supports_incremental=supports_incremental,
                    supports_append=supports_append,
                    incremental_fields=fields,
                )
            ]
        )
        assert schemas[0] == {"name": "dim_table", "should_sync": True, "sync_type": "full_refresh"}

    def test_webhook_only_table_left_disabled(self) -> None:
        schemas = build_default_schemas(
            [
                SourceSchema(
                    name="discounts",
                    supports_incremental=False,
                    supports_append=False,
                    supports_webhooks=True,
                    webhook_only=True,
                )
            ]
        )
        assert schemas == [{"name": "discounts", "should_sync": False}]

    def test_default_off_table_left_disabled(self) -> None:
        # A source marks a table should_sync_default=False when syncing it needs grants beyond
        # what source creation validated (e.g. GitHub org tables). One-shot setup force-enabling
        # it would make the first sync fail; it must start disabled like the picker leaves it.
        schemas = build_default_schemas(
            [
                SourceSchema(
                    name="teams",
                    supports_incremental=False,
                    supports_append=False,
                    should_sync_default=False,
                )
            ]
        )
        assert schemas == [{"name": "teams", "should_sync": False}]

    def test_never_defaults_to_cdc(self) -> None:
        schemas = build_default_schemas(
            [
                SourceSchema(
                    name="orders",
                    supports_incremental=True,
                    supports_append=True,
                    supports_cdc=True,
                    incremental_fields=[_field("updated_at")],
                    detected_primary_keys=["id"],
                )
            ]
        )
        assert schemas[0]["sync_type"] == "incremental"

    def test_enables_all_discovered_tables(self) -> None:
        source_schemas = [
            SourceSchema(
                name="a", supports_incremental=True, supports_append=True, incremental_fields=[_field("updated_at")]
            ),
            SourceSchema(name="b", supports_incremental=False, supports_append=False),
            SourceSchema(
                name="c", supports_incremental=False, supports_append=True, incremental_fields=[_field("created_at")]
            ),
        ]
        schemas = build_default_schemas(source_schemas)
        assert [s["name"] for s in schemas] == ["a", "b", "c"]
        assert all(s["should_sync"] for s in schemas)
