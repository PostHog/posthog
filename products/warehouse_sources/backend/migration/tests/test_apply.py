from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_management import SourceSchema
from products.warehouse_sources.backend.migration.apply import build_planned_schemas
from products.warehouse_sources.backend.migration.types import ItemProposal, ProposedRowFilter, ProposedSchema
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType


def _proposal(*schemas: ProposedSchema, **overrides: Any) -> ItemProposal:
    fields: dict[str, Any] = {
        "source_type": ExternalDataSourceType.POSTGRES,
        "prefix": "app_db",
        "prefill": {},
        "schemas": schemas,
        "sync_frequency": "6hour",
        "sync_time_of_day": None,
        "destination": None,
        **overrides,
    }
    return ItemProposal(**fields)


def _table(name: str, webhook_only: bool = False) -> SourceSchema:
    return SourceSchema(
        name=name,
        webhook_only=webhook_only,
        supports_incremental=True,
        supports_append=True,
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        columns=[("id", "integer", False), ("card_number", "text", True), ("updated_at", "timestamp", True)],
        detected_primary_keys=["id"],
    )


class TestBuildPlannedSchemas(SimpleTestCase):
    def test_overlays_the_plan_on_posthog_defaults(self) -> None:
        proposal = _proposal(
            ProposedSchema(
                name="public.orders",
                should_sync=True,
                sync_type=None,
                disabled_columns=("card_number",),
                row_filters=(
                    ProposedRowFilter(column="status", operator="=", values=("ACTIVE",)),
                    ProposedRowFilter(column="region", operator="IN", values=("eu", "us")),
                ),
            ),
            ProposedSchema(name="public.gone", should_sync=True, sync_type=None),
            ProposedSchema(name="public.locked", should_sync=True, sync_type=None),
        )
        tables = [_table("public.orders"), _table("public.audit_log"), _table("public.locked")]

        planned = build_planned_schemas(proposal, tables, {"public.locked": "permission denied"})

        orders, audit_log, locked = planned.schemas
        assert orders == {
            "name": "public.orders",
            "should_sync": True,
            "sync_type": "incremental",
            "incremental_field": "updated_at",
            "incremental_field_type": "datetime",
            "primary_key_columns": ["id"],
            "enabled_columns": ["id", "updated_at"],
            "row_filters": [
                {"column": "status", "operator": "=", "value": "ACTIVE"},
                {"column": "region", "operator": "IN", "value": ["eu", "us"]},
            ],
        }
        assert audit_log == {"name": "public.audit_log", "should_sync": False}
        assert locked == {"name": "public.locked", "should_sync": False}
        assert planned.unavailable == ("public.gone", "public.locked")

    @parameterized.expand(
        [
            ("no_table_list_uses_posthog_defaults", _proposal(schemas=None), True),
            ("nothing_moves", _proposal(), False),
            (
                "paused",
                _proposal(ProposedSchema(name="public.orders", should_sync=True, sync_type=None), start_paused=True),
                False,
            ),
        ]
    )
    def test_whole_source_decisions(self, _name: str, proposal: ItemProposal, syncs: bool) -> None:
        planned = build_planned_schemas(proposal, [_table("public.orders")], {})
        assert planned.schemas[0]["should_sync"] is syncs
        assert planned.unavailable == ()
        assert bool(planned.planned) == syncs

    def test_matches_alternative_names_and_reports_webhook_only_tables(self) -> None:
        proposal = _proposal(
            ProposedSchema(name="public.orders", should_sync=True, sync_type=None, alternative_names=("orders",)),
            ProposedSchema(name="events", should_sync=True, sync_type=None),
            sync_time_of_day="03:30:00",
        )

        planned = build_planned_schemas(proposal, [_table("orders"), _table("events", webhook_only=True)], {})

        orders, events = planned.schemas
        assert (orders["name"], orders["should_sync"], orders["sync_time_of_day"]) == ("orders", True, "03:30:00")
        assert events == {"name": "events", "should_sync": False}
        assert (planned.unavailable, planned.webhook_only, planned.planned) == ((), ("events",), ("orders", "events"))
