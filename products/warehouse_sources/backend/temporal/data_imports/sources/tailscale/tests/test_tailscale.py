from datetime import UTC, datetime
from typing import Any, Optional

import pytest
from freezegun import freeze_time
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale import tailscale as tailscale_module
from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.settings import TAILSCALE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.tailscale import (
    TailscaleAuth,
    TailscaleAuthError,
    TailscaleResumeConfig,
    _endpoint_url,
    _parse_datetime,
    _parse_retry_after,
    get_rows,
    normalize_tailnet,
    tailscale_source,
    validate_credentials,
)


def _response(*, status_code: int = 200, json_data: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.text = text
    response.json.return_value = json_data
    response.headers = {}
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception(f"{status_code} Client Error")
    else:
        response.raise_for_status.return_value = None
    return response


def _patch_session(responses: list[Any]) -> tuple[mock.MagicMock, Any]:
    session = mock.MagicMock()
    session.get.side_effect = responses
    return session, mock.patch.object(tailscale_module, "make_tracked_session", return_value=session)


class TestNormalizeTailnet:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "-"),
            ("", "-"),
            ("   ", "-"),
            ("-", "-"),
            ("example.com", "example.com"),
            ("  example.com  ", "example.com"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_tailnet(raw) == expected

    def test_endpoint_url_quotes_tailnet_as_single_path_segment(self):
        url = _endpoint_url(TAILSCALE_ENDPOINTS["devices"], "bad/../segment")
        assert url == "https://api.tailscale.com/api/v2/tailnet/bad%2F..%2Fsegment/devices"


class TestParseDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            # Tailscale timestamps carry nanosecond precision, which fromisoformat rejects untrimmed.
            ("2026-01-15T10:30:45.687985429Z", datetime(2026, 1, 15, 10, 30, 45, 687985, tzinfo=UTC)),
            ("2026-01-15T10:30:45Z", datetime(2026, 1, 15, 10, 30, 45, tzinfo=UTC)),
            (datetime(2026, 1, 15, 10, 30, 45), datetime(2026, 1, 15, 10, 30, 45, tzinfo=UTC)),
            ("not-a-date", None),
            ("", None),
            (None, None),
        ],
    )
    def test_parse(self, value, expected):
        assert _parse_datetime(value) == expected


class TestTailscaleAuth:
    def test_api_key_used_directly_without_token_exchange(self):
        session, patched = _patch_session([])
        with patched:
            headers = TailscaleAuth(api_key="tskey-api-x").get_headers()
        assert headers["Authorization"] == "Bearer tskey-api-x"
        session.post.assert_not_called()

    def test_oauth_client_exchanges_and_caches_token(self):
        session = mock.MagicMock()
        session.post.return_value = _response(json_data={"access_token": "at-123", "expires_in": 3600})
        with mock.patch.object(tailscale_module, "make_tracked_session", return_value=session):
            auth = TailscaleAuth(client_id="cid", client_secret="csecret")
            first = auth.get_headers()
            second = auth.get_headers()

        assert first["Authorization"] == "Bearer at-123"
        assert second == first
        assert session.post.call_count == 1
        assert session.post.call_args.kwargs["data"] == {"client_id": "cid", "client_secret": "csecret"}

    @pytest.mark.parametrize("json_data", [{"error": "bad"}, {}])
    def test_oauth_failure_raises_auth_error(self, json_data):
        session = mock.MagicMock()
        session.post.return_value = _response(status_code=401, json_data=json_data)
        with mock.patch.object(tailscale_module, "make_tracked_session", return_value=session):
            with pytest.raises(TailscaleAuthError):
                TailscaleAuth(client_id="cid", client_secret="wrong").get_headers()

    def test_missing_credentials_raises_auth_error(self):
        with pytest.raises(TailscaleAuthError):
            TailscaleAuth().get_headers()


class TestTailscaleSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, partition_key",
        [
            ("devices", ["id"], None),
            ("users", ["id"], None),
            ("keys", ["id"], None),
            ("configuration_audit_logs", None, "eventTime"),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, partition_key):
        response = tailscale_source(
            api_key="tskey-api-x",
            client_id=None,
            client_secret=None,
            tailnet=None,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestGetRows:
    def _run(self, endpoint: str, responses: list[Any], manager: Optional[mock.MagicMock] = None, **kwargs: Any):
        if manager is None:
            manager = mock.MagicMock()
            manager.can_resume.return_value = False
        session, patched = _patch_session(responses)
        with patched:
            rows: list[dict[str, Any]] = []
            for batch in get_rows(
                api_key="tskey-api-x",
                client_id=None,
                client_secret=None,
                tailnet="example.com",
                endpoint=endpoint,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                **kwargs,
            ):
                rows.extend(batch)
        return rows, session, manager

    def test_devices_single_request_with_all_fields(self):
        rows, session, _ = self._run("devices", [_response(json_data={"devices": [{"id": "1"}, {"id": "2"}]})])
        assert [r["id"] for r in rows] == ["1", "2"]
        assert session.get.call_count == 1
        call = session.get.call_args
        assert call.args[0] == "https://api.tailscale.com/api/v2/tailnet/example.com/devices"
        assert call.kwargs["params"] == {"fields": "all"}

    def test_keys_fans_out_to_details_and_skips_deleted(self):
        responses = [
            _response(json_data={"keys": [{"id": "k1"}, {"id": "k2"}]}),
            _response(json_data={"id": "k1", "created": "2026-01-01T00:00:00Z"}),
            _response(status_code=404),
        ]
        rows, session, _ = self._run("keys", responses)

        # The deleted key's 404 is skipped rather than failing the sync.
        assert rows == [{"id": "k1", "created": "2026-01-01T00:00:00Z"}]
        detail_urls = [call.args[0] for call in session.get.call_args_list[1:]]
        assert detail_urls == [
            "https://api.tailscale.com/api/v2/tailnet/example.com/keys/k1",
            "https://api.tailscale.com/api/v2/tailnet/example.com/keys/k2",
        ]


@freeze_time("2026-01-30T00:00:00Z")
class TestAuditLogRows:
    def _run(self, responses: list[Any], manager: Optional[mock.MagicMock] = None, **kwargs: Any):
        if manager is None:
            manager = mock.MagicMock()
            manager.can_resume.return_value = False
        session, patched = _patch_session(responses)
        with patched:
            batches = list(
                get_rows(
                    api_key="tskey-api-x",
                    client_id=None,
                    client_secret=None,
                    tailnet="example.com",
                    endpoint="configuration_audit_logs",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    **kwargs,
                )
            )
        return batches, session, manager

    def _log(self, event_time: str, action: str = "UPDATE") -> dict[str, Any]:
        return {"eventTime": event_time, "action": action}

    def test_incremental_sync_windows_filters_and_checkpoints(self):
        # Watermark 2026-01-20 with 7-day windows and now=2026-01-30 → two windows:
        # [01-20, 01-27] and [01-27, 01-30].
        window1 = _response(
            json_data={
                "logs": [
                    # Returned newest-first to prove client-side ascending sort.
                    self._log("2026-01-25T00:00:00Z"),
                    self._log("2026-01-21T00:00:00Z"),
                    # `start` is inclusive, so the watermark row comes back — it must be dropped.
                    self._log("2026-01-20T00:00:00Z"),
                ]
            }
        )
        window2 = _response(
            json_data={
                "logs": [
                    # Window boundaries are inclusive on both ends, so the last row of window 1
                    # would reappear if it fell exactly on the boundary; the max-seen cursor
                    # drops anything at or before it.
                    self._log("2026-01-25T00:00:00Z"),
                    self._log("2026-01-29T00:00:00Z"),
                ]
            }
        )
        batches, session, manager = self._run(
            [window1, window2],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-20T00:00:00Z",
        )

        assert [[r["eventTime"] for r in batch] for batch in batches] == [
            ["2026-01-21T00:00:00Z", "2026-01-25T00:00:00Z"],
            ["2026-01-29T00:00:00Z"],
        ]

        requested_windows = [call.kwargs["params"] for call in session.get.call_args_list]
        assert requested_windows == [
            {"start": "2026-01-20T00:00:00Z", "end": "2026-01-27T00:00:00Z"},
            {"start": "2026-01-27T00:00:00Z", "end": "2026-01-30T00:00:00Z"},
        ]

        saved = [call.args[0].window_start for call in manager.save_state.call_args_list]
        assert saved == ["2026-01-27T00:00:00Z", "2026-01-30T00:00:00Z"]

    def test_resumes_from_saved_window(self):
        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = TailscaleResumeConfig(window_start="2026-01-28T00:00:00Z")

        _batches, session, _ = self._run(
            [_response(json_data={"logs": []})],
            manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-20T00:00:00Z",
        )

        assert session.get.call_count == 1
        assert session.get.call_args.kwargs["params"]["start"] == "2026-01-28T00:00:00Z"

    def test_watermark_older_than_retention_is_clamped(self):
        # Requesting a start older than the 90-day retention window risks a 4xx, so the
        # start is clamped to now - 90 days.
        with mock.patch.object(tailscale_module, "AUDIT_LOG_WINDOW_DAYS", 365):
            _batches, session, _ = self._run(
                [_response(json_data={"logs": []})],
                should_use_incremental_field=True,
                db_incremental_field_last_value="2025-01-01T00:00:00Z",
            )
        assert session.get.call_args.kwargs["params"] == {
            "start": "2025-11-01T00:00:00Z",
            "end": "2026-01-30T00:00:00Z",
        }

    def test_full_refresh_keeps_all_rows(self):
        with mock.patch.object(tailscale_module, "AUDIT_LOG_WINDOW_DAYS", 365):
            batches, _session, _ = self._run(
                [_response(json_data={"logs": [self._log("2025-11-02T00:00:00Z")]})],
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
        assert [[r["eventTime"] for r in batch] for batch in batches] == [["2025-11-02T00:00:00Z"]]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, schema_name, expected_valid",
        [
            (200, None, True),
            (401, None, False),
            # A 403 at source-create passes (scoped OAuth clients may not grant the
            # probe's scope), but a scoped per-schema probe fails.
            (403, None, True),
            (403, "devices", False),
            (404, None, False),
        ],
    )
    def test_status_mapping(self, status_code, schema_name, expected_valid):
        _session, patched = _patch_session([_response(status_code=status_code, json_data={"message": "nope"})])
        with patched:
            valid, message = validate_credentials(
                api_key="tskey-api-x",
                client_id=None,
                client_secret=None,
                tailnet=None,
                schema_name=schema_name,
            )
        assert valid is expected_valid
        if not expected_valid:
            assert message

    def test_audit_logs_probe_sends_required_time_window(self):
        session, patched = _patch_session([_response(json_data={"logs": []})])
        with patched:
            valid, _ = validate_credentials(
                api_key="tskey-api-x",
                client_id=None,
                client_secret=None,
                tailnet=None,
                schema_name="configuration_audit_logs",
            )
        assert valid is True
        params = session.get.call_args.kwargs["params"]
        assert "start" in params and "end" in params

    def test_oauth_exchange_failure_is_reported(self):
        session = mock.MagicMock()
        session.post.return_value = _response(status_code=401, json_data={})
        with mock.patch.object(tailscale_module, "make_tracked_session", return_value=session):
            valid, message = validate_credentials(
                api_key=None,
                client_id="cid",
                client_secret="wrong",
                tailnet=None,
            )
        assert valid is False
        assert "OAuth" in (message or "")

    def test_request_exception_returns_failure(self):
        import requests

        session = mock.MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError("boom")
        with mock.patch.object(tailscale_module, "make_tracked_session", return_value=session):
            valid, message = validate_credentials(
                api_key="tskey-api-x", client_id=None, client_secret=None, tailnet=None
            )
        assert valid is False
        assert "boom" in (message or "")


class TestRetryAfter:
    @pytest.mark.parametrize(
        "headers, expected",
        [
            ({"Retry-After": "5"}, 5.0),
            ({"Retry-After": "100000"}, 60.0),  # capped
            ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),  # HTTP-date ignored
            ({}, None),
        ],
    )
    def test_parse_retry_after(self, headers, expected):
        response = mock.MagicMock()
        response.headers = headers
        assert _parse_retry_after(response) == expected
