import dataclasses
from collections.abc import Mapping
from typing import Any, Literal

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.source_config import ReleaseStatus
from products.warehouse_sources.backend.migration.fivetran.planner import PlannedItem, plan_items
from products.warehouse_sources.backend.migration.types import (
    MigrationProvider,
    ProposedDestination,
    ProposedRowFilter,
    ScheduleKind,
    SourceCapabilities,
    VendorColumn,
    VendorConnection,
    VendorDestination,
    VendorRowFilter,
    VendorRowFilterClause,
    VendorSchedule,
    VendorSnapshot,
    VendorTable,
    Verdict,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@frozen
class _Match:
    source_type: ExternalDataSourceType
    table_aliases: Mapping[str, str] = dataclasses.field(default_factory=dict)
    config_keys: Mapping[str, str] = dataclasses.field(default_factory=dict)
    notes: tuple[str, ...] = ()


class _Catalog:
    def __init__(self, sources: Mapping[str, _Match], destinations: Mapping[str, str] | None = None) -> None:
        self._sources = sources
        self._destinations = destinations or {}

    def match_source(self, provider: str, vendor_service: str) -> _Match | None:
        return self._sources.get(vendor_service)

    def match_destination(self, provider: str, vendor_service: str) -> str | None:
        return self._destinations.get(vendor_service)


_HUBSPOT = _Match(source_type=ExternalDataSourceType.HUBSPOT, table_aliases={"contact": "contacts"})
_POSTGRES = _Match(source_type=ExternalDataSourceType.POSTGRES, config_keys={"host": "host", "user": "user"})
_CATALOG = _Catalog({"hubspot": _HUBSPOT, "postgres": _POSTGRES}, {"snowflake": "Snowflake"})


def _caps(**overrides: Any) -> SourceCapabilities:
    return dataclasses.replace(
        SourceCapabilities(
            release_status=ReleaseStatus.GA,
            unreleased=False,
            documented_tables=frozenset({"contacts", "deals"}),
            supports_column_selection=True,
            supports_row_filters=False,
        ),
        **overrides,
    )


_DATABASE_CAPS = _caps(documented_tables=None, supports_row_filters=True)


def _table(name: str = "contact", **overrides: Any) -> VendorTable:
    return dataclasses.replace(
        VendorTable(schema_name="hubspot", name=name, enabled=True, sync_mode=None, columns=(), row_filter=None),
        **overrides,
    )


def _connection(**overrides: Any) -> VendorConnection:
    return dataclasses.replace(
        VendorConnection(
            id="conn_example",
            service="hubspot",
            name="Hubspot-Main",
            destination_id=None,
            paused=False,
            schedule=VendorSchedule(kind=ScheduleKind.INTERVAL, interval_minutes=360),
            setup_state="connected",
            succeeded_at=None,
            networking_method="Directly",
            config={},
            schema_change_handling="ALLOW_ALL",
            tables_available=True,
            tables=(_table(),),
        ),
        **overrides,
    )


def _plan(
    connection: VendorConnection,
    caps: SourceCapabilities | None = None,
    destinations: tuple[VendorDestination, ...] = (),
) -> PlannedItem:
    snapshot = VendorSnapshot(
        provider=MigrationProvider.FIVETRAN,
        account_id="acct_example",
        account_name=None,
        destinations=destinations,
        connections=(connection,),
    )
    (item,) = plan_items(snapshot, _CATALOG, lambda _source_type: caps or _caps())
    return item


class TestVerdict(SimpleTestCase):
    def test_clean_connection_moves_as_is(self) -> None:
        item = _plan(_connection(tables=(_table("contact"), _table("deals"), _table("tickets", enabled=False))))

        assert item.verdict == Verdict.AS_IS
        assert item.caveats == ()
        assert item.proposal is not None
        assert item.proposal.source_type == ExternalDataSourceType.HUBSPOT
        assert item.proposal.prefix == "hubspot_main"
        assert [schema.name for schema in item.proposal.schemas] == ["contacts", "deals"]
        assert item.proposal.sync_frequency == "6hour"

    @parameterized.expand(
        [
            ("no_posthog_source", _connection(service="unknown_vendor"), _caps()),
            ("posthog_source_unreleased", _connection(), _caps(unreleased=True)),
        ]
    )
    def test_unsupported(self, _name: str, connection: VendorConnection, caps: SourceCapabilities) -> None:
        item = _plan(connection, caps)
        assert item.verdict == Verdict.UNSUPPORTED
        assert item.proposal is None
        assert len(item.caveats) == 1

    @parameterized.expand(
        [
            ("alpha_source", _connection(), _caps(release_status=ReleaseStatus.ALPHA), "alpha"),
            ("broken_setup", _connection(setup_state="broken"), _caps(), "`broken`"),
            ("private_link", _connection(networking_method="PrivateLink"), _caps(), "PrivateLink"),
            ("change_log", _connection(config={"update_method": "WAL_PGOUTPUT"}), _caps(), "change log"),
            ("blocked_schema_changes", _connection(schema_change_handling="BLOCK_ALL"), _caps(), "blocks new tables"),
            ("no_table_list", _connection(tables_available=False, tables=()), _caps(), "default tables"),
        ]
    )
    def test_caveat(self, _name: str, connection: VendorConnection, caps: SourceCapabilities, expected: str) -> None:
        item = _plan(connection, caps)
        assert item.verdict == Verdict.CAVEATS
        assert any(expected in caveat for caveat in item.caveats), item.caveats


class TestTables(SimpleTestCase):
    def test_table_without_posthog_equivalent_is_reported_not_dropped_silently(self) -> None:
        item = _plan(_connection(tables=(_table("contact"), _table("email_event"))))
        assert item.proposal is not None
        assert [schema.name for schema in item.proposal.schemas] == ["contacts"]
        assert any("`email_event`" in caveat for caveat in item.caveats)

    def test_database_tables_are_schema_qualified_and_config_is_prefilled(self) -> None:
        connection = _connection(
            service="postgres",
            config={"host": "db.example.com", "user": "reader", "port": 5432},
            tables=(_table("orders", schema_name="public"), _table("events", schema_name="analytics")),
        )
        item = _plan(connection, _DATABASE_CAPS)
        assert item.proposal is not None
        assert [schema.name for schema in item.proposal.schemas] == ["public.orders", "analytics.events"]
        assert item.proposal.prefill == {"host": "db.example.com", "user": "reader"}

    @parameterized.expand(
        [
            (
                "columns_selected",
                _caps(),
                ("card_number",),
                None,
            ),
            (
                "column_selection_unsupported",
                _caps(supports_column_selection=False),
                (),
                "syncs every column",
            ),
        ]
    )
    def test_disabled_columns(
        self, _name: str, caps: SourceCapabilities, expected_disabled: tuple[str, ...], expected_caveat: str | None
    ) -> None:
        columns = (
            VendorColumn(name="card_number", enabled=False, hashed=False, is_primary_key=False),
            VendorColumn(name="id", enabled=True, hashed=False, is_primary_key=True),
        )
        item = _plan(_connection(tables=(_table(columns=columns),)), caps)
        assert item.proposal is not None
        assert item.proposal.schemas[0].disabled_columns == expected_disabled
        assert any(expected_caveat in caveat for caveat in item.caveats) if expected_caveat else item.caveats == ()

    @parameterized.expand(
        [
            ("history_mode", {"sync_mode": "HISTORY"}, "keeps history"),
            (
                "hashed_column",
                {"columns": (VendorColumn(name="email", enabled=True, hashed=True, is_primary_key=False),)},
                "unhashed",
            ),
        ]
    )
    def test_table_feature_without_equivalent(self, _name: str, overrides: dict[str, Any], expected: str) -> None:
        item = _plan(_connection(tables=(_table(**overrides),)))
        assert item.proposal is not None
        assert len(item.proposal.schemas) == 1
        assert any(expected in caveat for caveat in item.caveats)


def _row_filter(
    *clauses: tuple[str, str, tuple[str, ...]], combinator: Literal["AND", "OR"] = "AND"
) -> VendorRowFilter:
    return VendorRowFilter(
        combinator=combinator,
        clauses=tuple(VendorRowFilterClause(column=c, operator=o, values=v) for c, o, v in clauses),
    )


class TestRowFilters(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "mapped",
                _DATABASE_CAPS,
                _row_filter(("status", "EQUALS", ("ACTIVE",)), ("region", "IN", ("eu", "us"))),
                (
                    ProposedRowFilter(column="status", operator="=", values=("ACTIVE",)),
                    ProposedRowFilter(column="region", operator="IN", values=("eu", "us")),
                ),
            ),
            (
                "or_combinator",
                _DATABASE_CAPS,
                _row_filter(("a", "EQUALS", ("1",)), ("b", "EQUALS", ("2",)), combinator="OR"),
                (),
            ),
            ("operator_without_equivalent", _DATABASE_CAPS, _row_filter(("name", "CONTAINS", ("x",))), ()),
            ("source_cannot_filter", _caps(documented_tables=None), _row_filter(("status", "EQUALS", ("ACTIVE",))), ()),
        ]
    )
    def test_row_filter(
        self,
        _name: str,
        caps: SourceCapabilities,
        row_filter: VendorRowFilter,
        expected: tuple[ProposedRowFilter, ...],
    ) -> None:
        connection = _connection(
            service="postgres", tables=(_table("orders", schema_name="public", row_filter=row_filter),)
        )
        item = _plan(connection, caps)
        assert item.proposal is not None
        assert item.proposal.schemas[0].row_filters == expected
        assert any("row filter" in caveat for caveat in item.caveats) == (expected == ())


class TestFrequency(SimpleTestCase):
    @parameterized.expand(
        [
            ("exact_interval", VendorSchedule(kind=ScheduleKind.INTERVAL, interval_minutes=15), "15min", None, False),
            (
                "one_minute_rounds_up",
                VendorSchedule(kind=ScheduleKind.INTERVAL, interval_minutes=1),
                "5min",
                None,
                True,
            ),
            (
                "three_hours_rounds_down",
                VendorSchedule(kind=ScheduleKind.INTERVAL, interval_minutes=180),
                "1hour",
                None,
                True,
            ),
            (
                "daily_with_time",
                VendorSchedule(kind=ScheduleKind.INTERVAL, interval_minutes=1440, time_of_day_utc="14:00"),
                "24hour",
                "14:00:00",
                False,
            ),
            (
                "time_of_day",
                VendorSchedule(kind=ScheduleKind.TIME_OF_DAY, time_of_day_utc="03:30"),
                "24hour",
                "03:30:00",
                False,
            ),
            ("manual", VendorSchedule(kind=ScheduleKind.MANUAL), "never", None, True),
            (
                "unknown_interval",
                VendorSchedule(kind=ScheduleKind.INTERVAL, interval_minutes=None),
                "6hour",
                None,
                True,
            ),
            ("cron_hour_step", VendorSchedule(kind=ScheduleKind.CRON, cron="0 */12 * * *"), "12hour", None, True),
            ("cron_daily", VendorSchedule(kind=ScheduleKind.CRON, cron="30 4 * * *"), "24hour", None, True),
            (
                "some_weekdays",
                VendorSchedule(kind=ScheduleKind.INTERVAL, interval_minutes=60, days_of_week=("MONDAY",)),
                "1hour",
                None,
                True,
            ),
        ]
    )
    def test_schedule(
        self, _name: str, schedule: VendorSchedule, frequency: str, time_of_day: str | None, has_caveat: bool
    ) -> None:
        item = _plan(_connection(schedule=schedule))
        assert item.proposal is not None
        assert (item.proposal.sync_frequency, item.proposal.sync_time_of_day) == (frequency, time_of_day)
        assert bool(item.caveats) == has_caveat, item.caveats

    def test_paused_connection_is_created_with_syncing_off(self) -> None:
        item = _plan(_connection(paused=True))
        assert item.proposal is not None
        assert item.proposal.sync_frequency == "never"


class TestDestination(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "supported",
                "snowflake",
                ProposedDestination(type="Snowflake", config={"database": "ANALYTICS"}),
                "different schema",
            ),
            ("unsupported", "oracle_warehouse", None, "PostHog warehouse"),
        ]
    )
    def test_destination(
        self, _name: str, service: str, expected: ProposedDestination | None, expected_caveat: str
    ) -> None:
        destination = VendorDestination(
            id="grp_example", name="Warehouse", service=service, region=None, config={"database": "ANALYTICS"}
        )
        item = _plan(_connection(destination_id="grp_example"), destinations=(destination,))
        assert item.proposal is not None
        assert item.proposal.destination == expected
        assert any(expected_caveat in caveat for caveat in item.caveats)
