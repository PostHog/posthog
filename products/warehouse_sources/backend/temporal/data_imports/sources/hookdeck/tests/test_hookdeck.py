from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hookdeck import (
    HookdeckSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.hookdeck import (
    REDACTED,
    HookdeckResumeConfig,
    _format_datetime,
    _redact_secrets,
    base_url,
    build_params,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.settings import (
    HOOKDECK_ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.source import HookdeckSource

API_VERSION = "2026-09-01"
SUPPORTED_VERSIONS = ["2025-07-01", "2026-09-01"]

INCREMENTAL_ENDPOINTS = sorted(name for name, c in HOOKDECK_ENDPOINTS.items() if c.incremental_fields)
FULL_REFRESH_ENDPOINTS = sorted(name for name, c in HOOKDECK_ENDPOINTS.items() if not c.incremental_fields)
ENDPOINT_FIELD_PAIRS = sorted(
    (name, entry["field"]) for name, c in HOOKDECK_ENDPOINTS.items() for entry in c.incremental_fields
)


def _response(models: list[dict[str, Any]] | None, next_cursor: str | None, status: int = 200) -> ScriptedResponse:
    pagination: dict[str, Any] = {"order_by": "created_at", "dir": "asc", "limit": PAGE_SIZE}
    if next_cursor is not None:
        pagination["next"] = next_cursor
    body = {"pagination": pagination, "count": len(models or []), "models": models or []}
    return ScriptedResponse(status=status, json=body)


def _driver() -> SourceDriver:
    return SourceDriver(HookdeckSource(), HookdeckSourceConfig(api_key="hd_key"))


class TestHookdeckTransport:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("2026-03-04T02:58:14.000Z", "2026-03-04T02:58:14.000Z"),
        ],
    )
    def test_format_datetime_emits_iso_utc(self, value: object, expected: str) -> None:
        result = _format_datetime(value)

        assert result == expected
        assert "+00:00" not in result

    @pytest.mark.parametrize("api_version", SUPPORTED_VERSIONS)
    def test_base_url_carries_the_version_segment(self, api_version: str) -> None:
        # An unversioned request tracks Hookdeck's latest version.
        assert base_url(api_version) == f"https://api.hookdeck.com/{api_version}"

    @pytest.mark.parametrize("api_version", SUPPORTED_VERSIONS)
    def test_sync_requests_carry_the_pinned_version(self, api_version: str) -> None:
        result = _driver().run("destinations", [_response([{"id": "des_1"}], None)], api_version=api_version)

        assert result.raised is None
        assert result.requests[0].origin == "https://api.hookdeck.com"
        assert result.requests[0].path == f"/{api_version}/destinations"

    @pytest.mark.parametrize("endpoint", sorted(HOOKDECK_ENDPOINTS))
    def test_every_request_pins_ascending_order(self, endpoint: str) -> None:
        # Hookdeck defaults to `dir=desc`; sort_mode="asc" would corrupt the watermark without this.
        params = build_params(
            HOOKDECK_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert params["dir"] == "asc"
        assert params["limit"] == PAGE_SIZE
        assert params["order_by"] == "created_at"
        assert not [key for key in params if key.endswith("[gte]")]

    @pytest.mark.parametrize("endpoint, field", ENDPOINT_FIELD_PAIRS)
    def test_selected_incremental_field_drives_both_sort_and_filter(self, endpoint: str, field: str) -> None:
        params = build_params(
            HOOKDECK_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field=field,
        )

        assert params["order_by"] == field
        assert params[f"{field}[gte]"] == "2026-03-04T02:58:14.000Z"

    def test_unsortable_incremental_field_falls_back_instead_of_splitting_sort_and_filter(self) -> None:
        # `last_attempt_at` is filterable on /events but not a valid `order_by` value.
        params = build_params(
            HOOKDECK_ENDPOINTS["events"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="last_attempt_at",
        )

        assert params["order_by"] == "created_at"
        assert params["created_at[gte]"] == "2026-03-04T02:58:14.000Z"
        assert "last_attempt_at[gte]" not in params

    @pytest.mark.parametrize("endpoint", FULL_REFRESH_ENDPOINTS)
    def test_full_refresh_endpoints_never_send_a_date_filter(self, endpoint: str) -> None:
        params = build_params(
            HOOKDECK_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="created_at",
        )

        assert not [key for key in params if key.endswith("[gte]")]

    def test_watermark_ignored_when_incremental_is_off(self) -> None:
        params = build_params(
            HOOKDECK_ENDPOINTS["events"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="created_at",
        )

        assert "created_at[gte]" not in params

    def test_first_sync_sends_no_filter(self) -> None:
        params = build_params(
            HOOKDECK_ENDPOINTS["events"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="created_at",
        )

        assert "created_at[gte]" not in params


class TestHookdeckCredentials:
    @pytest.mark.parametrize("status_code, expected", [(403, False)])
    @pytest.mark.parametrize("api_version", SUPPORTED_VERSIONS)
    def test_status_mapping(self, api_version: str, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, status = validate_credentials("hd_key", api_version)

        assert is_valid is expected
        assert status == status_code
        assert network.requests_log[0].url == f"https://api.hookdeck.com/{api_version}/sources?limit=1"
        assert network.requests_log[0].headers["authorization"] == "Bearer hd_key"


class TestHookdeckPagination:
    def test_follows_next_cursor_until_absent(self) -> None:
        result = _driver().run(
            "events",
            [_response([{"id": "evt_1"}, {"id": "evt_2"}], "cur_2"), _response([{"id": "evt_3"}], None)],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["evt_1", "evt_2", "evt_3"]
        assert len(result.requests) == 2
        assert result.requests[0].param("next") is None
        assert result.requests[1].param("next") == "cur_2"

    def test_stops_when_the_cursor_stops_advancing(self) -> None:
        result = _driver().run("events", [_response([{"id": "evt_1"}], "cur_2"), _response([{"id": "evt_2"}], "cur_2")])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["evt_1", "evt_2"]
        assert len(result.requests) == 2

    def test_stops_on_an_empty_page_even_with_a_cursor(self) -> None:
        result = _driver().run("events", [_response([], "cur_2")])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1

    def test_saves_resume_state_after_each_page_but_not_the_last(self) -> None:
        result = _driver().run("events", [_response([{"id": "evt_1"}], "cur_2"), _response([{"id": "evt_2"}], None)])

        assert result.raised is None
        assert result.saved_states == [HookdeckResumeConfig(next_cursor="cur_2")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "events", [_response([{"id": "evt_9"}], None)], resume_state=HookdeckResumeConfig(next_cursor="cur_7")
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["evt_9"]
        assert result.requests[0].param("next") == "cur_7"

    def test_incremental_filter_rides_the_first_request(self) -> None:
        result = _driver().run(
            "issues",
            [_response([{"id": "iss_1"}], None)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="last_seen_at",
        )

        assert result.raised is None
        assert result.requests[0].param("order_by") == "last_seen_at"
        assert result.requests[0].param("dir") == "asc"
        assert result.requests[0].param("last_seen_at[gte]") == "2026-03-04T02:58:14.000Z"

    def test_retries_throttles_and_server_errors(self) -> None:
        result = _driver().run(
            "events",
            [
                _response(None, None, status=429),
                _response(None, None, status=503),
                _response([{"id": "evt_1"}], None),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["evt_1"]
        assert len(result.requests) == 3

    def test_client_error_raises(self) -> None:
        result = _driver().run("events", [_response(None, None, status=404)])

        assert isinstance(result.raised, requests.HTTPError)


class TestHookdeckRedaction:
    @pytest.mark.parametrize(
        "row, expected",
        [
            # Destination auth_method container masked wholesale; benign fields survive.
            (
                {
                    "id": "des_1",
                    "name": "prod",
                    "config": {"url": "https://x", "auth_method": {"type": "BEARER", "config": {"token": "sk_live"}}},
                },
                {"id": "des_1", "name": "prod", "config": {"url": "https://x", "auth_method": REDACTED}},
            ),
            # Source verification container masked.
            (
                {"id": "src_1", "verification": {"type": "HMAC", "configs": {"webhook_secret_key": "whsec"}}},
                {"id": "src_1", "verification": REDACTED},
            ),
            # Transformation env values masked but the (non-secret) names kept.
            (
                {"id": "trs_1", "code": "return x", "env": {"API_KEY": "secret", "REGION": "us"}},
                {"id": "trs_1", "code": "return x", "env": {"API_KEY": REDACTED, "REGION": REDACTED}},
            ),
            # Connection embeds full source and destination objects — nested secrets reached at depth.
            (
                {
                    "id": "con_1",
                    "source": {"verification": {"configs": {"api_key": "k"}}},
                    "destination": {"auth": {"password": "p"}},
                },
                {"id": "con_1", "source": {"verification": REDACTED}, "destination": {"auth": REDACTED}},
            ),
            # Secret leaf keys sitting directly in a config are masked; None is left intact.
            (
                {"config": {"access_key_id": "AKIA", "secret_access_key": "abc", "region": None}},
                {"config": {"access_key_id": REDACTED, "secret_access_key": REDACTED, "region": None}},
            ),
        ],
    )
    def test_redacts_credential_bearing_fields(self, row: dict[str, Any], expected: dict[str, Any]) -> None:
        assert _redact_secrets(row) == expected

    def test_credential_endpoint_rows_are_redacted_end_to_end(self) -> None:
        result = _driver().run(
            "destinations", [_response([{"id": "des_1", "auth_method": {"config": {"token": "sk_live"}}}], None)]
        )

        assert result.raised is None
        assert result.rows == [{"id": "des_1", "auth_method": REDACTED}]

    def test_non_credential_endpoint_rows_pass_through_untouched(self) -> None:
        # `events` isn't flagged as credential-bearing, so an auth-shaped key must not be masked.
        result = _driver().run(
            "events", [_response([{"id": "evt_1", "auth_method": {"config": {"token": "kept"}}}], None)]
        )

        assert result.raised is None
        assert result.rows == [{"id": "evt_1", "auth_method": {"config": {"token": "kept"}}}]


class TestHookdeckSampleCapture:
    # Raw responses reach the sampler before `_redact_secrets` runs, and the name-based scrubbers
    # don't recognise Hookdeck's secret containers, so both transports must opt out of sample capture.
    def test_sync_session_disables_sample_capture(self) -> None:
        result = _driver().run("events", [_response([], None)])

        assert result.raised is None
        assert result.session_options[0]["capture"] is False

    def test_probe_disables_sample_capture(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("hd_key", API_VERSION)

        assert network.session_options[0]["capture"] is False


class TestHookdeckSourceResponse:
    @pytest.mark.parametrize("endpoint", sorted(HOOKDECK_ENDPOINTS))
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response([], None)])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        # Hookdeck ids are unique per resource type, and no endpoint fans out from a parent.
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "month"
