import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.callrail import (
    CallRailResumeConfig,
    _format_start_date,
    callrail_source,
    get_rows,
    resolve_account_id,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.settings import (
    CALLRAIL_ENDPOINTS,
    ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the callrail module.
CALLRAIL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.callrail.callrail.make_tracked_session"
)


def _response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _page(response_key: str, items: list[dict[str, Any]], total_pages: int) -> Response:
    return _response({response_key: items, "total_pages": total_pages, "total_records": 999})


def _accounts(ids: list[str]) -> Response:
    return _response({"accounts": [{"id": account_id} for account_id in ids]})


def _make_manager(resume_state: CallRailResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return snapshots of each request AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _collect(
    endpoint: str,
    responses: list[Response],
    MockSession: mock.MagicMock,
    manager: mock.MagicMock | None = None,
    **kwargs: Any,
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]], mock.MagicMock]:
    session = MockSession.return_value
    snapshots = _wire(session, responses)
    manager = manager if manager is not None else _make_manager()
    batches = list(get_rows("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs))
    return batches, snapshots, manager


class TestFormatStartDate:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2026, 3, 4, 22, 13, 20, tzinfo=UTC), "2026-03-04"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04T22:13:20Z", "2026-03-04"),
            ("", None),
        ],
    )
    def test_format_start_date(self, value: Any, expected: str | None) -> None:
        assert _format_start_date(value) == expected

    def test_naive_datetime_returns_a_date_string(self) -> None:
        # No tzinfo -> astimezone(UTC) localizes against the host timezone, so we can only assert
        # that a date string is returned without verifying the specific value.
        assert _format_start_date(datetime(2026, 3, 4, 12, 0, 0)) is not None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(CALLRAIL_SESSION_PATCH)
    def test_validate_credentials_status_mapping(
        self, mock_session: mock.MagicMock, status_code: int, expected: bool
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key") is expected

    @mock.patch(CALLRAIL_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False


class TestResolveAccountId:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_returns_provided_account_id_without_request(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [])
        assert resolve_account_id("key", 1, "j", account_id="ACC123") == "ACC123"
        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resolves_first_account_when_unset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_accounts(["ACC1", "ACC2"])])
        assert resolve_account_id("key", 1, "j") == "ACC1"
        # Only the first account is used, so we request a single row rather than a full page.
        assert snapshots[0]["params"]["per_page"] == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_when_no_accounts(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_accounts([])])
        with pytest.raises(ValueError):
            resolve_account_id("key", 1, "j")


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_by_page_number(self, MockSession: mock.MagicMock) -> None:
        batches, snapshots, manager = _collect(
            "calls",
            [
                _page("calls", [{"id": "1"}, {"id": "2"}], total_pages=2),
                _page("calls", [{"id": "3"}], total_pages=2),
            ],
            MockSession,
            account_id="ACC",
        )

        assert [item["id"] for batch in batches for item in batch] == ["1", "2", "3"]
        assert snapshots[0]["params"]["page"] == 1
        assert snapshots[0]["params"]["per_page"] == 250
        assert snapshots[1]["params"]["page"] == 2
        # State saved once (after page 1, pointing at page 2); page 2 is the last so no save after it.
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert saved == CallRailResumeConfig(account_id="ACC", page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_header_wraps_key_in_token_format(self, MockSession: mock.MagicMock) -> None:
        _, snapshots, _ = _collect(
            "calls", [_page("calls", [{"id": "1"}], total_pages=1)], MockSession, account_id="ACC"
        )
        # CallRail expects the token wrapped in token="..." per its v3 docs; sent via framework auth.
        assert snapshots[0]["auth"].api_key == 'Token token="key"'
        assert snapshots[0]["auth"].name == "Authorization"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _, snapshots, _ = _collect(
            "calls",
            [_page("calls", [{"id": "9"}], total_pages=5)],
            MockSession,
            manager=_make_manager(CallRailResumeConfig(account_id="ACC9", page=5)),
            account_id="ACC",
        )

        # Resumes at the saved page and pinned account, ignoring the passed account_id, and
        # without re-resolving accounts.
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["page"] == 5
        assert "/a/ACC9/" in snapshots[0]["url"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resolves_account_when_not_resuming(self, MockSession: mock.MagicMock) -> None:
        _, snapshots, _ = _collect(
            "users",
            [
                _accounts(["RESOLVED"]),
                _page("users", [{"id": "u1"}], total_pages=1),
            ],
            MockSession,
        )

        assert "/a/RESOLVED/users.json" in snapshots[1]["url"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_stops_without_saving(self, MockSession: mock.MagicMock) -> None:
        batches, _, manager = _collect("calls", [_page("calls", [], total_pages=0)], MockSession, account_id="ACC")

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_response_key_stops_without_rows(self, MockSession: mock.MagicMock) -> None:
        # A 200 body without the list key reads as an empty page — end of data, not an error.
        batches, _, manager = _collect("calls", [_response({"total_pages": 3})], MockSession, account_id="ACC")

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_carries_start_date_and_sort(self, MockSession: mock.MagicMock) -> None:
        _, snapshots, _ = _collect(
            "calls",
            [_page("calls", [{"id": "1"}], total_pages=1)],
            MockSession,
            account_id="ACC",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert snapshots[0]["params"]["start_date"] == "2026-01-01"
        assert snapshots[0]["params"]["sort"] == "start_time"
        assert snapshots[0]["params"]["order"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_start_date_omitted_when_not_using_incremental(self, MockSession: mock.MagicMock) -> None:
        _, snapshots, _ = _collect(
            "calls",
            [_page("calls", [{"id": "1"}], total_pages=1)],
            MockSession,
            account_id="ACC",
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert "start_date" not in snapshots[0]["params"]
        # Sort is still ascending on the cursor field so full-refresh pages don't skip/duplicate.
        assert snapshots[0]["params"]["sort"] == "start_time"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_start_date_omitted_when_last_value_missing(self, MockSession: mock.MagicMock) -> None:
        _, snapshots, _ = _collect(
            "calls",
            [_page("calls", [{"id": "1"}], total_pages=1)],
            MockSession,
            account_id="ACC",
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert "start_date" not in snapshots[0]["params"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_has_no_sort_or_start_date(self, MockSession: mock.MagicMock) -> None:
        _, snapshots, _ = _collect(
            "users",
            [_page("users", [{"id": "u1"}], total_pages=1)],
            MockSession,
            account_id="ACC",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        assert "sort" not in snapshots[0]["params"]
        assert "order" not in snapshots[0]["params"]
        assert "start_date" not in snapshots[0]["params"]


class TestCallRailSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = CALLRAIL_ENDPOINTS[endpoint]
        response = callrail_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(CALLRAIL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config: Any) -> None:
        # Never partition on a mutable field; only stable creation/start timestamps are allowed.
        if config.partition_key:
            assert config.partition_key in {"start_time", "submitted_at", "created_at"}

    @pytest.mark.parametrize("config", list(CALLRAIL_ENDPOINTS.values()))
    def test_incremental_endpoints_have_a_sort_field(self, config: Any) -> None:
        # An incremental endpoint must sort ascending on its cursor so the watermark advances.
        if config.supports_incremental:
            assert config.sort_field is not None
            assert config.incremental_fields
