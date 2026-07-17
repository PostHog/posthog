from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce import (
    BabelforceResumeConfig,
    _build_params,
    _build_url,
    _to_epoch,
    babelforce_source,
    get_rows,
    is_environment_valid,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.settings import (
    BABELFORCE_ENDPOINTS,
    ENDPOINTS,
)


def _make_manager(resume_state: BabelforceResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(items: list[dict[str, Any]], current: Optional[int], pages: Optional[int]) -> dict[str, Any]:
    pagination: dict[str, Any] = {"total": 0, "max": 100}
    if current is not None:
        pagination["current"] = current
    if pages is not None:
        pagination["pages"] = pages
    return {"items": items, "pagination": pagination}


def _mock_responses(mock_session: mock.MagicMock, pages: list[dict[str, Any]]) -> None:
    responses = []
    for page in pages:
        resp = mock.MagicMock(status_code=200, ok=True)
        resp.json.return_value = page
        responses.append(resp)
    mock_session.return_value.get.side_effect = responses


class TestToEpoch:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            ("2023-11-14T22:13:20.000Z", 1700000000),
            ("2023-11-14T22:13:20+00:00", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-date", None),
            (True, None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected


class TestEnvironmentValidation:
    @pytest.mark.parametrize(
        "environment, expected",
        [
            ("services", True),
            ("us-east", True),
            (" services ", True),
            ("My-Env-1", True),
            ("", False),
            ("-leading-dash", False),
            ("evil.example.com", False),
            ("evil/path", False),
            ("host:8443", False),
            ("a b", False),
        ],
    )
    def test_is_environment_valid(self, environment, expected):
        assert is_environment_valid(environment) is expected

    def test_build_url_rejects_invalid_environment(self):
        with pytest.raises(ValueError):
            _build_url("evil.example.com", "/agents", {})


class TestBuildParams:
    def test_filter_capable_endpoint_includes_window(self):
        params = _build_params(BABELFORCE_ENDPOINTS["calls"], from_timestamp=1700000000, to_timestamp=1700000100)
        assert params["dateCreated.start"] == 1700000000
        assert params["dateCreated.end"] == 1700000100
        assert params["max"] == 100

    def test_full_refresh_endpoint_never_gets_window(self):
        params = _build_params(BABELFORCE_ENDPOINTS["agents"], from_timestamp=1700000000, to_timestamp=1700000100)
        assert "dateCreated.start" not in params
        assert "dateCreated.end" not in params

    def test_no_watermark_omits_start(self):
        params = _build_params(BABELFORCE_ENDPOINTS["calls"], from_timestamp=None, to_timestamp=1700000100)
        assert "dateCreated.start" not in params
        assert params["dateCreated.end"] == 1700000100


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("services", "/agents", {}) == "https://services.babelforce.com/api/v2/agents"

    def test_drops_none_values_and_encodes(self):
        url = _build_url("services", "/calls/reporting", {"max": 100, "page": None, "dateCreated.start": 1700000000})
        assert url == "https://services.babelforce.com/api/v2/calls/reporting?max=100&dateCreated.start=1700000000"

    def test_environment_becomes_subdomain(self):
        url = _build_url("us-east", "/agents", {})
        assert url.startswith("https://us-east.babelforce.com/")


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
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("services", "id", "token") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce.make_tracked_session"
    )
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("services", "id", "token") is False


class TestSessionHardening:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce.make_tracked_session"
    )
    def test_sessions_redact_credentials_and_disable_redirects_and_capture(self, mock_session):
        # The token rides a custom header the sampler's denylist doesn't know and that
        # requests would forward on a cross-host redirect; dropping any of these would
        # leak a usable credential into HTTP samples or to a redirect target.
        response = mock.MagicMock(status_code=200, ok=True)
        response.json.return_value = _page([], current=1, pages=1)
        mock_session.return_value.get.return_value = response

        validate_credentials("services", "id", "token")
        list(get_rows("services", "id", "token", "agents", mock.MagicMock(), _make_manager()))

        assert len(mock_session.call_args_list) >= 2
        for call in mock_session.call_args_list:
            assert call.kwargs["redact_values"] == ("id", "token")
            assert call.kwargs["allow_redirects"] is False
            assert call.kwargs["capture"] is False


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce.make_tracked_session"
    )
    def test_paginates_until_last_page(self, mock_session):
        _mock_responses(
            mock_session,
            [
                _page([{"id": "1"}, {"id": "2"}], current=1, pages=2),
                _page([{"id": "3"}], current=2, pages=2),
            ],
        )

        manager = _make_manager()
        batches = list(get_rows("services", "id", "token", "agents", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2", "3"]
        # First request omits `page` (first-page index is undocumented); second requests page 2.
        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "page=" not in first_url
        assert "page=2" in second_url
        # State is saved only while a next page exists.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_page == 2

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce.make_tracked_session"
    )
    def test_resumes_from_saved_state(self, mock_session):
        _mock_responses(mock_session, [_page([{"id": "9"}], current=5, pages=5)])
        manager = _make_manager(BabelforceResumeConfig(next_page=5, params={"max": 100, "dateCreated.end": 1700000100}))

        batches = list(get_rows("services", "id", "token", "calls", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["9"]
        url = mock_session.return_value.get.call_args_list[0].args[0]
        # The saved window and page are reused so the resumed run continues the same query.
        assert "page=5" in url
        assert "dateCreated.end=1700000100" in url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce.make_tracked_session"
    )
    def test_stops_without_reyielding_when_page_param_is_ignored(self, mock_session):
        same_page = _page([{"id": "1"}], current=1, pages=3)
        _mock_responses(mock_session, [same_page, same_page])

        manager = _make_manager()
        batches = list(get_rows("services", "id", "token", "sms", mock.MagicMock(), manager))

        # The repeated page is detected and not yielded a second time.
        assert [item["id"] for batch in batches for item in batch] == ["1"]
        assert mock_session.return_value.get.call_count == 2

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce.make_tracked_session"
    )
    def test_stops_when_pagination_current_missing(self, mock_session):
        _mock_responses(mock_session, [_page([{"id": "1"}], current=None, pages=None)])

        manager = _make_manager()
        batches = list(get_rows("services", "id", "token", "agents", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1"]
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce.make_tracked_session"
    )
    def test_empty_response_yields_nothing(self, mock_session):
        _mock_responses(mock_session, [_page([], current=1, pages=1)])

        manager = _make_manager()
        batches = list(get_rows("services", "id", "token", "calls", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce.time")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce.make_tracked_session"
    )
    def test_incremental_run_windows_the_query(self, mock_session, mock_time):
        mock_time.time.return_value = 1700000100
        _mock_responses(mock_session, [_page([{"id": "1"}], current=1, pages=1)])

        manager = _make_manager()
        list(
            get_rows(
                "services",
                "id",
                "token",
                "calls",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2023-11-14T22:13:20.000Z",
            )
        )

        url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "dateCreated.start=1700000000" in url
        assert "dateCreated.end=1700000100" in url


class TestBabelforceSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = BABELFORCE_ENDPOINTS[endpoint]
        response = babelforce_source("services", "id", "token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        # Reporting order is undocumented, so the watermark must only finalize on completion.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", [c for c in BABELFORCE_ENDPOINTS.values() if c.partition_key])
    def test_partition_keys_are_stable_creation_fields(self, config):
        assert config.partition_key == "dateCreated"
