import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.hookdeck import (
    REDACTED,
    HookdeckResumeConfig,
    _format_datetime,
    _redact_secrets,
    base_url,
    build_params,
    hookdeck_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.settings import (
    HOOKDECK_ENDPOINTS,
    PAGE_SIZE,
)

HOOKDECK_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.hookdeck.hookdeck.make_tracked_session"
)

API_VERSION = "2025-07-01"

INCREMENTAL_ENDPOINTS = sorted(name for name, c in HOOKDECK_ENDPOINTS.items() if c.incremental_fields)
FULL_REFRESH_ENDPOINTS = sorted(name for name, c in HOOKDECK_ENDPOINTS.items() if not c.incremental_fields)
ENDPOINT_FIELD_PAIRS = sorted(
    (name, entry["field"]) for name, c in HOOKDECK_ENDPOINTS.items() for entry in c.incremental_fields
)


def _response(models: list[dict[str, Any]] | None, next_cursor: str | None, status: int = 200) -> Response:
    pagination: dict[str, Any] = {"order_by": "created_at", "dir": "asc", "limit": PAGE_SIZE}
    if next_cursor is not None:
        pagination["next"] = next_cursor
    body = {"pagination": pagination, "count": len(models or []), "models": models or []}
    response = Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    return response


def _make_manager(resume_state: HookdeckResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    # `request.params` is one dict mutated in place across pages, so snapshot a copy per request.
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return hookdeck_source(
        "hd_key",
        API_VERSION,
        endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


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

    def test_base_url_carries_the_version_segment(self) -> None:
        # An unversioned request resolves to Hookdeck's OLDEST supported version.
        assert base_url(API_VERSION) == f"https://api.hookdeck.com/{API_VERSION}"

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
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_status_mapping(self, mock_session_factory, status_code: int, expected: bool) -> None:
        mock_session_factory.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        is_valid, status = validate_credentials("hd_key", API_VERSION)

        assert is_valid is expected
        assert status == status_code

        call = mock_session_factory.return_value.get.call_args
        assert call.args[0] == f"https://api.hookdeck.com/{API_VERSION}/sources?limit=1"
        assert call.kwargs["headers"]["Authorization"] == "Bearer hd_key"

    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_transport_error_is_not_valid(self, mock_session_factory) -> None:
        mock_session_factory.return_value.get.side_effect = requests.ConnectionError("boom")

        assert validate_credentials("hd_key", API_VERSION) == (False, None)


class TestHookdeckPagination:
    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_follows_next_cursor_until_absent(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [_response([{"id": "evt_1"}, {"id": "evt_2"}], "cur_2"), _response([{"id": "evt_3"}], None)],
        )

        rows = _rows(_source("events", _make_manager()))

        assert [row["id"] for row in rows] == ["evt_1", "evt_2", "evt_3"]
        assert session.send.call_count == 2
        assert "next" not in params[0]
        assert params[1]["next"] == "cur_2"

    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_stops_when_the_cursor_stops_advancing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "evt_1"}], "cur_2"), _response([{"id": "evt_2"}], "cur_2")])

        rows = _rows(_source("events", _make_manager()))

        assert [row["id"] for row in rows] == ["evt_1", "evt_2"]
        assert session.send.call_count == 2

    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_stops_on_an_empty_page_even_with_a_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], "cur_2")])

        assert _rows(_source("events", _make_manager())) == []
        assert session.send.call_count == 1

    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_saves_resume_state_after_each_page_but_not_the_last(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "evt_1"}], "cur_2"), _response([{"id": "evt_2"}], None)])
        manager = _make_manager()

        _rows(_source("events", manager))

        assert manager.save_state.call_count == 1
        assert manager.save_state.call_args.args[0] == HookdeckResumeConfig(next_cursor="cur_2")

    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "evt_9"}], None)])

        rows = _rows(_source("events", _make_manager(HookdeckResumeConfig(next_cursor="cur_7"))))

        assert [row["id"] for row in rows] == ["evt_9"]
        assert params[0]["next"] == "cur_7"

    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_incremental_filter_rides_the_first_request(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "iss_1"}], None)])

        _rows(
            _source(
                "issues",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                incremental_field="last_seen_at",
            )
        )

        assert params[0]["order_by"] == "last_seen_at"
        assert params[0]["dir"] == "asc"
        assert params[0]["last_seen_at[gte]"] == "2026-03-04T02:58:14.000Z"

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_retries_throttles_and_server_errors(self, MockSession, _mock_sleep) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(None, None, status=429),
                _response(None, None, status=503),
                _response([{"id": "evt_1"}], None),
            ],
        )

        rows = _rows(_source("events", _make_manager()))

        assert [row["id"] for row in rows] == ["evt_1"]
        assert session.send.call_count == 3

    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_client_error_raises(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, None, status=404)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("events", _make_manager()))


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

    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_credential_endpoint_rows_are_redacted_end_to_end(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "des_1", "auth_method": {"config": {"token": "sk_live"}}}], None)])

        rows = _rows(_source("destinations", _make_manager()))

        assert rows == [{"id": "des_1", "auth_method": REDACTED}]

    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_non_credential_endpoint_rows_pass_through_untouched(self, MockSession) -> None:
        # `events` isn't flagged as credential-bearing, so an auth-shaped key must not be masked.
        session = MockSession.return_value
        _wire(session, [_response([{"id": "evt_1", "auth_method": {"config": {"token": "kept"}}}], None)])

        rows = _rows(_source("events", _make_manager()))

        assert rows == [{"id": "evt_1", "auth_method": {"config": {"token": "kept"}}}]


class TestHookdeckSampleCapture:
    # Raw responses reach the sampler before `_redact_secrets` runs, and the name-based scrubbers
    # don't recognise Hookdeck's secret containers, so both transports must opt out of sample capture.
    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_sync_session_disables_sample_capture(self, MockSession) -> None:
        MockSession.return_value.headers = {}

        _source("events", _make_manager())

        assert MockSession.call_args.kwargs["capture"] is False

    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_probe_disables_sample_capture(self, MockSession) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("hd_key", API_VERSION)

        assert MockSession.call_args.kwargs["capture"] is False


class TestHookdeckSourceResponse:
    @pytest.mark.parametrize("endpoint", sorted(HOOKDECK_ENDPOINTS))
    @mock.patch(HOOKDECK_SESSION_PATCH)
    def test_source_response_shape(self, MockSession, endpoint: str) -> None:
        MockSession.return_value.headers = {}

        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        # Hookdeck ids are unique per resource type, and no endpoint fans out from a parent.
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "month"
