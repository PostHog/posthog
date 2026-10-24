from django.test import SimpleTestCase

from products.warehouse_sources.backend.facade.source_management import SourceSchema
from products.warehouse_sources.backend.migration.apply import build_planned_schemas
from products.warehouse_sources.backend.migration.types import ItemProposal, ProposedRowFilter, ProposedSchema
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType


def _proposal(*schemas: ProposedSchema) -> ItemProposal:
    return ItemProposal(
        source_type=ExternalDataSourceType.POSTGRES,
        prefix="app_db",
        prefill={},
        schemas=schemas,
        sync_frequency="6hour",
        sync_time_of_day=None,
        destination=None,
    )


def _table(name: str) -> SourceSchema:
    return SourceSchema(
        name=name,
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

    def test_no_table_list_uses_posthog_defaults(self) -> None:
        planned = build_planned_schemas(_proposal(), [_table("public.orders")], {})
        assert planned.schemas[0]["should_sync"] is True
        assert planned.unavailable == ()
