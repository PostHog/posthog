from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_management import SourceSchema
from products.warehouse_sources.backend.migration.apply import (
    TableOverride,
    TableOverrideError,
    build_planned_schemas,
    with_table_overrides,
)
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


def _table(name: str, webhook_only: bool = False, source_schema: str | None = None) -> SourceSchema:
    return SourceSchema(
        name=name,
        webhook_only=webhook_only,
        source_schema=source_schema,
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
            # Discovery read schema `public`, so the bare `users` and `orders` are not this schema's tables.
            ProposedSchema(name="sales.users", should_sync=True, sync_type=None, alternative_names=("users",)),
            ProposedSchema(name="sales.orders", should_sync=True, sync_type=None, alternative_names=("orders",)),
            ProposedSchema(name="events", should_sync=True, sync_type=None),
            sync_time_of_day="03:30:00",
        )
        discovered = [
            _table("orders", source_schema="public"),
            _table("users", source_schema="public"),
            _table("events", webhook_only=True),
        ]

        planned = build_planned_schemas(proposal, discovered, {})

        orders, users, events = planned.schemas
        assert (orders["name"], orders["should_sync"], orders["sync_time_of_day"]) == ("orders", True, "03:30:00")
        assert users == {"name": "users", "should_sync": False}
        assert events == {"name": "events", "should_sync": False}
        assert (planned.unavailable, planned.webhook_only, planned.planned) == (
            ("sales.users", "sales.orders"),
            ("events",),
            ("orders", "events"),
        )


_CONTACTS = ProposedSchema(name="contacts", should_sync=True, sync_type=None, vendor_table="contact")
_DEALS = ProposedSchema(name="deals", should_sync=True, sync_type=None, vendor_table="deals")


class TestTableOverrides(SimpleTestCase):
    @parameterized.expand(
        [
            ("rename_an_inferred_pair", [("contact", "contact_list")], ["contact_list", "deals"]),
            ("map_an_unmatched_table", [("email_event", "email_events")], ["contacts", "deals", "email_events"]),
            ("leave_a_table_out", [("deals", None)], ["contacts"]),
            ("swap_two_names", [("contact", "deals"), ("deals", "contacts")], ["deals", "contacts"]),
        ]
    )
    def test_overrides_change_the_plan(
        self, _name: str, overrides: list[tuple[str, str | None]], expected: list[str]
    ) -> None:
        proposal = _proposal(_CONTACTS, _DEALS, unmatched_tables=("email_event",))

        result = with_table_overrides(proposal, [TableOverride(vendor_table=v, posthog_table=p) for v, p in overrides])

        assert result.schemas is not None
        assert [schema.name for schema in result.schemas] == expected

    @parameterized.expand(
        [
            ("unknown_vendor_table", (_CONTACTS,), [("not_a_table", "x")], "not a Fivetran table"),
            ("two_tables_one_name", (_CONTACTS, _DEALS), [("deals", "contacts")], "maps to `contacts`"),
            ("default_tables_plan", None, [("contact", "x")], "default tables"),
        ]
    )
    def test_overrides_that_do_not_fit_are_refused(
        self,
        _name: str,
        schemas: tuple[ProposedSchema, ...] | None,
        overrides: list[tuple[str, str | None]],
        message: str,
    ) -> None:
        proposal = _proposal(*(schemas or ()), schemas=schemas)
        with self.assertRaisesRegex(TableOverrideError, message):
            with_table_overrides(proposal, [TableOverride(vendor_table=v, posthog_table=p) for v, p in overrides])
