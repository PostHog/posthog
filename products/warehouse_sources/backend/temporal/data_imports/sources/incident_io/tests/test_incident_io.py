from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io import (
    IncidentIoResumeConfig,
    IncidentIoRetryableError,
    _build_params,
    _build_url,
    _format_filter_value,
    _params_from_url,
    _parse_retry_after,
    _wait_with_retry_after,
    get_rows,
    incident_io_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.settings import (
    ENDPOINTS,
    INCIDENT_IO_ENDPOINTS,
)


def _make_manager(resume_state: IncidentIoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(data_key: str, items: list[dict[str, Any]], after: str | None) -> dict[str, Any]:
    return {data_key: items, "pagination_meta": {"after": after, "page_size": 250}}


def _response(body: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.json.return_value = body
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = {}
    return response


class TestFormatFilterValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            (datetime(2024, 5, 1, 12, 30, tzinfo=UTC), "2024-05-01"),
            (datetime(2024, 5, 1, 12, 30), "2024-05-01"),
            (date(2024, 5, 1), "2024-05-01"),
            ("2024-05-01T12:30:00Z", "2024-05-01"),
            ("2024-05-01T12:30:00+00:00", "2024-05-01"),
            ("2024-05-01", "2024-05-01"),
            ("not-a-date", None),
            (1700000000, None),
        ],
    )
    def test_format_filter_value(self, value, expected):
        assert _format_filter_value(value) == expected


class TestBuildParams:
    def test_incidents_include_page_size_and_sort(self):
        params = _build_params(INCIDENT_IO_ENDPOINTS["incidents"], None, None)
        assert params == {"page_size": 250, "sort_by": "created_at_oldest_first"}

    def test_incremental_filter_included_when_set(self):
        params = _build_params(INCIDENT_IO_ENDPOINTS["incidents"], "updated_at", "2024-05-01")
        assert params["updated_at[gte]"] == "2024-05-01"

    def test_incremental_filter_omitted_without_value(self):
        params = _build_params(INCIDENT_IO_ENDPOINTS["incidents"], "updated_at", None)
        assert "updated_at[gte]" not in params

    def test_non_paginated_endpoint_has_no_params(self):
        assert _build_params(INCIDENT_IO_ENDPOINTS["severities"], None, None) == {}

    @pytest.mark.parametrize("endpoint", ["alerts", "escalations"])
    def test_small_page_endpoints_use_capped_page_size(self, endpoint):
        params = _build_params(INCIDENT_IO_ENDPOINTS[endpoint], None, None)
        assert params == {"page_size": 50}


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/v1/severities", {}) == "https://api.incident.io/v1/severities"

    def test_drops_none_values_and_encodes_brackets(self):
        url = _build_url("/v2/incidents", {"page_size": 250, "after": None, "updated_at[gte]": "2024-05-01"})
        assert url == "https://api.incident.io/v2/incidents?page_size=250&updated_at%5Bgte%5D=2024-05-01"


class TestParamsFromUrl:
    def test_strips_after_and_keeps_filters(self):
        url = _build_url(
            "/v2/incidents",
            {"page_size": 250, "sort_by": "created_at_oldest_first", "updated_at[gte]": "2024-05-01", "after": "01H"},
        )
        params = _params_from_url(url)
        assert params == {
            "page_size": "250",
            "sort_by": "created_at_oldest_first",
            "updated_at[gte]": "2024-05-01",
        }

    def test_url_without_query(self):
        assert _params_from_url("https://api.incident.io/v1/severities") == {}


class TestRetryAfter:
    @pytest.mark.parametrize(
        "header_value, expected",
        [
            (None, None),
            ("", None),
            ("30", 30.0),
            ("0", 0.0),
            ("-5", 0.0),
            ("1.5", 1.5),
            ("Wed, 21 Oct 2026 07:28:00 GMT", None),
        ],
    )
    def test_parse_retry_after(self, header_value, expected):
        assert _parse_retry_after(header_value) == expected

    def test_wait_honors_retry_after(self):
        retry_state = mock.MagicMock()
        retry_state.outcome.exception.return_value = IncidentIoRetryableError("rate limited", retry_after=30.0)
        assert _wait_with_retry_after(retry_state) == 30.0

    def test_wait_caps_retry_after(self):
        retry_state = mock.MagicMock()
        retry_state.outcome.exception.return_value = IncidentIoRetryableError("rate limited", retry_after=9999.0)
        assert _wait_with_retry_after(retry_state) == 120.0

    @pytest.mark.parametrize(
        "exception",
        [
            IncidentIoRetryableError("server error"),
            ValueError("boom"),
        ],
    )
    def test_wait_falls_back_to_exponential_backoff(self, exception):
        retry_state = mock.MagicMock()
        retry_state.outcome.exception.return_value = exception
        retry_state.attempt_number = 1
        wait = _wait_with_retry_after(retry_state)
        assert isinstance(wait, float)
        assert wait >= 0


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
            (401, False),
            (403, True),
            (500, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_status_mapping_at_source_create(self, mock_session, status_code, expected_valid):
        mock_session.return_value.get.return_value = _response({}, status_code)

        is_valid, _ = validate_credentials("key")

        assert is_valid is expected_valid

    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_status_mapping_with_schema_name(self, mock_session, status_code, expected_valid):
        mock_session.return_value.get.return_value = _response({}, status_code)

        is_valid, error = validate_credentials("key", schema_name="alerts")

        assert is_valid is expected_valid
        if status_code == 403:
            assert error is not None and "alerts" in error

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_probes_incidents_with_minimal_page_at_source_create(self, mock_session):
        mock_session.return_value.get.return_value = _response({})

        validate_credentials("key")

        url = mock_session.return_value.get.call_args.args[0]
        assert url == "https://api.incident.io/v2/incidents?page_size=1"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_probes_non_paginated_endpoint_without_page_size(self, mock_session):
        mock_session.return_value.get.return_value = _response({})

        validate_credentials("key", schema_name="severities")

        url = mock_session.return_value.get.call_args.args[0]
        assert url == "https://api.incident.io/v1/severities"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_sends_bearer_auth_header(self, mock_session):
        mock_session.return_value.get.return_value = _response({})

        validate_credentials("secret-key")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer secret-key"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_swallows_network_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")

        is_valid, error = validate_credentials("key")

        assert is_valid is False
        assert error is not None


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_paginates_via_pagination_meta_after(self, mock_session):
        pages = [
            _page("incidents", [{"id": "01A"}, {"id": "01B"}], "01B"),
            _page("incidents", [{"id": "01C"}], None),
        ]
        mock_session.return_value.get.side_effect = [_response(page) for page in pages]

        manager = _make_manager()
        batches = list(get_rows("key", "incidents", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["01A", "01B", "01C"]
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "after=01B" in second_url
        # State is saved only while a next page exists, after the batch was yielded.
        manager.save_state.assert_called_once()
        assert "after=01B" in manager.save_state.call_args.args[0].next_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_incremental_request_includes_filter_and_sort(self, mock_session):
        mock_session.return_value.get.return_value = _response(_page("incidents", [], None))

        manager = _make_manager()
        list(
            get_rows(
                "key",
                "incidents",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 5, 1, 12, 30, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert "updated_at%5Bgte%5D=2024-05-01" in url
        assert "sort_by=created_at_oldest_first" in url
        assert "page_size=250" in url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_full_refresh_ignores_incremental_value(self, mock_session):
        mock_session.return_value.get.return_value = _response(_page("incidents", [], None))

        manager = _make_manager()
        list(
            get_rows(
                "key",
                "incidents",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert "gte" not in url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_resumes_from_saved_state_and_preserves_filters(self, mock_session):
        resume_url = _build_url(
            "/v2/incidents",
            {"page_size": 250, "sort_by": "created_at_oldest_first", "updated_at[gte]": "2024-05-01", "after": "01B"},
        )
        pages = [
            _page("incidents", [{"id": "01C"}], "01C"),
            _page("incidents", [], None),
        ]
        mock_session.return_value.get.side_effect = [_response(page) for page in pages]

        manager = _make_manager(IncidentIoResumeConfig(next_url=resume_url))
        list(get_rows("key", "incidents", mock.MagicMock(), manager))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert first_url == resume_url
        # The next page keeps the original chain's filter and swaps in the new cursor.
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "updated_at%5Bgte%5D=2024-05-01" in second_url
        assert "after=01C" in second_url
        assert "after=01B" not in second_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_non_paginated_endpoint_fetches_once(self, mock_session):
        body = {"severities": [{"id": "01A"}], "pagination_meta": {"after": "01A"}}
        mock_session.return_value.get.return_value = _response(body)

        manager = _make_manager()
        batches = list(get_rows("key", "severities", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_count == 1
        assert [item["id"] for batch in batches for item in batch] == ["01A"]
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_empty_response_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _response(_page("alerts", [], None))

        manager = _make_manager()
        batches = list(get_rows("key", "alerts", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_missing_data_key_yields_nothing(self, mock_session):
        mock_session.return_value.get.return_value = _response({"pagination_meta": {"after": None}})

        manager = _make_manager()
        assert list(get_rows("key", "incidents", mock.MagicMock(), manager)) == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_retries_on_429_honoring_retry_after(self, mock_session):
        rate_limited = _response({}, 429)
        rate_limited.headers = {"Retry-After": "0"}
        ok = _response(_page("incidents", [{"id": "01A"}], None))
        mock_session.return_value.get.side_effect = [rate_limited, ok]

        manager = _make_manager()
        batches = list(get_rows("key", "incidents", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_count == 2
        assert [item["id"] for batch in batches for item in batch] == ["01A"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_retries_on_5xx(self, mock_session):
        server_error = _response({}, 500)
        ok = _response(_page("incidents", [{"id": "01A"}], None))
        mock_session.return_value.get.side_effect = [server_error, ok]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io._fallback_wait",
            return_value=0,
        ):
            manager = _make_manager()
            batches = list(get_rows("key", "incidents", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_count == 2
        assert [item["id"] for batch in batches for item in batch] == ["01A"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
    )
    def test_raises_on_client_error(self, mock_session):
        not_found = _response({}, 404)
        not_found.raise_for_status.side_effect = Exception("404 Client Error")
        mock_session.return_value.get.return_value = not_found

        manager = _make_manager()
        with pytest.raises(Exception, match="404 Client Error"):
            list(get_rows("key", "incidents", mock.MagicMock(), manager))


class TestIncidentIoSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = INCIDENT_IO_ENDPOINTS[endpoint]
        response = incident_io_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(INCIDENT_IO_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"

    @pytest.mark.parametrize("config", list(INCIDENT_IO_ENDPOINTS.values()))
    def test_endpoint_paths_are_versioned(self, config):
        assert config.path.startswith(("/v1/", "/v2/"))
