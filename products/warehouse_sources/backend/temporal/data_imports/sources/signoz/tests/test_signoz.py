import dataclasses
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.signoz import signoz as sgz
from products.warehouse_sources.backend.temporal.data_imports.sources.signoz.settings import SIGNOZ_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.signoz.signoz import (
    SigNozResumeConfig,
    _build_query_range_body,
    _extract_config_items,
    _extract_raw_rows,
    _raw_row_to_item,
    _to_epoch_ms,
    normalize_host,
    signoz_source,
    validate_credentials,
)


class TestNormalizeHost:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("example.signoz.io", "example.signoz.io"),
            ("https://example.signoz.io", "example.signoz.io"),
            ("https://example.signoz.io/", "example.signoz.io"),
            ("http://example.signoz.io/api/v1", "example.signoz.io"),
            ("  example.signoz.io  ", "example.signoz.io"),
        ],
    )
    def test_normalize_host(self, raw: str, expected: str) -> None:
        assert normalize_host(raw) == expected


class TestToEpochMs:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 1, 1, tzinfo=UTC), 1767225600000),
            (datetime(2026, 1, 1), 1767225600000),  # naive -> UTC
            (date(2026, 1, 1), 1767225600000),
            (1767225600000, 1767225600000),  # already ms
            (1767225600, 1767225600000),  # seconds -> ms
            ("2026-01-01T00:00:00Z", 1767225600000),
            # Go marshals time.Time with nanosecond precision; must still parse.
            ("2026-01-01T00:00:00.123456789Z", 1767225600123),
            ("not-a-timestamp", None),
            (None, None),
        ],
    )
    def test_to_epoch_ms(self, value: Any, expected: int | None) -> None:
        assert _to_epoch_ms(value) == expected


class TestBuildQueryRangeBody:
    def test_logs_body_shape(self) -> None:
        body = _build_query_range_body(SIGNOZ_ENDPOINTS["logs"], 1000, 2000, 50)

        assert body["start"] == 1000
        assert body["end"] == 2000
        assert body["requestType"] == "raw"
        spec = body["compositeQuery"]["queries"][0]["spec"]
        assert spec["signal"] == "logs"
        assert spec["offset"] == 50
        assert spec["limit"] == SIGNOZ_ENDPOINTS["logs"].page_size
        # Ascending timestamp+id ordering keeps offset paging deterministic and the
        # pipeline's incremental watermark correct.
        assert spec["order"] == [
            {"key": {"name": "timestamp"}, "direction": "asc"},
            {"key": {"name": "id"}, "direction": "asc"},
        ]

    def test_traces_order_uses_span_id_tiebreaker(self) -> None:
        body = _build_query_range_body(SIGNOZ_ENDPOINTS["traces"], 0, 1, 0)
        spec = body["compositeQuery"]["queries"][0]["spec"]
        assert spec["signal"] == "traces"
        assert [o["key"]["name"] for o in spec["order"]] == ["timestamp", "span_id"]


class TestExtractRawRows:
    def test_extracts_rows_from_v5_envelope(self) -> None:
        response = {
            "status": "success",
            "data": {
                "type": "raw",
                "data": {
                    "results": [
                        {
                            "queryName": "A",
                            "nextCursor": "",
                            "rows": [{"timestamp": "2026-01-01T00:00:00Z", "data": {"id": "1"}}],
                        }
                    ]
                },
            },
        }
        assert _extract_raw_rows(response) == [{"timestamp": "2026-01-01T00:00:00Z", "data": {"id": "1"}}]

    @pytest.mark.parametrize(
        "response",
        [
            {},
            {"data": {}},
            {"data": {"data": {}}},
            {"data": {"data": {"results": []}}},
            {"data": {"data": {"results": [{"queryName": "A", "rows": None}]}}},
            "unexpected",
            None,
        ],
    )
    def test_malformed_envelope_returns_empty(self, response: Any) -> None:
        assert _extract_raw_rows(response) == []


class TestRawRowToItem:
    def test_flattens_data_and_envelope_timestamp_wins(self) -> None:
        row = {
            "timestamp": "2026-01-01T00:00:00Z",
            "data": {"id": "1", "body": "hello", "timestamp": 1767225600000000000},
        }
        item = _raw_row_to_item(row)
        assert item == {"id": "1", "body": "hello", "timestamp": "2026-01-01T00:00:00Z"}

    def test_missing_data_map(self) -> None:
        assert _raw_row_to_item({"timestamp": "2026-01-01T00:00:00Z"}) == {"timestamp": "2026-01-01T00:00:00Z"}


class TestExtractConfigItems:
    def test_rules_nested_under_data_rules(self) -> None:
        response = {"status": "success", "data": {"rules": [{"id": "r1"}, {"id": "r2"}]}}
        assert _extract_config_items(response, SIGNOZ_ENDPOINTS["alert_rules"]) == [{"id": "r1"}, {"id": "r2"}]

    def test_dashboards_list_directly_under_data(self) -> None:
        response = {"status": "success", "data": [{"id": "d1"}]}
        assert _extract_config_items(response, SIGNOZ_ENDPOINTS["dashboards"]) == [{"id": "d1"}]

    def test_notification_channels_allowlist_strips_credential_data(self) -> None:
        # The `data` field carries receiver secrets (Slack webhook URLs, PagerDuty keys); the
        # allowlist must drop it (and anything else off-list) before it reaches the warehouse.
        response = {
            "status": "success",
            "data": [
                {
                    "id": "c1",
                    "name": "oncall",
                    "type": "slack",
                    "data": {"url": "https://hooks.slack.com/services/SECRET"},
                    "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-02T00:00:00Z",
                    "internal_field": "drop me",
                }
            ],
        }
        assert _extract_config_items(response, SIGNOZ_ENDPOINTS["notification_channels"]) == [
            {
                "id": "c1",
                "name": "oncall",
                "type": "slack",
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-02T00:00:00Z",
            }
        ]

    @pytest.mark.parametrize(
        "response",
        [{}, {"data": None}, {"data": {"rules": "nope"}}, None],
    )
    def test_malformed_response_returns_empty(self, response: Any) -> None:
        assert _extract_config_items(response, SIGNOZ_ENDPOINTS["alert_rules"]) == []


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "schema_name", "expected_valid"),
        [
            (200, None, True),
            (401, None, False),
            # 403 at source-create is a valid key without the probe's role -> accept.
            (403, None, True),
            # 403 on a scoped probe is a hard failure.
            (403, "logs", False),
            (500, None, False),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.signoz.signoz.make_tracked_session")
    def test_status_mapping(
        self, mock_session: mock.MagicMock, status_code: int, schema_name: str | None, expected_valid: bool
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        response.is_redirect = False
        response.is_permanent_redirect = False
        mock_session.return_value.get.return_value = response

        is_valid, error = validate_credentials("example.signoz.io", "key", schema_name=schema_name)

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.signoz.signoz.make_tracked_session")
    def test_probe_disables_sample_capture(self, mock_session: mock.MagicMock) -> None:
        # The probe response can echo the token, which the name-based scrubber can't strip, so
        # the session must be created with capture=False to keep it out of HTTP sample capture.
        response = mock.MagicMock()
        response.status_code = 200
        response.is_redirect = False
        response.is_permanent_redirect = False
        mock_session.return_value.get.return_value = response

        validate_credentials("example.signoz.io", "key")

        assert mock_session.call_args.kwargs["capture"] is False

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.signoz.signoz.make_tracked_session")
    def test_redirect_is_rejected(self, mock_session: mock.MagicMock) -> None:
        response = mock.MagicMock()
        response.status_code = 302
        response.is_redirect = True
        mock_session.return_value.get.return_value = response

        is_valid, error = validate_credentials("example.signoz.io", "key")
        assert is_valid is False
        assert error is not None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.signoz.signoz.make_tracked_session")
    def test_request_exception_is_caught(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        is_valid, error = validate_credentials("example.signoz.io", "key")
        assert is_valid is False
        assert error is not None

    @pytest.mark.parametrize("host", ["", "not a host!", "bad_host/"])
    def test_invalid_host_is_rejected_without_a_request(self, host: str) -> None:
        is_valid, error = validate_credentials(host, "key")
        assert is_valid is False
        assert error == "Invalid SigNoz host"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.signoz.signoz._is_host_safe")
    def test_unsafe_host_is_blocked(self, mock_host_safe: mock.MagicMock) -> None:
        mock_host_safe.return_value = (False, "Hosts with internal IP addresses are not allowed")
        is_valid, error = validate_credentials("10.0.0.1", "key", team_id=42)
        assert is_valid is False
        assert error == "Hosts with internal IP addresses are not allowed"


class TestSigNozSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "expected_pks", "expected_partition_key"),
        [
            ("logs", ["id"], "timestamp"),
            ("traces", ["trace_id", "span_id"], "timestamp"),
            ("alert_rules", ["id"], "createAt"),
            ("dashboards", ["id"], "createdAt"),
            ("notification_channels", ["id"], "createdAt"),
        ],
    )
    def test_source_response_shape(self, endpoint: str, expected_pks: list[str], expected_partition_key: str) -> None:
        response = signoz_source(
            host="example.signoz.io",
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [expected_partition_key]


def _page(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"status": "success", "data": {"type": "raw", "data": {"results": [{"queryName": "A", "rows": rows}]}}}


def _with_page_size(endpoint: str, page_size: int) -> Any:
    return dataclasses.replace(SIGNOZ_ENDPOINTS[endpoint], page_size=page_size)


def _log_row(ts: str, row_id: str) -> dict[str, Any]:
    return {"timestamp": ts, "data": {"id": row_id, "body": f"line {row_id}"}}


class TestGetRows:
    def _run(
        self,
        endpoint: str,
        responses: list[Any],
        can_resume: bool = False,
        resume_state: SigNozResumeConfig | None = None,
        page_size: int = 2,
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[list[dict[str, Any]]], list[SigNozResumeConfig], list[dict[str, Any]]]:
        manager = mock.MagicMock()
        manager.can_resume.return_value = can_resume
        manager.load_state.return_value = resume_state
        saved: list[SigNozResumeConfig] = []
        manager.save_state.side_effect = lambda state: saved.append(state)

        requests_made: list[dict[str, Any]] = []

        def fake_post(url: str, json: Any = None, timeout: Any = None, allow_redirects: Any = None) -> Any:
            requests_made.append({"url": url, "body": json})
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.ok = True
            resp.is_redirect = False
            resp.is_permanent_redirect = False
            resp.json.return_value = responses[len(requests_made) - 1]
            return resp

        def fake_get(url: str, timeout: Any = None, allow_redirects: Any = None) -> Any:
            requests_made.append({"url": url, "body": None})
            resp = mock.MagicMock()
            resp.status_code = 200
            resp.ok = True
            resp.is_redirect = False
            resp.is_permanent_redirect = False
            resp.json.return_value = responses[len(requests_made) - 1]
            return resp

        with (
            mock.patch.object(sgz, "make_tracked_session") as mock_session,
            mock.patch.dict(sgz.SIGNOZ_ENDPOINTS, {endpoint: _with_page_size(endpoint, page_size)}),
        ):
            mock_session.return_value.post.side_effect = fake_post
            mock_session.return_value.get.side_effect = fake_get
            batches = list(
                sgz.get_rows(
                    host="example.signoz.io",
                    api_key="key",
                    endpoint=endpoint,
                    team_id=1,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=should_use_incremental_field,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
            )
        return batches, saved, requests_made

    def test_config_endpoint_yields_items_from_single_get(self) -> None:
        responses = [{"status": "success", "data": {"rules": [{"id": "r1"}]}}]
        batches, saved, requests_made = self._run("alert_rules", responses)

        assert batches == [[{"id": "r1"}]]
        assert saved == []
        assert requests_made[0]["url"] == "https://example.signoz.io/api/v1/rules"
        assert requests_made[0]["body"] is None

    def test_notification_channels_endpoint_drops_credential_data(self) -> None:
        # End-to-end guard on the sync path: the receiver `data` payload never reaches the
        # yielded rows, so imported channel secrets can't land in the warehouse table.
        responses = [
            {
                "status": "success",
                "data": [{"id": "c1", "name": "oncall", "type": "slack", "data": {"url": "https://secret"}}],
            }
        ]
        batches, _saved, _requests = self._run("notification_channels", responses)

        assert batches == [[{"id": "c1", "name": "oncall", "type": "slack"}]]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.signoz.signoz.make_tracked_session")
    def test_sync_session_disables_sample_capture(self, mock_session: mock.MagicMock) -> None:
        # Imported telemetry/config can carry secrets the name-based scrubber can't strip, so
        # the sync session must be created with capture=False.
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.ok = True
        resp.is_redirect = False
        resp.is_permanent_redirect = False
        resp.json.return_value = _page([])
        mock_session.return_value.post.return_value = resp

        list(
            sgz.get_rows(
                host="example.signoz.io",
                api_key="key",
                endpoint="logs",
                team_id=1,
                logger=mock.MagicMock(),
                resumable_source_manager=mock.MagicMock(can_resume=lambda: False),
            )
        )

        assert mock_session.call_args.kwargs["capture"] is False

    def test_short_page_terminates_without_saving_state(self) -> None:
        responses = [_page([_log_row("2026-01-01T00:00:00Z", "1")])]
        batches, saved, requests_made = self._run("logs", responses, page_size=2)

        assert len(batches) == 1
        assert batches[0][0]["id"] == "1"
        assert saved == []
        assert len(requests_made) == 1
        assert requests_made[0]["url"] == "https://example.signoz.io/api/v5/query_range"

    def test_full_page_advances_window_start_and_saves_state_after_yield(self) -> None:
        responses = [
            _page([_log_row("2026-01-01T00:00:00Z", "1"), _log_row("2026-01-01T00:00:01Z", "2")]),
            _page([_log_row("2026-01-01T00:00:02Z", "3")]),
        ]
        batches, saved, requests_made = self._run(
            "logs",
            responses,
            can_resume=True,
            resume_state=SigNozResumeConfig(window_start_ms=1767225600000, window_end_ms=1767312000000, offset=0),
            page_size=2,
        )

        assert [len(b) for b in batches] == [2, 1]
        # Window start advanced to the last row's timestamp; one trailing row at that ms is
        # skipped via the offset instead of an ever-growing window offset.
        assert len(saved) == 1
        assert saved[0].window_start_ms == 1767225601000
        assert saved[0].offset == 1
        # The second request starts at the advanced window with the trailing-row offset.
        second_spec = requests_made[1]["body"]["compositeQuery"]["queries"][0]["spec"]
        assert requests_made[1]["body"]["start"] == 1767225601000
        assert second_spec["offset"] == 1

    def test_full_page_within_one_millisecond_grows_offset(self) -> None:
        same_ts = "2026-01-01T00:00:00Z"
        responses = [
            _page([_log_row(same_ts, "1"), _log_row(same_ts, "2")]),
            _page([_log_row(same_ts, "3"), _log_row(same_ts, "4")]),
            _page([]),
        ]
        _batches, saved, requests_made = self._run(
            "logs",
            responses,
            can_resume=True,
            resume_state=SigNozResumeConfig(window_start_ms=1767225600000, window_end_ms=1767225700000, offset=0),
            page_size=2,
        )

        # The whole window-start millisecond spans multiple pages: offset accumulates so no
        # rows are skipped and none are refetched.
        assert [s.offset for s in saved] == [2, 4]
        assert all(s.window_start_ms == 1767225600000 for s in saved)
        assert [r["body"]["compositeQuery"]["queries"][0]["spec"]["offset"] for r in requests_made] == [0, 2, 4]

    def test_resumes_from_saved_window(self) -> None:
        responses = [_page([])]
        _batches, _saved, requests_made = self._run(
            "logs",
            responses,
            can_resume=True,
            resume_state=SigNozResumeConfig(window_start_ms=123, window_end_ms=456, offset=7),
        )

        body = requests_made[0]["body"]
        assert body["start"] == 123
        assert body["end"] == 456
        assert body["compositeQuery"]["queries"][0]["spec"]["offset"] == 7

    def test_incremental_watermark_sets_window_start(self) -> None:
        responses = [_page([])]
        _batches, _saved, requests_made = self._run(
            "logs",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert requests_made[0]["body"]["start"] == 1767225600000

    def test_first_sync_uses_lookback_window(self) -> None:
        responses = [_page([])]
        _batches, _saved, requests_made = self._run("logs", responses)

        body = requests_made[0]["body"]
        lookback_days = (body["end"] - body["start"]) / 1000 / 86400
        assert round(lookback_days) == SIGNOZ_ENDPOINTS["logs"].default_lookback_days
