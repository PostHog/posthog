from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import pytest
import time_machine
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tailscale import (
    TailscaleAuthMethodConfig,
    TailscaleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.settings import TAILSCALE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.source import TailscaleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.tailscale import (
    TailscaleAuth,
    TailscaleAuthError,
    TailscaleResumeConfig,
    _endpoint_url,
    _parse_datetime,
    _parse_retry_after,
    validate_credentials,
)


def _driver(tailnet: str | None = "example.com") -> SourceDriver:
    return SourceDriver(
        TailscaleSource(),
        TailscaleSourceConfig(
            auth_method=TailscaleAuthMethodConfig(selection="api_key", api_key="tskey-api-x"), tailnet=tailnet
        ),
    )


class TestNormalizeTailnet:
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
    def test_oauth_client_exchanges_and_caches_token(self):
        with scripted_network(always(ScriptedResponse(json={"access_token": "at-123", "expires_in": 3600}))) as network:
            auth = TailscaleAuth(client_id="cid", client_secret="csecret")
            first = auth.get_headers()
            second = auth.get_headers()

        assert first["Authorization"] == "Bearer at-123"
        assert second == first
        assert len(network.requests_log) == 1
        assert parse_qs((network.requests_log[0].body or b"").decode()) == {
            "client_id": ["cid"],
            "client_secret": ["csecret"],
        }

    @pytest.mark.parametrize("json_data", [{"error": "bad"}, {}])
    def test_oauth_failure_raises_auth_error(self, json_data):
        with scripted_network(always(ScriptedResponse(status=401, json=json_data))):
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
        response = _driver().run(endpoint, always(ScriptedResponse(json={}))).response

        assert response is not None
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
    def test_devices_single_request_with_all_fields(self):
        result = _driver().run("devices", [ScriptedResponse(json={"devices": [{"id": "1"}, {"id": "2"}]})])
        assert [r["id"] for r in result.rows] == ["1", "2"]
        assert len(result.requests) == 1
        request = result.requests[0]
        assert request.origin + request.path == "https://api.tailscale.com/api/v2/tailnet/example.com/devices"
        assert dict(request.query) == {"fields": ("all",)}

    def test_keys_fans_out_to_details_and_skips_deleted(self):
        result = _driver().run(
            "keys",
            [
                ScriptedResponse(json={"keys": [{"id": "k1"}, {"id": "k2"}]}),
                ScriptedResponse(json={"id": "k1", "created": "2026-01-01T00:00:00Z"}),
                ScriptedResponse(status=404),
            ],
        )

        # The deleted key's 404 is skipped rather than failing the sync.
        assert result.rows == [{"id": "k1", "created": "2026-01-01T00:00:00Z"}]
        detail_urls = [request.origin + request.path for request in result.requests[1:]]
        assert detail_urls == [
            "https://api.tailscale.com/api/v2/tailnet/example.com/keys/k1",
            "https://api.tailscale.com/api/v2/tailnet/example.com/keys/k2",
        ]


class TestAuditLogRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2026-01-30T00:00:00Z", tick=False):
            yield

    def _log(self, event_time: str, action: str = "UPDATE") -> dict[str, Any]:
        return {"eventTime": event_time, "action": action}

    def test_incremental_sync_windows_filters_and_checkpoints(self):
        # Watermark 2026-01-20 with 7-day windows and now=2026-01-30 → two windows:
        # [01-20, 01-27] and [01-27, 01-30].
        window1 = ScriptedResponse(
            json={
                "logs": [
                    # Returned newest-first to prove client-side ascending sort.
                    self._log("2026-01-25T00:00:00Z"),
                    self._log("2026-01-21T00:00:00Z"),
                    # `start` is inclusive, so the watermark row comes back — it must be dropped.
                    self._log("2026-01-20T00:00:00Z"),
                ]
            }
        )
        window2 = ScriptedResponse(
            json={
                "logs": [
                    # Window boundaries are inclusive on both ends, so the last row of window 1
                    # would reappear if it fell exactly on the boundary; the max-seen cursor
                    # drops anything at or before it.
                    self._log("2026-01-25T00:00:00Z"),
                    self._log("2026-01-29T00:00:00Z"),
                ]
            }
        )
        result = _driver().run(
            "configuration_audit_logs",
            [window1, window2],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-20T00:00:00Z",
        )

        assert [[r["eventTime"] for r in batch] for batch in result.items] == [
            ["2026-01-21T00:00:00Z", "2026-01-25T00:00:00Z"],
            ["2026-01-29T00:00:00Z"],
        ]

        requested_windows = [{name: values[0] for name, values in request.query.items()} for request in result.requests]
        assert requested_windows == [
            {"start": "2026-01-20T00:00:00Z", "end": "2026-01-27T00:00:00Z"},
            {"start": "2026-01-27T00:00:00Z", "end": "2026-01-30T00:00:00Z"},
        ]

        saved = [state.window_start for state in result.saved_states]
        assert saved == ["2026-01-27T00:00:00Z", "2026-01-30T00:00:00Z"]

    def test_resumes_from_saved_window(self):
        result = _driver().run(
            "configuration_audit_logs",
            [ScriptedResponse(json={"logs": []})],
            resume_state=TailscaleResumeConfig(window_start="2026-01-28T00:00:00Z"),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-20T00:00:00Z",
        )

        assert len(result.requests) == 1
        assert result.requests[0].param("start") == "2026-01-28T00:00:00Z"


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
        with scripted_network(always(ScriptedResponse(status=status_code, json={"message": "nope"}))):
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
        with scripted_network([ScriptedResponse(json={"logs": []})]) as network:
            valid, _ = validate_credentials(
                api_key="tskey-api-x",
                client_id=None,
                client_secret=None,
                tailnet=None,
                schema_name="configuration_audit_logs",
            )
        assert valid is True
        request = network.requests_log[0]
        assert request.param("start") is not None and request.param("end") is not None

    def test_oauth_exchange_failure_is_reported(self):
        with scripted_network(always(ScriptedResponse(status=401, json={}))):
            valid, message = validate_credentials(
                api_key=None,
                client_id="cid",
                client_secret="wrong",
                tailnet=None,
            )
        assert valid is False
        assert "OAuth" in (message or "")


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
