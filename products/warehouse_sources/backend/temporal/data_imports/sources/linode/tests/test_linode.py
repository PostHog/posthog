import json
from datetime import UTC, date, datetime
from typing import Any

import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.linode import LinodeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.linode.linode import (
    LinodeResumeConfig,
    _format_filter_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linode.source import LinodeSource


def _driver() -> SourceDriver:
    return SourceDriver(LinodeSource(), LinodeSourceConfig(api_token="tok"))


def _page(items: list[dict[str, Any]], *, page: int = 1, pages: int = 1) -> ScriptedResponse:
    return ScriptedResponse(json={"page": page, "pages": pages, "results": len(items), "data": items})


class TestFormatFilterValue:
    @parameterized.expand(
        [
            ("integer_passthrough", 12345, 12345),
            ("string_passthrough", "abc", "abc"),
            ("aware_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
        ]
    )
    def test_format_filter_value(self, _name: str, value: Any, expected: Any) -> None:
        # A "+00:00" offset in the filter value would make Linode reject the X-Filter, so datetimes
        # must render without one.
        assert _format_filter_value(value) == expected


class TestValidateCredentials:
    def test_token_is_registered_for_redaction(self) -> None:
        # The PAT rides in an Authorization header the value-based scrubber can only mask if the token
        # is registered via redact_values; dropping it would leak the credential into HTTP telemetry.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("tok")
        assert network.session_options[0]["redact_values"] == ("tok",)

    def test_error_status_does_not_leak_response_body(self) -> None:
        # Linode error bodies can echo account data; the persisted validation message must not carry it.
        with scripted_network(always(ScriptedResponse(status=500, body=b"secret account details"))):
            _valid, message = validate_credentials("tok")
        assert message == "Linode API returned 500"
        assert "secret account details" not in message


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        # Only page 2 has a response. A different resume page causes the test to fail.
        result = _driver().run(
            "volumes", [_page([{"id": 3}], page=2, pages=2)], resume_state=LinodeResumeConfig(next_page=2)
        )

        assert result.raised is None
        assert result.params("page") == ["2"]
        assert [row["id"] for row in result.rows] == [3]

    def test_incremental_endpoint_attaches_x_filter_with_watermark(self) -> None:
        # A regression that stops threading the watermark into the X-Filter would silently revert
        # incremental events to a full refresh; assert the id `+gte` bound is present on the request.
        result = _driver().run(
            "events",
            [_page([{"id": 5}])],
            incremental_field="id",
            db_incremental_field_last_value=4,
        )

        assert result.raised is None
        assert json.loads(result.requests[0].headers["x-filter"]) == {
            "+order_by": "id",
            "+order": "asc",
            "id": {"+gte": 4},
        }

    def test_sync_session_registers_token_for_redaction(self) -> None:
        # The PAT rides on the Authorization header of every paginated request, so it must be
        # registered for value-based masking in HTTP telemetry.
        result = _driver().run("volumes", [_page([{"id": 1}])])

        assert result.raised is None
        assert result.session_options[0]["redact_values"] == ("tok",)

    def test_checkpoint_advances_per_committed_page(self) -> None:
        # Each page is yielded (and committed downstream) before its checkpoint is saved, and the
        # checkpoint points at the NEXT unfetched page — so a crash resumes there without re-fetching
        # committed rows or skipping any (the guarantee the append-only endpoints rely on). The final
        # page has no next page, so it saves nothing.
        result = _driver().run(
            "volumes",
            [
                _page([{"id": 1}], page=1, pages=3),
                _page([{"id": 2}], page=2, pages=3),
                _page([{"id": 3}], page=3, pages=3),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.saved_states == [LinodeResumeConfig(next_page=2), LinodeResumeConfig(next_page=3)]
        assert result.committed_states == [LinodeResumeConfig(next_page=2), LinodeResumeConfig(next_page=3)]

    def test_lke_node_pools_fan_out_per_cluster_and_carry_the_cluster_id(self) -> None:
        result = _driver().run(
            "lke_node_pools",
            [
                _page([{"id": 7, "label": "prod"}, {"id": 8, "label": "staging"}]),
                _page([{"id": 70, "count": 3}]),
                _page([{"id": 80, "count": 1}, {"id": 81, "count": 2}]),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v4/lke/clusters", "/v4/lke/clusters/7/pools", "/v4/lke/clusters/8/pools"]
        assert [(row["cluster_id"], row["id"], row["count"]) for row in result.rows] == [
            (7, 70, 3),
            (8, 80, 1),
            (8, 81, 2),
        ]

    def test_invoice_items_fan_out_per_invoice_and_carry_invoice_fields(self) -> None:
        result = _driver().run(
            "invoice_items",
            [
                _page([{"id": 11, "date": "2026-01-01T00:00:00"}, {"id": 12, "date": "2026-02-01T00:00:00"}]),
                _page([{"label": "Linode 1", "amount": 5.0}]),
                _page([{"label": "Linode 1", "amount": 5.0}, {"label": "Backups", "amount": 2.0}]),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/v4/account/invoices",
            "/v4/account/invoices/11/items",
            "/v4/account/invoices/12/items",
        ]
        assert [(row["invoice_id"], row["invoice_date"], row["label"]) for row in result.rows] == [
            (11, "2026-01-01T00:00:00", "Linode 1"),
            (12, "2026-02-01T00:00:00", "Linode 1"),
            (12, "2026-02-01T00:00:00", "Backups"),
        ]
        assert result.response is not None
        assert result.response.partition_keys == ["invoice_date"]

    def test_volume_quota_usage_fans_out_per_quota_and_skips_quotas_without_usage(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v4/volumes/quotas":
                return _page([{"quota_id": "vol-capacity-us-east"}, {"quota_id": "vol-attachments-us-east"}])
            if request.path == "/v4/volumes/quotas/vol-attachments-us-east/usage":
                return ScriptedResponse(status=404, json={"errors": [{"reason": "Not found"}]})
            return ScriptedResponse(json={"quota_limit": 51200, "usage": 12800})

        result = _driver().run("volume_quota_usage", respond)

        assert result.raised is None
        assert result.paths == [
            "/v4/volumes/quotas",
            "/v4/volumes/quotas/vol-capacity-us-east/usage",
            "/v4/volumes/quotas/vol-attachments-us-east/usage",
        ]
        assert result.requests[0].param("page_size") == "500"
        assert result.requests[1].param("page_size") is None
        assert result.rows == [{"quota_id": "vol-capacity-us-east", "quota_limit": 51200, "usage": 12800}]

    def test_account_transfer_yields_the_bare_object_as_one_row(self) -> None:
        transfer = {"quota": 4000, "used": 120, "billable": 0, "region_transfers": []}
        result = _driver().run("account_transfer", [ScriptedResponse(json=transfer)])

        assert result.raised is None
        assert result.rows == [transfer]
        assert result.requests[0].param("page_size") is None
        assert len(result.requests) == 1


_TRANSFER = {"bytes_in": 10, "bytes_out": 20, "bytes_total": 30}


def _monthly_transfer_vendor(missing_linode_id: int | None = None, missing_status: int = 404):
    linodes = [
        {"id": 1, "created": "2019-06-01T08:00:00"},
        {"id": 2, "created": "2026-02-10T12:30:00"},
        {"id": 3, "created": "2018-01-01T00:00:00"},
    ]

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/v4/linode/instances":
            return _page(linodes)
        linode_id = int(request.path.split("/")[4])
        if linode_id == missing_linode_id:
            return ScriptedResponse(status=missing_status, json={"errors": [{"reason": "Not found"}]})
        return ScriptedResponse(json=_TRANSFER)

    return respond


class TestMonthlyTransfer:
    @parameterized.expand(
        [
            (
                # A full refresh reads the lookback window and ignores a stale watermark.
                "full_refresh_reads_the_lookback_window",
                {"should_use_incremental_field": False, "db_incremental_field_last_value": datetime(2026, 2, 1)},
                [(2025, month) for month in range(4, 13)] + [(2026, 1)],
            ),
            (
                "first_incremental_sync_reads_the_lookback_window",
                {"incremental_field": "month_start", "db_incremental_field_last_value": None},
                [(2025, month) for month in range(4, 13)] + [(2026, 1)],
            ),
            (
                "incremental_sync_starts_at_the_watermark_month",
                {
                    "incremental_field": "month_start",
                    "db_incremental_field_last_value": datetime(2026, 2, 1, tzinfo=UTC),
                },
                [],
            ),
            (
                "string_watermark_mid_month",
                {"incremental_field": "month_start", "db_incremental_field_last_value": "2026-01-20T00:00:00"},
                [(2026, 1)],
            ),
        ]
    )
    @time_machine.travel(datetime(2026, 3, 15, 9, 0, tzinfo=UTC), tick=False)
    def test_walks_months_oldest_first_across_all_linodes(
        self, _name: str, inputs: dict[str, Any], months_before_february: list[tuple[int, int]]
    ) -> None:
        # Linode 2 exists from February 2026, so it gets no request for earlier months.
        expected = [(linode_id, year, month) for year, month in months_before_february for linode_id in (1, 3)]
        expected += [(linode_id, 2026, month) for month in (2, 3) for linode_id in (1, 2, 3)]

        result = _driver().run("linode_monthly_transfer", _monthly_transfer_vendor(), **inputs)

        assert result.raised is None
        assert [(row["linode_id"], row["year"], row["month"]) for row in result.rows] == expected
        assert result.paths[1:] == [
            f"/v4/linode/instances/{linode_id}/transfer/{year}/{month}" for linode_id, year, month in expected
        ]
        assert [row["month_start"] for row in result.rows] == [
            datetime(year, month, 1, tzinfo=UTC) for _id, year, month in expected
        ]
        assert result.rows[0]["bytes_total"] == 30

    @time_machine.travel(datetime(2026, 3, 15, tzinfo=UTC), tick=False)
    def test_skips_a_linode_deleted_after_the_listing(self) -> None:
        result = _driver().run(
            "linode_monthly_transfer",
            _monthly_transfer_vendor(missing_linode_id=3),
            incremental_field="month_start",
            db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
        )

        assert result.raised is None
        assert [row["linode_id"] for row in result.rows] == [1, 2]

    @time_machine.travel(datetime(2026, 3, 15, tzinfo=UTC), tick=False)
    def test_other_client_errors_fail_the_sync(self) -> None:
        result = _driver().run(
            "linode_monthly_transfer",
            _monthly_transfer_vendor(missing_linode_id=1, missing_status=403),
            incremental_field="month_start",
            db_incremental_field_last_value=datetime(2026, 3, 1, tzinfo=UTC),
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert "403" in str(result.raised)


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_statuses_are_retried_then_reraised(self, _name: str, status_code: int) -> None:
        result = _driver().run("volumes", always(ScriptedResponse(status=status_code, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5
        assert set(result.paths) == {"/v4/volumes"}

    def test_client_error_message_excludes_response_body(self) -> None:
        # Error bodies can carry account/billing/audit data; a failing sync must not copy the raw body
        # into the raised (and later persisted) error message.
        result = _driver().run(
            "volumes",
            [ScriptedResponse(status=404, json={"errors": [{"reason": "secret account details"}]})],
        )

        assert isinstance(result.raised, Exception)
        assert "secret account details" not in str(result.raised)


class TestLinodeSource:
    @parameterized.expand(
        [
            ("invoices", "date", True),
            ("events", "created", True),
            ("domains", None, False),
            ("users", None, False),
        ]
    )
    def test_partitioning_matches_stable_field(
        self, endpoint: str, partition_key: str | None, partitioned: bool
    ) -> None:
        result = _driver().run(endpoint, [_page([])])

        assert result.raised is None
        response = result.response
        assert response is not None
        if partitioned:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None
