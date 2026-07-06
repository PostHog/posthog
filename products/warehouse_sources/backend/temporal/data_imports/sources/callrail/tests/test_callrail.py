from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.callrail.callrail import (
    CallRailResumeConfig,
    _build_params,
    _build_url,
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


def _make_manager(resume_state: CallRailResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(response_key: str, items: list[dict[str, Any]], total_pages: int) -> dict[str, Any]:
    return {response_key: items, "total_pages": total_pages, "total_records": 999}


def _response(body: dict[str, Any]) -> mock.MagicMock:
    resp = mock.MagicMock(status_code=200, ok=True)
    resp.json.return_value = body
    return resp


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


class TestBuildParams:
    def test_incremental_endpoint_requests_ascending_sort(self) -> None:
        params = _build_params(
            CALLRAIL_ENDPOINTS["calls"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert params["sort"] == "start_time"
        assert params["order"] == "asc"
        assert params["per_page"] == 250
        assert "start_date" not in params

    def test_start_date_included_only_when_incremental_and_value_present(self) -> None:
        params = _build_params(
            CALLRAIL_ENDPOINTS["calls"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params["start_date"] == "2026-03-04"

    def test_start_date_omitted_when_not_using_incremental(self) -> None:
        params = _build_params(
            CALLRAIL_ENDPOINTS["calls"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert "start_date" not in params

    def test_full_refresh_endpoint_has_no_sort_or_start_date(self) -> None:
        params = _build_params(
            CALLRAIL_ENDPOINTS["users"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now(UTC),
        )
        assert "sort" not in params
        assert "order" not in params
        assert "start_date" not in params


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url("https://api.callrail.com/v3/a/A/calls.json", {}) == (
            "https://api.callrail.com/v3/a/A/calls.json"
        )

    def test_drops_none_values_and_encodes(self) -> None:
        url = _build_url("https://x/calls.json", {"per_page": 250, "start_date": None, "page": 2})
        assert url == "https://x/calls.json?per_page=250&page=2"


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
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.callrail.callrail.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(
        self, mock_session: mock.MagicMock, status_code: int, expected: bool
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.callrail.callrail.make_tracked_session"
    )
    def test_validate_credentials_swallows_exceptions(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False


class TestResolveAccountId:
    def test_returns_provided_account_id_without_request(self) -> None:
        session = mock.MagicMock()
        assert resolve_account_id(session, "key", mock.MagicMock(), account_id="ACC123") == "ACC123"
        session.get.assert_not_called()

    def test_resolves_first_account_when_unset(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response({"accounts": [{"id": "ACC1"}, {"id": "ACC2"}]})
        assert resolve_account_id(session, "key", mock.MagicMock()) == "ACC1"
        # Only the first account is used, so we request a single row rather than a full page.
        assert "per_page=1" in session.get.call_args.args[0]

    def test_raises_when_no_accounts(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response({"accounts": []})
        with pytest.raises(ValueError):
            resolve_account_id(session, "key", mock.MagicMock())


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.callrail.callrail.make_tracked_session"
    )
    def test_paginates_by_page_number(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = [
            _response(_page("calls", [{"id": "1"}, {"id": "2"}], total_pages=2)),
            _response(_page("calls", [{"id": "3"}], total_pages=2)),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", "calls", mock.MagicMock(), manager, account_id="ACC"))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2", "3"]
        # State saved once (after page 1, pointing at page 2); page 2 is the last so no save after it.
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert saved.page == 2
        assert saved.account_id == "ACC"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.callrail.callrail.make_tracked_session"
    )
    def test_resumes_from_saved_page(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response(_page("calls", [{"id": "9"}], total_pages=5))

        manager = _make_manager(CallRailResumeConfig(account_id="ACC9", page=5))
        list(get_rows("key", "calls", mock.MagicMock(), manager, account_id="ACC"))

        # Resumes at the saved page and pinned account, ignoring the passed account_id.
        url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "page=5" in url
        assert "/a/ACC9/" in url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.callrail.callrail.make_tracked_session"
    )
    def test_resolves_account_when_not_resuming(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = [
            _response({"accounts": [{"id": "RESOLVED"}]}),
            _response(_page("users", [{"id": "u1"}], total_pages=1)),
        ]

        manager = _make_manager()
        list(get_rows("key", "users", mock.MagicMock(), manager))

        data_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "/a/RESOLVED/users.json" in data_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.callrail.callrail.make_tracked_session"
    )
    def test_empty_page_stops_without_saving(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response(_page("calls", [], total_pages=0))

        manager = _make_manager()
        batches = list(get_rows("key", "calls", mock.MagicMock(), manager, account_id="ACC"))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.callrail.callrail.make_tracked_session"
    )
    def test_incremental_request_carries_start_date(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = _response(_page("calls", [{"id": "1"}], total_pages=1))

        manager = _make_manager()
        list(
            get_rows(
                "key",
                "calls",
                mock.MagicMock(),
                manager,
                account_id="ACC",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "start_date=2026-01-01" in url
        assert "sort=start_time" in url


class TestCallRailSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = CALLRAIL_ENDPOINTS[endpoint]
        response = callrail_source("key", endpoint, mock.MagicMock(), _make_manager())

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
