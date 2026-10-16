from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
import time_machine
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.daisycon.daisycon import (
    DaisyconPublisherError,
    DaisyconResumeConfig,
    add_last_modified,
    resolve_publisher_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.daisycon.source import DaisyconSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.daisycon import (
    DaisyconSourceConfig,
)

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.daisycon.source"


@contextmanager
def _connected(publisher_ids: list[str]) -> Iterator[None]:
    integration = SimpleNamespace(config={"daisycon_publisher_ids": publisher_ids})
    with (
        mock.patch.object(DaisyconSource, "get_oauth_integration", return_value=integration),
        mock.patch(f"{SOURCE_MODULE}.resolve_daisycon_oauth_token", return_value="at_1"),
    ):
        yield


def _run(endpoint: str, script: Any, config: DaisyconSourceConfig | None = None, **inputs: Any) -> DriveResult:
    config = config or DaisyconSourceConfig(daisycon_integration_id=7, publisher_id="111", currency_code=None)
    with _connected(["111"]):
        return SourceDriver(DaisyconSource(), config).run(endpoint, script, **inputs)


def _transaction(transaction_id: str, *modified: str) -> dict[str, Any]:
    return {
        "affiliatemarketing_id": transaction_id,
        "date": "2026-01-02 10:00:00",
        "parts": [{"id": f"p{i}", "last_modified": value} for i, value in enumerate(modified)],
    }


NO_CONTENT = ScriptedResponse(status=204)


class TestTransactions:
    def test_full_refresh_walks_pages_until_no_content(self) -> None:
        result = _run(
            "transactions",
            [
                ScriptedResponse(json=[_transaction("t1", "2026-01-03 09:00:00", "2026-02-01 08:00:00")]),
                ScriptedResponse(json=[_transaction("t2", "2026-01-04 09:00:00")]),
                NO_CONTENT,
            ],
        )

        assert result.raised is None
        assert result.paths == ["/publishers/111/transactions"] * 3
        assert result.params("page") == ["1", "2", "3"]
        assert result.params("per_page") == ["1000"] * 3
        assert result.params("date_modified_start") == ["2000-01-01 00:00:00"] * 3
        assert result.requests[0].headers["authorization"] == "Bearer at_1"
        assert [row["last_modified"] for row in result.rows] == ["2026-02-01 08:00:00", "2026-01-04 09:00:00"]
        assert result.committed_states[0] == DaisyconResumeConfig(next_page=2, date_filter="2000-01-01 00:00:00")
        assert result.response is not None and result.response.sort_mode == "desc"

    @pytest.mark.parametrize(
        ("last_value", "expected"),
        [
            (datetime(2026, 3, 4, 5, 6, 7), "2026-03-04 05:06:07"),
            ("2026-03-04 05:06:07", "2026-03-04 05:06:07"),
            (date(2026, 3, 4), "2026-03-04 00:00:00"),
        ],
    )
    def test_incremental_sync_filters_on_the_watermark(self, last_value: Any, expected: str) -> None:
        result = _run(
            "transactions",
            [NO_CONTENT],
            incremental_field="last_modified",
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.params("date_modified_start") == [expected]

    def test_resume_keeps_the_interrupted_filter_and_page(self) -> None:
        result = _run(
            "transactions",
            [NO_CONTENT],
            resume_state=DaisyconResumeConfig(next_page=3, date_filter="2026-01-01 00:00:00"),
            incremental_field="last_modified",
            db_incremental_field_last_value=datetime(2026, 5, 1),
        )

        assert result.raised is None
        assert result.params("page") == ["3"]
        assert result.params("date_modified_start") == ["2026-01-01 00:00:00"]

    def test_a_rejected_token_fails_the_run_with_the_url_the_error_map_matches(self) -> None:
        result = _run(
            "transactions", always(ScriptedResponse(status=401, json={"error": "Authenticate: Expired token"}))
        )

        assert result.raised is not None
        assert "401 Client Error: Unauthorized for url: https://services.daisycon.com" in str(result.raised)


class TestStatistics:
    @time_machine.travel(datetime(2026, 10, 15, 12, tzinfo=UTC), tick=False)
    @pytest.mark.parametrize(
        ("currency_code", "last_value", "expected_start", "expected_currency"),
        [
            (None, None, "2000-01-01", "EUR"),
            ("usd ", date(2026, 9, 1), "2026-09-01", "USD"),
        ],
    )
    def test_requests_a_date_window_up_to_today(
        self, currency_code: str | None, last_value: Any, expected_start: str, expected_currency: str
    ) -> None:
        config = DaisyconSourceConfig(daisycon_integration_id=7, publisher_id="111", currency_code=currency_code)
        result = _run(
            "statistics_daily",
            [ScriptedResponse(json=[{"date": "2026-09-01", "currency_code": "EUR", "click_raw": 3}]), NO_CONTENT],
            config=config,
            incremental_field="date",
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.paths[0] == "/publishers/111/statistics/date"
        assert result.params("start")[0] == expected_start
        assert result.params("end")[0] == "2026-10-15"
        assert result.params("currency_code")[0] == expected_currency


class TestPublisherResolution:
    @pytest.mark.parametrize(
        ("requested", "available", "expected"),
        [
            ("222", ["111", "222"], "222"),
            (" 222 ", ["222"], "222"),
            (None, ["111"], "111"),
            ("", ["111"], "111"),
        ],
    )
    def test_picks_the_publisher(self, requested: str | None, available: list[str], expected: str) -> None:
        assert resolve_publisher_id(requested, available) == expected

    @pytest.mark.parametrize(
        ("requested", "available", "message"),
        [
            ("999", ["111", "222"], "cannot read publisher 999"),
            (None, ["111", "222"], "more than one publisher"),
        ],
    )
    def test_refuses_a_publisher_the_login_cannot_pick(
        self, requested: str | None, available: list[str], message: str
    ) -> None:
        with pytest.raises(DaisyconPublisherError, match=message):
            resolve_publisher_id(requested, available)


class TestAddLastModified:
    @pytest.mark.parametrize(
        ("row", "expected"),
        [
            ({"date": "2026-01-01 00:00:00", "parts": []}, "2026-01-01 00:00:00"),
            ({"date": "2026-01-01 00:00:00", "parts": None}, "2026-01-01 00:00:00"),
            (
                {
                    "date": "2026-01-01 00:00:00",
                    "parts": [{"id": "a"}, {"id": "b", "last_modified": "2026-03-01 00:00:00"}],
                },
                "2026-03-01 00:00:00",
            ),
        ],
    )
    def test_takes_the_newest_part_time_or_falls_back_to_the_transaction_date(
        self, row: dict[str, Any], expected: str
    ) -> None:
        assert add_last_modified(row)["last_modified"] == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("response", "publisher_id", "expected_valid", "message_fragment"),
        [
            (ScriptedResponse(json=[{"id": 111, "name": "Blog"}]), "111", True, None),
            (ScriptedResponse(status=401, json={"error": "Authenticate: Expired token"}), "111", False, "Reconnect"),
            (ScriptedResponse(status=503, json={"error": "Service unavailable"}), "111", False, "Could not reach"),
        ],
    )
    def test_maps_the_token_probe(
        self, response: ScriptedResponse, publisher_id: str, expected_valid: bool, message_fragment: str | None
    ) -> None:
        config = DaisyconSourceConfig(daisycon_integration_id=7, publisher_id=publisher_id, currency_code=None)
        with _connected(["111"]), scripted_network(always(response)) as network:
            is_valid, message = DaisyconSource().validate_credentials(config, team_id=1)

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message
        # Setup waits on the probe, so a 5xx gets no retry.
        assert [request.path for request in network.requests_log] == ["/publishers"]

    @pytest.mark.parametrize(
        ("publisher_id", "currency_code", "message_fragment"),
        [
            # The login gained publisher 222 after connecting; the sync only knows the stored list.
            ("222", None, "cannot read publisher 222"),
            ("111", "euro", "three-letter currency code"),
        ],
    )
    def test_refuses_what_the_sync_would_refuse_without_a_request(
        self, publisher_id: str, currency_code: str | None, message_fragment: str
    ) -> None:
        config = DaisyconSourceConfig(daisycon_integration_id=7, publisher_id=publisher_id, currency_code=currency_code)
        with _connected(["111"]), scripted_network([]) as network:
            is_valid, message = DaisyconSource().validate_credentials(config, team_id=1)

        assert is_valid is False
        assert message is not None and message_fragment in message
        assert network.requests_log == []
