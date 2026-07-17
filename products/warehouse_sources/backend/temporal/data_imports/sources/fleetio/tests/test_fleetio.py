import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.fleetio import (
    FLEETIO_API_VERSION,
    FleetioAuth,
    FleetioResumeConfig,
    _build_base_params,
    _format_incremental_value,
    fleetio_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.settings import FLEETIO_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the fleetio module.
FLEETIO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.fleetio.make_tracked_session"
)


def _response(records: list[dict[str, Any]] | None, next_cursor: str | None, *, body: Any = None) -> Response:
    resp = Response()
    resp.status_code = 200
    envelope: Any = body if body is not None else {"records": records or [], "next_cursor": next_cursor}
    resp._content = json.dumps(envelope).encode()
    return resp


def _make_manager(resume_state: FleetioResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages (the paginator injects the cursor
    into it), so inspecting it after the run shows only the final state — snapshot a copy when each
    request is prepared. The prepared request carries a real on-host URL so the client's SSRF
    allowed-hosts check passes.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = "https://secure.fleetio.com/api/v1/vehicles"
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(manager: mock.MagicMock, **kwargs: Any):
    return fleetio_source(
        api_key="k",
        account_token="a",
        endpoint="vehicles",
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "some-cursor", "some-cursor"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestFleetioAuth:
    def test_sets_both_credential_headers(self) -> None:
        request = PreparedRequest()
        request.headers = {}
        FleetioAuth("key123", "acct456")(request)
        assert request.headers["Authorization"] == "Token key123"
        assert request.headers["Account-Token"] == "acct456"

    def test_reports_both_credentials_as_secret_for_redaction(self) -> None:
        # Both the API key and the account token must be masked in HTTP telemetry; the account-token
        # header name isn't one the generic scrubbers recognise, so value-based redaction is required.
        assert set(FleetioAuth("key123", "acct456").secret_values()) == {"key123", "acct456"}


class TestBuildBaseParams:
    def test_full_refresh_sorts_by_partition_key_and_has_no_filter(self) -> None:
        params = _build_base_params(
            FLEETIO_ENDPOINTS["vehicles"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {"per_page": 100, "sort[created_at]": "asc"}

    def test_incremental_sorts_and_filters_on_chosen_field(self) -> None:
        params = _build_base_params(
            FLEETIO_ENDPOINTS["vehicles"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params["sort[updated_at]"] == "asc"
        assert params["filter[updated_at][gt]"] == "2026-03-04T02:58:14+00:00"

    def test_incremental_first_sync_has_no_filter_value(self) -> None:
        # First incremental sync has no last value yet — sort, but don't filter (pull everything).
        params = _build_base_params(
            FLEETIO_ENDPOINTS["vehicles"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="updated_at",
        )
        assert params == {"per_page": 100, "sort[updated_at]": "asc"}

    def test_incremental_on_created_at_filters_created_at(self) -> None:
        params = _build_base_params(
            FLEETIO_ENDPOINTS["fuel_entries"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert params["sort[created_at]"] == "asc"
        assert params["filter[created_at][gt]"] == "2026-01-01T00:00:00+00:00"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_next_cursor_is_null(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}, {"id": 2}], "CUR2"), _response([{"id": 3}], None)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        # First page carries no cursor; the second is fetched with the cursor from page one.
        assert "start_cursor" not in params[0]
        assert params[0]["per_page"] == 100
        assert params[0]["sort[created_at]"] == "asc"
        assert params[1]["start_cursor"] == "CUR2"
        # Checkpoint saved once (pointing at the next page); the terminal page saves nothing.
        manager.save_state.assert_called_once_with(FleetioResumeConfig(start_cursor="CUR2"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_terminal_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}, {"id": 2}], None)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_starts_from_saved_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 9}], None)])

        manager = _make_manager(FleetioResumeConfig(start_cursor="SAVED"))
        rows = _rows(_source(manager))

        assert rows == [{"id": 9}]
        assert params[0]["start_cursor"] == "SAVED"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_filter_reaches_the_request(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}], None)])

        rows = _rows(
            _source(
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        assert rows == [{"id": 1}]
        assert params[0]["sort[updated_at]"] == "asc"
        assert params[0]["filter[updated_at][gt]"] == "2026-03-04T02:58:14+00:00"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_version_header_is_set_on_session(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], None)])

        _rows(_source(_make_manager()))
        assert session.headers.get("X-Api-Version") == FLEETIO_API_VERSION

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bare_list_body_fails_loudly(self, MockSession) -> None:
        # A bare list means the version pin was ignored (legacy page-based response) — fail loud
        # instead of silently truncating to one page.
        session = MockSession.return_value
        _wire(session, [_response(None, None, body=[{"id": 1}])])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(_make_manager()))


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code,expected", [(200, True), (401, False), (403, False)])
    @mock.patch(FLEETIO_SESSION_PATCH)
    def test_status_maps_to_bool(self, mock_session, status_code: int, expected: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("k", "a") is expected

    @mock.patch(FLEETIO_SESSION_PATCH)
    def test_network_error_is_not_valid(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("k", "a") is False
