import dataclasses
from collections.abc import Collection, Iterable, Mapping
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
from products.warehouse_sources.backend.models.util import validate_source_prefix
from products.warehouse_sources.backend.types import ExternalDataSourceType


@frozen
class _Tables:
    names: frozenset[str]
    complete: bool = True


@frozen
class _TableMatch:
    vendor_table: str
    posthog_table: str | None
    confidence: str | None


class _Catalog:
    """Implements the catalog Protocol: exact means equal ignoring case, and `inferred` lists the rule pairs."""

    def __init__(self, hubspot_tables: _Tables | None, inferred: Mapping[str, str] | None = None) -> None:
        self._tables = {ExternalDataSourceType.HUBSPOT: hubspot_tables, ExternalDataSourceType.POSTGRES: None}
        self._inferred = inferred or {}

    def match_source(self, provider: str, vendor_service: str) -> ExternalDataSourceType | None:
        return {"hubspot": ExternalDataSourceType.HUBSPOT, "postgres": ExternalDataSourceType.POSTGRES}.get(
            vendor_service
        )

    def match_destination(self, provider: str, vendor_service: str) -> str | None:
        return {"snowflake": "Snowflake"}.get(vendor_service)

    def posthog_tables(self, source_type: ExternalDataSourceType) -> _Tables | None:
        return self._tables[source_type]

    def match_tables(
        self, provider: str, vendor_tables: Iterable[str], posthog_table_names: Collection[str]
    ) -> tuple[_TableMatch, ...]:
        vendor_tables = list(vendor_tables)
        by_lower = {name.lower(): name for name in posthog_table_names}
        exact_targets = {by_lower[t.lower()] for t in vendor_tables if t.lower() in by_lower}
        matches = []
        for table in vendor_tables:
            inferred = self._inferred.get(table)
            if table.lower() in by_lower:
                matches.append(
                    _TableMatch(vendor_table=table, posthog_table=by_lower[table.lower()], confidence="exact")
                )
            elif inferred in posthog_table_names and inferred not in exact_targets:
                matches.append(_TableMatch(vendor_table=table, posthog_table=inferred, confidence="inferred"))
            else:
                matches.append(_TableMatch(vendor_table=table, posthog_table=None, confidence=None))
        return tuple(matches)

    def prefill_config(
        self, provider: str, source_type: ExternalDataSourceType, vendor_config: Mapping[str, Any]
    ) -> dict[str, Any]:
        keys = {"host": "host", "user": "user", "tunnel_host": "ssh_tunnel.host"}
        return {keys[key]: value for key, value in vendor_config.items() if key in keys}


_HUBSPOT_TABLES = _Tables(names=frozenset({"contacts", "deals"}))


def _caps(**overrides: Any) -> SourceCapabilities:
    return dataclasses.replace(
        SourceCapabilities(
            release_status=ReleaseStatus.GA,
            unreleased=False,
            supports_column_selection=True,
            supports_row_filters=False,
        ),
        **overrides,
    )


_TEAM_FLAGS = frozenset({"flag-the-team-has"})
_DATABASE_CAPS = _caps(supports_row_filters=True, toggle_groups=frozenset({"ssh_tunnel"}))


def _table(name: str = "contacts", **overrides: Any) -> VendorTable:
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


def _plan_all(
    connections: tuple[VendorConnection, ...],
    caps: SourceCapabilities | None = None,
    destinations: tuple[VendorDestination, ...] = (),
    catalog: _Catalog | None = None,
) -> tuple[PlannedItem, ...]:
    snapshot = VendorSnapshot(
        provider=MigrationProvider.FIVETRAN,
        account_id="acct_example",
        account_name=None,
        destinations=destinations,
        connections=connections,
    )
    return plan_items(
        snapshot,
        catalog or _Catalog(_HUBSPOT_TABLES),
        lambda _source_type: caps or _caps(),
        flag_enabled=_TEAM_FLAGS.__contains__,
    )


def _plan(
    connection: VendorConnection,
    caps: SourceCapabilities | None = None,
    destinations: tuple[VendorDestination, ...] = (),
    catalog: _Catalog | None = None,
) -> PlannedItem:
    (item,) = _plan_all((connection,), caps, destinations, catalog)
    return item


class TestVerdict(SimpleTestCase):
    def test_clean_connection_moves_as_is(self) -> None:
        item = _plan(_connection(tables=(_table("contacts"), _table("deals"), _table("tickets", enabled=False))))

        assert item.verdict == Verdict.AS_IS
        assert item.caveats == ()
        assert item.proposal is not None
        assert item.proposal.source_type == ExternalDataSourceType.HUBSPOT
        assert item.proposal.prefix == "hubspot_main"
        assert item.proposal.schemas is not None
        assert [schema.name for schema in item.proposal.schemas] == ["contacts", "deals"]
        assert item.proposal.sync_frequency == "6hour"

    def test_prefixes_are_valid_and_unique_per_source_type(self) -> None:
        first, second, numbered, digit_first = _plan_all(
            (
                _connection(name="hubspot"),
                _connection(id="conn_staging", name="hubspot"),
                _connection(id="conn_other", name="hubspot_2"),
                _connection(name="3PL Orders"),
            )
        )

        assert first.proposal and second.proposal and numbered.proposal and digit_first.proposal
        # `hubspot_2` belongs to another connection, so the repeat skips it.
        assert (first.proposal.prefix, second.proposal.prefix, numbered.proposal.prefix) == (
            "hubspot",
            "hubspot_3",
            "hubspot_2",
        )
        assert any("`hubspot_3`" in caveat for caveat in second.caveats), second.caveats
        assert validate_source_prefix(digit_first.proposal.prefix) == (True, "")

    @parameterized.expand(
        [
            ("no_posthog_source", _connection(service="unknown_vendor"), _caps()),
            ("posthog_source_unreleased", _connection(), _caps(unreleased=True)),
            (
                "team_lacks_the_source_flag",
                _connection(),
                _caps(feature_flags=frozenset({"flag-the-team-has", "flag-the-team-lacks"})),
            ),
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
            ("empty_table_list", _connection(tables=()), _caps(), "default tables"),
        ]
    )
    def test_caveat(self, _name: str, connection: VendorConnection, caps: SourceCapabilities, expected: str) -> None:
        item = _plan(connection, caps)
        assert item.verdict == Verdict.CAVEATS
        assert any(expected in caveat for caveat in item.caveats), item.caveats


class TestTables(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "unmatched_table_is_returned",
                ("contacts", "email_event"),
                _HUBSPOT_TABLES,
                ["contacts"],
                (),
                ("email_event",),
                ("deals",),
                "not planned",
            ),
            (
                "inferred_pair_is_planned_and_marked",
                ("contact", "deals"),
                _HUBSPOT_TABLES,
                ["contacts", "deals"],
                (("contact", "contacts"),),
                (),
                (),
                "naming rule",
            ),
            # An exact match takes the table, so the inferred pair does not apply.
            (
                "exact_match_wins_over_a_rule",
                ("contact", "contacts"),
                _HUBSPOT_TABLES,
                ["contacts"],
                (),
                ("contact",),
                ("deals",),
                "not planned",
            ),
            (
                "two_tables_one_posthog_table",
                ("Contacts", "contacts"),
                _HUBSPOT_TABLES,
                ["contacts"],
                (),
                # Listed, so the user can choose it over the other table.
                ("contacts",),
                ("deals",),
                "same PostHog table",
            ),
            (
                "nothing_moves",
                ("email_event",),
                _HUBSPOT_TABLES,
                [],
                (),
                ("email_event",),
                ("contacts", "deals"),
                "every table starts with syncing off",
            ),
            # The source discovers more tables than it lists, so apply checks this name against discovery.
            (
                "partial_list_keeps_the_vendor_name",
                ("contacts", "users"),
                _Tables(names=frozenset({"contacts"}), complete=False),
                ["contacts", "users"],
                (),
                (),
                (),
                None,
            ),
        ]
    )
    def test_tables_that_cannot_move_are_reported_not_dropped_silently(
        self,
        _name: str,
        tables: tuple[str, ...],
        known: _Tables,
        expected: list[str],
        inferred: tuple[tuple[str, str], ...],
        unmatched: tuple[str, ...],
        unused: tuple[str, ...],
        expected_caveat: str | None,
    ) -> None:
        catalog = _Catalog(known, inferred={"contact": "contacts"})
        item = _plan(_connection(tables=tuple(_table(name) for name in tables)), catalog=catalog)
        assert item.proposal is not None and item.proposal.schemas is not None
        assert [schema.name for schema in item.proposal.schemas] == expected
        assert [(pair.vendor_table, pair.posthog_table) for pair in item.proposal.inferred_tables] == list(inferred)
        assert item.proposal.unmatched_tables == unmatched
        assert item.proposal.unused_posthog_tables == unused
        if expected_caveat:
            assert any(expected_caveat in caveat for caveat in item.caveats), item.caveats
        else:
            assert item.caveats == ()

    def test_database_tables_are_schema_qualified_and_config_is_prefilled(self) -> None:
        connection = _connection(
            service="postgres",
            config={"host": "db.example.com", "user": "reader", "port": 5432, "tunnel_host": "bastion.example.com"},
            tables=(
                _table("orders", schema_name="public"),
                _table("events", schema_name="analytics"),
                _table("events", schema_name="public"),
            ),
        )
        item = _plan(connection, _DATABASE_CAPS)
        assert item.proposal is not None and item.proposal.schemas is not None
        # Both `events` tables keep only their qualified names, so apply cannot map them to one bare table.
        assert [(schema.name, schema.alternative_names) for schema in item.proposal.schemas] == [
            ("public.orders", ("orders",)),
            ("analytics.events", ()),
            ("public.events", ()),
        ]
        assert any("`events`" in caveat for caveat in item.caveats), item.caveats
        assert item.proposal.prefill == {
            "host": "db.example.com",
            "user": "reader",
            "ssh_tunnel": {"host": "bastion.example.com", "enabled": True},
        }

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
        assert item.proposal is not None and item.proposal.schemas is not None
        assert item.proposal.schemas[0].disabled_columns == expected_disabled
        if expected_caveat:
            assert any(expected_caveat in caveat for caveat in item.caveats)
        else:
            assert item.caveats == ()

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
        assert item.proposal is not None and item.proposal.schemas is not None
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
            ("several_values_for_one_value_operator", _DATABASE_CAPS, _row_filter(("a", "EQUALS", ("1", "2"))), ()),
            ("source_cannot_filter", _caps(), _row_filter(("status", "EQUALS", ("ACTIVE",))), ()),
            (
                "column_not_filterable_on_this_table",
                _caps(supports_row_filters=True, row_filter_columns={"public.orders": frozenset({"created_at"})}),
                _row_filter(("status", "EQUALS", ("ACTIVE",))),
                (),
            ),
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
        assert item.proposal is not None and item.proposal.schemas is not None
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
            ("manual", VendorSchedule(kind=ScheduleKind.MANUAL), "6hour", None, True),
            (
                "unknown_interval",
                VendorSchedule(kind=ScheduleKind.INTERVAL, interval_minutes=None),
                "6hour",
                None,
                True,
            ),
            ("cron_hour_step", VendorSchedule(kind=ScheduleKind.CRON, cron="0 */12 * * *"), "12hour", None, True),
            ("cron_daily", VendorSchedule(kind=ScheduleKind.CRON, cron="30 4 * * *"), "24hour", None, True),
            ("cron_weekdays", VendorSchedule(kind=ScheduleKind.CRON, cron="30 4 * * 1-5"), "24hour", None, True),
            ("cron_weekly", VendorSchedule(kind=ScheduleKind.CRON, cron="30 4 * * 1"), "7day", None, True),
            ("cron_monthly", VendorSchedule(kind=ScheduleKind.CRON, cron="30 4 1 * *"), "30day", None, True),
            ("cron_every_minute", VendorSchedule(kind=ScheduleKind.CRON, cron="* * * * *"), "5min", None, True),
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

    @parameterized.expand(
        [
            ("paused", _connection(paused=True), True),
            ("manual", _connection(schedule=VendorSchedule(kind=ScheduleKind.MANUAL)), True),
            ("running", _connection(), False),
        ]
    )
    def test_paused_or_manual_connection_starts_paused(
        self, _name: str, connection: VendorConnection, start_paused: bool
    ) -> None:
        item = _plan(connection)
        assert item.proposal is not None
        assert item.proposal.start_paused == start_paused
        assert item.proposal.sync_frequency == "6hour"


class TestDestination(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "supported",
                "snowflake",
                ProposedDestination(type="Snowflake", config={"database": "ANALYTICS"}),
                None,
            ),
            ("unsupported", "oracle_warehouse", None, "PostHog warehouse"),
        ]
    )
    def test_destination(
        self, _name: str, service: str, expected: ProposedDestination | None, expected_caveat: str | None
    ) -> None:
        destination = VendorDestination(
            id="grp_example", name="Warehouse", service=service, region=None, config={"database": "ANALYTICS"}
        )
        item = _plan(_connection(destination_id="grp_example"), destinations=(destination,))
        assert item.proposal is not None
        assert item.proposal.destination == expected
        if expected_caveat:
            assert any(expected_caveat in caveat for caveat in item.caveats)
        else:
            assert item.caveats == ()
