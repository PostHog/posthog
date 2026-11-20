from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

import requests
from parameterized import parameterized

from posthog.models import Organization, User

from products.managed_warehouse.backend.facade.contracts import (
    ControlPlaneNotConfiguredError,
    ControlPlaneUnavailableError,
    ControlPlaneUpstreamError,
    QueryNotFoundError,
    WarehouseNotFoundError,
)
from products.managed_warehouse.backend.logic import console_pricing, console_queries, console_usage
from products.managed_warehouse.backend.logic.console_labels import principal_label
from products.managed_warehouse.backend.presentation.hogtower import TranslatedResponse

TIB = console_pricing.TIB
GIB = console_pricing.GIB
_SEND = "products.managed_warehouse.backend.presentation.hogtower._send"

HOGTOWER = override_settings(HOGTOWER_API_URL="http://hogtower.invalid")


def _usage_body(group_by: str, compute: list[dict[str, Any]], storage: list[dict[str, Any]] | None = None) -> dict:
    return {"from": "x", "to": "y", "group_by": group_by, "compute": compute, "storage": storage or []}


def _row(key: str, billable: int = 0, queries: int = 0) -> dict[str, Any]:
    return {
        "key": key,
        "queries": queries,
        "logical_bytes_scanned": billable,
        "billable_bytes": billable,
        "failed_billable_bytes": 0,
        "cpu_seconds": None,
    }


def _fake_usage(by_day: dict, by_breakdown: dict):
    def send(method: str, path: str, **kwargs: Any) -> TranslatedResponse:
        assert path.endswith("/usage")
        body = by_day if kwargs["params"]["group_by"] == "day" else by_breakdown
        return TranslatedResponse(200, body)

    return send


@HOGTOWER
class TestBuildUsageSummary(BaseTest):
    def _build(
        self, by_day: dict, by_breakdown: dict, *, period: str = "last_month", group_by: str = "source", now=None
    ):
        now = now or datetime(2026, 3, 10, 12, tzinfo=UTC)
        with patch(_SEND, side_effect=_fake_usage(by_day, by_breakdown)):
            return console_usage.build_usage_summary(
                str(self.organization.id),
                period=period,
                group_by=group_by,
                now=now,  # type: ignore[arg-type]
            )

    def test_empty_month_is_zero_filled_without_nan(self) -> None:
        summary = self._build(_usage_body("day", []), _usage_body("source", []), period="current_month")

        assert [d.date.day for d in summary.daily] == list(range(1, 11))
        assert all(d.billable_bytes == 0 and d.storage_average_bytes == 0 for d in summary.daily)
        assert summary.total_estimated_cost_usd == 0
        assert summary.forecast_total_usd == 0
        assert summary.breakdown == ()
        assert summary.budget.share_used is None

    def test_february_prices_storage_over_28_days(self) -> None:
        # 200 GiB stored for the whole of February 2026 averages exactly 200 GiB.
        storage = [{"day": f"2026-02-{d:02d}", "byte_seconds": str(200 * GIB * 86400)} for d in range(1, 29)]
        summary = self._build(
            _usage_body("day", [], storage),
            _usage_body("source", []),
            now=datetime(2026, 3, 10, tzinfo=UTC),
        ).storage

        assert summary.gib_months == Decimal(200)
        assert summary.estimated_cost_usd == Decimal("4")
        assert summary.free_gib_months == Decimal(100)

    @parameterized.expand(
        [
            ("january", datetime(2026, 2, 10, tzinfo=UTC), 31, "2026-01-01", "2026-02-01"),
            ("february", datetime(2026, 3, 10, tzinfo=UTC), 28, "2026-02-01", "2026-03-01"),
        ]
    )
    def test_last_month_bounds(self, _name: str, now: datetime, days: int, start: str, end: str) -> None:
        summary = self._build(_usage_body("day", []), _usage_body("source", []), now=now)
        assert len(summary.daily) == days
        assert (summary.period_start.isoformat(), summary.period_end.isoformat()) == (start, end)
        assert summary.forecast_total_usd is None

    def test_no_forecast_before_a_full_day_has_passed(self) -> None:
        summary = self._build(
            _usage_body("day", [_row("2026-03-01", billable=TIB)]),
            _usage_body("source", []),
            period="current_month",
            now=datetime(2026, 3, 1, 12, tzinfo=UTC),
        )
        assert summary.forecast_total_usd is None
        assert summary.total_estimated_cost_usd == 0

    def test_current_month_average_bytes_uses_elapsed_time(self) -> None:
        # 1 GiB stored for the first 10 days of March averages 1 GiB so far, not 1/3 of it.
        storage = [{"day": f"2026-03-{d:02d}", "byte_seconds": str(GIB * 86400)} for d in range(1, 11)]
        summary = self._build(
            _usage_body("day", [], storage),
            _usage_body("source", []),
            period="current_month",
            now=datetime(2026, 3, 11, tzinfo=UTC),
        )
        assert summary.storage.average_bytes == GIB

    def test_storage_average_for_today_divides_by_elapsed_time(self) -> None:
        # 1 GiB held since midnight: 6 h of byte-seconds on a day that is 6 h old averages 1 GiB.
        storage = [
            {"day": "2026-03-09", "byte_seconds": str(GIB * 86400)},
            {"day": "2026-03-10", "byte_seconds": str(GIB * 6 * 3600)},
        ]
        summary = self._build(
            _usage_body("day", [], storage),
            _usage_body("source", []),
            period="current_month",
            now=datetime(2026, 3, 10, 6, tzinfo=UTC),
        )
        assert [d.storage_average_bytes for d in summary.daily[-2:]] == [GIB, GIB]

    def test_storage_average_for_today_has_a_one_hour_floor(self) -> None:
        storage = [{"day": "2026-03-10", "byte_seconds": str(GIB * 600)}]
        summary = self._build(
            _usage_body("day", [], storage),
            _usage_body("source", []),
            period="current_month",
            now=datetime(2026, 3, 10, 0, 10, tzinfo=UTC),
        )
        assert summary.daily[-1].storage_average_bytes == GIB // 6

    @parameterized.expand([("none", None), ("empty", "")])
    def test_team_breakdown_without_a_team_is_unattributed(self, _name: str, key: str | None) -> None:
        rows = [_row("7", 2 * TIB, 1), {**_row("x", TIB, 1), "key": key}]
        summary = self._build(_usage_body("day", []), _usage_body("team", rows), group_by="team")
        assert [r.label for r in summary.breakdown] == ["Project 7", "Unattributed"]

    @parameterized.expand(
        [
            ("breakdown row without key", {"compute": [{"queries": 1}], "storage": []}),
            ("non numeric storage", {"compute": [], "storage": [{"day": "2026-02-01", "byte_seconds": "lots"}]}),
        ]
    )
    def test_malformed_usage_body_is_an_upstream_error(self, _name: str, body: dict) -> None:
        with self.assertRaises(ControlPlaneUpstreamError):
            self._build({**_usage_body("day", []), **body}, _usage_body("source", []))

    def test_last_month_has_every_day_and_no_forecast(self) -> None:
        summary = self._build(_usage_body("day", []), _usage_body("source", []))

        assert len(summary.daily) == 28
        assert summary.forecast_total_usd is None
        assert (summary.period_start.isoformat(), summary.period_end.isoformat()) == ("2026-02-01", "2026-03-01")

    def test_partial_current_month_forecast_scales_month_to_date(self) -> None:
        # Ten days of March (31 days) with 4 TiB billed: the pace is 12.4 TiB for the month.
        now = datetime(2026, 3, 11, tzinfo=UTC)
        by_day = _usage_body("day", [_row("2026-03-02", billable=4 * TIB, queries=3)])
        summary = self._build(by_day, _usage_body("source", []), period="current_month", now=now)

        assert summary.compute.estimated_cost_usd == 0
        assert summary.daily[1].billable_bytes == 4 * TIB
        assert summary.forecast_total_usd is not None
        assert abs(summary.forecast_total_usd - Decimal("21")) < Decimal("0.0001")

    def test_breakdown_labels_share_and_other_row(self) -> None:
        rows = [_row("posthog-sql-editor", 6 * TIB, 5), _row("trino-cli", 2 * TIB, 1)]
        rows += [_row(f"tool-{i}", TIB // 100, 1) for i in range(20)]
        by_day = _usage_body("day", [_row("2026-02-05", billable=8 * TIB + 20 * (TIB // 100))])
        summary = self._build(by_day, _usage_body("source", rows))

        labels = [r.label for r in summary.breakdown]
        assert labels[:2] == ["SQL editor", "trino-cli"]
        assert len(summary.breakdown) == 21
        assert summary.breakdown[-1].key == "other" and summary.breakdown[-1].queries == 2
        total_billable = 8 * TIB + 20 * (TIB // 100)
        assert (
            summary.breakdown[0].estimated_cost_share_usd
            == summary.compute.estimated_cost_usd * 6 * TIB / total_billable
        )

    def test_control_plane_other_row_joins_the_other_row(self) -> None:
        rows = [_row(f"tool-{i}", TIB, 1) for i in range(21)] + [_row("__other__", 3 * TIB, 5)]
        by_day = _usage_body("day", [_row("2026-02-05", billable=24 * TIB)])
        summary = self._build(by_day, _usage_body("source", rows))

        assert [r.key for r in summary.breakdown].count("other") == 1
        assert "__other__" not in [r.key for r in summary.breakdown] + [r.label for r in summary.breakdown]
        other = summary.breakdown[-1]
        assert (other.queries, other.billable_bytes) == (6, 4 * TIB)

    def test_budget_share_used(self) -> None:
        console_usage.update_console_settings(str(self.organization.id), changes={"monthly_budget_usd": Decimal("10")})
        by_day = _usage_body("day", [_row("2026-02-05", billable=6 * TIB)])
        summary = self._build(by_day, _usage_body("source", []))

        assert summary.compute.estimated_cost_usd == Decimal("5")
        assert summary.budget.share_used == Decimal("0.5")


class TestPrincipalLabels(BaseTest):
    def test_only_organization_members_are_resolved(self) -> None:
        member = User.objects.create_user("member@example.com", "pw", "Ada")
        self.organization.members.add(member)
        stranger = User.objects.create_user("stranger@example.com", "pw", "Eve")
        other_org = Organization.objects.create(name="Other")
        other_org.members.add(stranger)

        principals = [
            f"posthog:sql-editor:team:{self.team.pk}:user:{member.pk}",
            f"posthog:sql-editor:team:{self.team.pk}:user:{stranger.pk}",
        ]
        with patch(_SEND, return_value=TranslatedResponse(200, _history(principals))), HOGTOWER:
            page = console_queries.list_query_history(
                str(self.organization.id),
                date_from=None,
                date_to=None,
                principal=None,
                source=None,
                state=None,
                team_id=None,
                limit=None,
                cursor=None,
            )

        assert [r.principal_label for r in page.queries] == ["SQL editor · Ada", "SQL editor"]
        assert page.queries[0].estimated_cost_usd == Decimal("2.5")
        assert page.next_cursor == "c-7"

    @parameterized.expand(
        [
            ("dbt_user", "dbt_user"),
            ("posthog:trino-materialization:team:1:view:abc", "Materialized views · Project 1"),
            ("posthog:materialization:team:1", "Materialized views · Project 1"),
            ("posthog:import:team:2", "Data imports · Project 2"),
            ("posthog:trino-model-aliases:team:3", "PostHog model aliases · Project 3"),
            ("posthog:sql-editor-schema-discovery:team:1", "SQL editor schema discovery · Project 1"),
            ("posthog:something-new", "PostHog"),
        ]
    )
    def test_principal_labels_by_prefix(self, principal: str, expected: str) -> None:
        assert principal_label(principal, {}) == expected

    def test_project_principals_are_named_by_project(self) -> None:
        rows = [
            _row(f"posthog:materialization:team:{self.team.pk}", 2 * TIB, 1),
            _row("posthog:import:team:99999999", TIB, 1),
        ]
        with HOGTOWER, patch(_SEND, side_effect=_fake_usage(_usage_body("day", []), _usage_body("principal", rows))):
            summary = console_usage.build_usage_summary(
                str(self.organization.id),
                period="last_month",
                group_by="principal",
                now=datetime(2026, 3, 10, tzinfo=UTC),
            )
        assert [r.label for r in summary.breakdown] == [
            f"Materialized views · {self.team.name}",
            "Data imports · Project 99999999",
        ]


def _history(principals: list[str]) -> dict:
    return {
        "queries": [
            {
                "id": i,
                "query_id": f"20261120_101500_0000{i}_abcde",
                "principal": p,
                "team_id": 1,
                "source": "posthog-sql-editor",
                "state": "FINISHED",
                "error_code": None,
                "error_type": None,
                "created_at": None,
                "completed_at": "2026-11-20T10:15:01Z",
                "elapsed_ms": None,
                "queued_ms": None,
                "logical_bytes_scanned": TIB,
                "billable": True,
                "cpu_seconds": None,
                "query": "select 1",
            }
            for i, p in enumerate(principals, start=1)
        ],
        "next_cursor": "c-7",
    }


@HOGTOWER
class TestControlPlaneErrors(BaseTest):
    @parameterized.expand(
        [
            ("missing warehouse", 404, WarehouseNotFoundError),
            ("catalog unreachable", 503, ControlPlaneUnavailableError),
            ("server error", 500, ControlPlaneUpstreamError),
        ]
    )
    def test_status_maps_to_facade_error(self, _name: str, status_code: int, error: type[Exception]) -> None:
        with patch(_SEND, return_value=TranslatedResponse(status_code, {"error": "x"})):
            with self.assertRaises(error):
                console_queries.get_storage_overview(str(self.organization.id))

    def test_cancel_404_is_query_not_found(self) -> None:
        with patch(_SEND, return_value=TranslatedResponse(404, {})):
            with self.assertRaises(QueryNotFoundError):
                console_queries.cancel_query(str(self.organization.id), "20261120_101500_00001_abcde")

    def test_transport_failure_is_upstream_error(self) -> None:
        with patch(_SEND, side_effect=requests.ConnectionError("down")):
            with self.assertRaises(ControlPlaneUpstreamError):
                console_queries.get_storage_overview(str(self.organization.id))

    @override_settings(HOGTOWER_API_URL=None)
    def test_unconfigured_control_plane(self) -> None:
        with self.assertRaises(ControlPlaneNotConfiguredError):
            console_queries.get_storage_overview(str(self.organization.id))

    def test_storage_survives_a_failing_maintenance_call(self) -> None:
        def send(method: str, path: str, **kwargs: Any) -> TranslatedResponse:
            if path.endswith("/maintenance"):
                return TranslatedResponse(500, {})
            return TranslatedResponse(
                200, {"tables": [], "total_bytes": 5, "pending_deletion_files": 0, "read_at": None}
            )

        with patch(_SEND, side_effect=send):
            overview = console_queries.get_storage_overview(str(self.organization.id))
        assert overview.maintenance is None and overview.total_bytes == 5
