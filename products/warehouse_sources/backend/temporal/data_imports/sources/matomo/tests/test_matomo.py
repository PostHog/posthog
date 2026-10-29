from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.matomo import MatomoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.matomo.matomo import (
    VISITS_PAGE_SIZE,
    MatomoResumeConfig,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.matomo.settings import (
    REPORT_LOOKBACK_DAYS,
    VISIT_FINALITY_WINDOW_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.matomo.source import MatomoSource


def _driver() -> SourceDriver:
    return SourceDriver(
        MatomoSource(), MatomoSourceConfig(host="https://m.example.com", site_id="1", api_token="token")
    )


def _final_ts(offset_seconds: int = 0) -> int:
    # A timestamp safely older than the finality window.
    return int(datetime.now(tz=UTC).timestamp()) - VISIT_FINALITY_WINDOW_SECONDS - 100 - offset_seconds


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://myorg.matomo.cloud", "https://myorg.matomo.cloud"),
            ("myorg.matomo.cloud", "https://myorg.matomo.cloud"),
            ("https://analytics.example.com/", "https://analytics.example.com"),
            ("http://analytics.internal:8080", "http://analytics.internal:8080"),
        ],
    )
    def test_valid_hosts(self, value: str, expected: str) -> None:
        assert normalize_host(value) == expected

    @pytest.mark.parametrize("value", ["", "   ", "ftp://example.com", "https://"])
    def test_invalid_hosts_raise(self, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_host(value)


class TestValidateCredentials:
    def test_error_envelope_fails_validation(self) -> None:
        with scripted_network([ScriptedResponse(json={"result": "error", "message": "bad token"})]) as network:
            assert validate_credentials("https://myorg.matomo.cloud", "1", "bad") is False

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/index.php"
        assert parse_qs((network.requests_log[0].body or b"").decode())["token_auth"] == ["bad"]


class TestVisits:
    def test_full_page_at_one_timestamp_steps_past_cursor(self) -> None:
        # minTimestamp is inclusive, so a full page whose visits all share the
        # same second must step the cursor forward or it would refetch forever.
        ts = _final_ts(10_000)
        first_page = [{"idVisit": str(i), "serverTimestamp": ts} for i in range(VISITS_PAGE_SIZE)]
        second_page = [{"idVisit": "last", "serverTimestamp": ts + 5}]
        result = _driver().run(
            "visits",
            [ScriptedResponse(json=first_page), ScriptedResponse(json=second_page)]
            + [ScriptedResponse(json=[]) for _ in range(10)],
            incremental_field="serverTimestamp",
            db_incremental_field_last_value=ts - 60,
        )

        assert result.raised is None
        assert [len(batch) for batch in result.items] == [VISITS_PAGE_SIZE, 1]
        assert parse_qs((result.requests[1].body or b"").decode())["minTimestamp"] == [str(ts + 1)]

    def test_still_active_visits_are_deferred(self) -> None:
        now = int(datetime.now(tz=UTC).timestamp())
        result = _driver().run(
            "visits",
            [
                ScriptedResponse(
                    json=[
                        {"idVisit": "done", "serverTimestamp": _final_ts()},
                        {"idVisit": "active", "serverTimestamp": now - 10},
                    ]
                ),
                *[ScriptedResponse(json=[]) for _ in range(4)],
            ],
            incremental_field="serverTimestamp",
            db_incremental_field_last_value=now,
        )

        assert result.raised is None
        assert {row["idVisit"] for row in result.rows} == {"done"}

    def test_resume_day_restarts_the_walk_where_it_stopped(self) -> None:
        today = datetime.now(tz=UTC).date()
        result = _driver().run(
            "visits",
            [ScriptedResponse(json=[])],
            resume_state=MatomoResumeConfig(min_timestamp=1, next_date=today.isoformat()),
        )

        assert result.raised is None
        assert len(result.requests) == 1
        assert parse_qs((result.requests[0].body or b"").decode())["date"] == [today.isoformat()]


class TestReports:
    def test_walks_days_oldest_first_and_injects_date(self) -> None:
        result = _driver().run(
            "visits_summary",
            [ScriptedResponse(json={"nb_visits": 5}) for _ in range(REPORT_LOOKBACK_DAYS + 1)],
            incremental_field="_date",
            db_incremental_field_last_value=datetime.now(tz=UTC).date().isoformat(),
        )

        # Lookback window: REPORT_LOOKBACK_DAYS + 1 days, one row per day.
        assert result.raised is None
        assert len(result.items) == REPORT_LOOKBACK_DAYS + 1
        dates = [batch[0]["_date"] for batch in result.items]
        assert dates == sorted(dates)
        assert all(batch[0]["nb_visits"] == 5 for batch in result.items)
        first_body = parse_qs((result.requests[0].body or b"").decode())
        assert first_body["period"] == ["day"]
        assert first_body["method"] == ["VisitsSummary.get"]

    def test_list_reports_yield_rows_per_day(self) -> None:
        result = _driver().run(
            "referrers",
            [ScriptedResponse(json=[{"label": "Direct"}, {"label": "Search"}])] * (REPORT_LOOKBACK_DAYS + 1),
            incremental_field="_date",
            db_incremental_field_last_value=datetime.now(tz=UTC).date().isoformat(),
        )

        assert result.raised is None
        assert all(len(batch) == 2 for batch in result.items)
        assert all("_date" in row for row in result.rows)

    def test_api_error_envelope_raises(self) -> None:
        result = _driver().run(
            "visits_summary",
            [ScriptedResponse(json={"result": "error", "message": "no access"})],
            resume_state=MatomoResumeConfig(next_date=datetime.now(tz=UTC).date().isoformat()),
        )

        assert isinstance(result.raised, ValueError)
        assert "no access" in str(result.raised)


class TestDrivenEndpoints:
    @pytest.mark.parametrize(
        "endpoint,method,expected_flat",
        [
            # Without flat=1 page URLs come back as folder rows whose pages hide in subtables.
            ("pages", "Actions.getPageUrls", ["1"]),
            ("event_names", "Events.getName", None),
        ],
    )
    def test_report_request_params(self, endpoint: str, method: str, expected_flat: list[str] | None) -> None:
        today = datetime.now(tz=UTC).date().isoformat()

        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=[{"label": "/pricing"}])],
            resume_state=MatomoResumeConfig(next_date=today),
        )

        assert result.raised is None
        assert result.rows == [{"label": "/pricing", "_date": today}]
        [request] = result.requests
        body = parse_qs((request.body or b"").decode())
        assert (body["method"], body["period"], body["date"], body["filter_limit"]) == (
            [method],
            ["day"],
            [today],
            ["-1"],
        )
        assert body.get("flat") == expected_flat

    @pytest.mark.parametrize(
        "goals",
        [
            [{"idgoal": 1, "name": "Signup"}, {"idgoal": 2, "name": "Purchase"}],
            # Older Matomo releases key the goals by id instead of returning a list.
            {"1": {"idgoal": "1", "name": "Signup"}, "2": {"idgoal": "2", "name": "Purchase"}},
        ],
    )
    def test_goals_fetched_in_one_undated_call(self, goals: Any) -> None:
        result = _driver().run("goals", [ScriptedResponse(json=goals)])

        assert result.raised is None
        assert [row["name"] for row in result.rows] == ["Signup", "Purchase"]
        [request] = result.requests
        body = parse_qs((request.body or b"").decode())
        assert body["method"] == ["Goals.getGoals"]
        assert "period" not in body and "date" not in body


class TestMatomoSourceResponse:
    @pytest.mark.parametrize(
        "endpoint,expected_mode,expected_keys,expected_format",
        [
            # visits' primary key idVisit is an incrementing int, so it must ship an explicit
            # datetime scheme — otherwise the pipeline buckets one Delta partition per visit.
            ("visits", "datetime", ["serverTimestamp"], "month"),
            ("visits_summary", None, None, None),
            ("referrers", None, None, None),
        ],
    )
    def test_partition_scheme_per_endpoint(
        self, endpoint: str, expected_mode: str | None, expected_keys: list[str] | None, expected_format: str | None
    ) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=[] if endpoint == "visits" else {})],
            resume_state=MatomoResumeConfig(next_date=datetime.now(tz=UTC).date().isoformat()),
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_mode == expected_mode
        assert result.response.partition_keys == expected_keys
        assert result.response.partition_format == expected_format
        # partition_size=1 is what caused the per-row explosion; it must never come back.
        assert result.response.partition_size is None
        assert result.response.partition_count is None
