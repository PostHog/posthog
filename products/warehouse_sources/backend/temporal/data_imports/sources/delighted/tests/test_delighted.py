from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted import (
    PAGE_SIZE,
    DelightedResumeConfig,
    DelightedRetryableError,
    DelightedUnexpectedRedirectError,
    _build_params,
    _build_url,
    _is_delighted_url,
    _next_page_url,
    _parse_retry_after,
    _retry_wait,
    _to_epoch,
    delighted_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.delighted.settings import (
    DELIGHTED_ENDPOINTS,
    ENDPOINTS,
)


def _make_manager(resume_state: DelightedResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(
    body: Any,
    status_code: int = 200,
    links: dict[str, dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> mock.MagicMock:
    response = mock.MagicMock()
    response.json.return_value = body
    response.status_code = status_code
    response.ok = status_code < 400
    response.is_redirect = status_code in (301, 302, 303, 307, 308)
    response.is_permanent_redirect = status_code in (301, 308)
    response.links = links or {}
    response.headers = headers or {}
    return response


def _query_params(url: str) -> dict[str, str]:
    return {key: values[-1] for key, values in parse_qs(urlsplit(url).query).items()}


class TestToEpoch:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-number", None),
            (True, None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected


class TestBuildParams:
    def test_survey_responses_full_refresh_defaults(self):
        params = _build_params(DELIGHTED_ENDPOINTS["survey_responses"], incremental_field=None, since_value=None)

        assert params["per_page"] == PAGE_SIZE
        assert params["order"] == "asc"
        assert params["expand[]"] == "person"
        assert "since" not in params
        assert "updated_since" not in params

    def test_survey_responses_updated_at_cursor_uses_updated_since(self):
        params = _build_params(
            DELIGHTED_ENDPOINTS["survey_responses"], incremental_field="updated_at", since_value=1700000000
        )

        assert params["updated_since"] == 1700000000
        assert params["order"] == "asc:updated_at"
        assert "since" not in params

    def test_survey_responses_created_at_cursor_uses_since(self):
        params = _build_params(
            DELIGHTED_ENDPOINTS["survey_responses"], incremental_field="created_at", since_value=1700000000
        )

        assert params["since"] == 1700000000
        assert params["order"] == "asc"
        assert "updated_since" not in params

    @pytest.mark.parametrize(
        "endpoint, cursor_field",
        [
            ("people", "created_at"),
            ("unsubscribes", "unsubscribed_at"),
            ("bounces", "bounced_at"),
        ],
    )
    def test_append_only_endpoints_filter_via_since_without_order(self, endpoint, cursor_field):
        params = _build_params(DELIGHTED_ENDPOINTS[endpoint], incremental_field=cursor_field, since_value=1700000000)

        assert params["since"] == 1700000000
        assert params["per_page"] == PAGE_SIZE
        assert "order" not in params

    def test_unknown_cursor_field_is_ignored(self):
        params = _build_params(DELIGHTED_ENDPOINTS["people"], incremental_field="nope", since_value=1700000000)

        assert "since" not in params

    def test_metrics_has_no_pagination_params(self):
        assert _build_params(DELIGHTED_ENDPOINTS["metrics"], incremental_field=None, since_value=None) == {}


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/metrics.json", {}) == "https://api.delighted.com/v1/metrics.json"

    def test_drops_none_values_and_encodes(self):
        url = _build_url("/people.json", {"per_page": 100, "since": None})
        assert url == "https://api.delighted.com/v1/people.json?per_page=100"


class TestIsDelightedUrl:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://api.delighted.com/v1/people.json?page=2", True),
            ("https://API.DELIGHTED.COM/v1/people.json", True),
            ("http://api.delighted.com/v1/people.json", False),
            ("https://evil.example.com/steal", False),
            ("https://api.delighted.com.evil.example.com/steal", False),
            ("not a url", False),
            ("", False),
        ],
    )
    def test_only_https_api_host_is_allowed(self, url, expected):
        assert _is_delighted_url(url) is expected


class TestNextPageUrl:
    @pytest.mark.parametrize(
        "url, expected_page",
        [
            ("https://api.delighted.com/v1/bounces.json?per_page=100", "2"),
            ("https://api.delighted.com/v1/bounces.json?per_page=100&page=2", "3"),
            ("https://api.delighted.com/v1/bounces.json?page=9&per_page=100&since=1700000000", "10"),
        ],
    )
    def test_increments_page_param(self, url, expected_page):
        next_url = _next_page_url(url)

        assert _query_params(next_url)["page"] == expected_page
        assert urlsplit(next_url).path == "/v1/bounces.json"

    def test_preserves_other_params(self):
        next_url = _next_page_url("https://api.delighted.com/v1/survey_responses.json?per_page=100&since=1700000000")
        params = _query_params(next_url)

        assert params["per_page"] == "100"
        assert params["since"] == "1700000000"


class TestParseRetryAfter:
    @pytest.mark.parametrize(
        "header, expected",
        [
            (None, None),
            ("5", 5.0),
            ("0", 0.0),
            ("2.5", 2.5),
            ("-3", 0.0),
            ("soon", None),
        ],
    )
    def test_parse_retry_after_values(self, header, expected):
        headers = {} if header is None else {"Retry-After": header}
        assert _parse_retry_after(_response([], headers=headers)) == expected


class TestRetryWait:
    def _retry_state(self, exception: Exception | None) -> mock.MagicMock:
        state = mock.MagicMock()
        state.attempt_number = 1
        state.outcome.exception.return_value = exception
        return state

    def test_uses_server_retry_after_when_present(self):
        state = self._retry_state(DelightedRetryableError("rate limited", retry_after=7.0))
        assert _retry_wait(state) == 7.0

    def test_caps_server_retry_after(self):
        state = self._retry_state(DelightedRetryableError("rate limited", retry_after=9999.0))
        assert _retry_wait(state) == 120.0

    @pytest.mark.parametrize(
        "exception",
        [
            DelightedRetryableError("server error", retry_after=None),
            ValueError("boom"),
        ],
    )
    def test_falls_back_to_exponential_backoff(self, exception):
        state = self._retry_state(exception)
        assert 0 <= _retry_wait(state) <= 60


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
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = _response({}, status_code=status_code)

        assert validate_credentials("key") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_validate_credentials_uses_basic_auth_with_blank_password(self, mock_session):
        mock_session.return_value.get.return_value = _response({}, status_code=200)

        validate_credentials("my-key")

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        # base64("my-key:")
        assert headers["Authorization"] == "Basic bXkta2V5Og=="


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_page_pagination_advances_until_short_page(self, mock_session):
        full_page = [{"person_id": str(i), "bounced_at": i} for i in range(PAGE_SIZE)]
        short_page = [{"person_id": "x", "bounced_at": 999}]
        mock_session.return_value.get.side_effect = [_response(full_page), _response(short_page)]

        manager = _make_manager()
        batches = list(get_rows("key", "bounces", mock.MagicMock(), manager))

        assert len(batches) == 2
        assert len(batches[0]) == PAGE_SIZE
        assert batches[1] == short_page

        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert _query_params(second_url)["page"] == "2"

        # State is saved only while a next page exists.
        manager.save_state.assert_called_once()
        assert _query_params(manager.save_state.call_args.args[0].next_url)["page"] == "2"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_link_header_pagination_follows_next_url(self, mock_session):
        next_url = "https://api.delighted.com/v1/people.json?page_info=abc123&per_page=100"
        first = _response([{"id": "1"}], links={"next": {"url": next_url}})
        second = _response([{"id": "2"}])
        mock_session.return_value.get.side_effect = [first, second]

        manager = _make_manager()
        batches = list(get_rows("key", "people", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2"]
        assert mock_session.return_value.get.call_args_list[1].args[0] == next_url
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_url == next_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_link_header_takes_priority_over_page_counting(self, mock_session):
        next_url = "https://api.delighted.com/v1/survey_responses.json?page_info=zzz"
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        first = _response(full_page, links={"next": {"url": next_url}})
        second = _response([])
        mock_session.return_value.get.side_effect = [first, second]

        manager = _make_manager()
        list(get_rows("key", "survey_responses", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[1].args[0] == next_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_resumes_from_saved_state(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "9"}])

        resume_url = "https://api.delighted.com/v1/survey_responses.json?page=5&per_page=100"
        manager = _make_manager(DelightedResumeConfig(next_url=resume_url))

        list(get_rows("key", "survey_responses", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_fetch_page_disables_redirects(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        list(get_rows("key", "survey_responses", mock.MagicMock(), _make_manager()))

        assert mock_session.return_value.get.call_args.kwargs["allow_redirects"] is False

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_unexpected_redirect_is_rejected(self, mock_session):
        mock_session.return_value.get.return_value = _response([], status_code=302)

        with pytest.raises(DelightedUnexpectedRedirectError):
            list(get_rows("key", "survey_responses", mock.MagicMock(), _make_manager()))

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_offhost_link_header_is_not_followed(self, mock_session):
        # A server-controlled Link header pointing off-host must not receive the API credentials.
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        first = _response(full_page, links={"next": {"url": "https://evil.example.com/steal"}})
        second = _response([])
        mock_session.return_value.get.side_effect = [first, second]

        list(get_rows("key", "survey_responses", mock.MagicMock(), _make_manager()))

        # Falls back to page-number increment on the API host rather than the off-host URL.
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert second_url.startswith("https://api.delighted.com/")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_offhost_resume_url_is_ignored(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager(DelightedResumeConfig(next_url="https://evil.example.com/steal"))
        list(get_rows("key", "survey_responses", mock.MagicMock(), manager))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert first_url.startswith("https://api.delighted.com/")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_incremental_request_params_for_updated_at_cursor(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        list(
            get_rows(
                "key",
                "survey_responses",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field="updated_at",
            )
        )

        params = _query_params(mock_session.return_value.get.call_args.args[0])
        assert params["updated_since"] == "1700000000"
        assert params["order"] == "asc:updated_at"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_full_refresh_ignores_incremental_field(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        list(
            get_rows(
                "key",
                "survey_responses",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=1700000000,
                incremental_field="updated_at",
            )
        )

        params = _query_params(mock_session.return_value.get.call_args.args[0])
        assert "updated_since" not in params
        assert params["order"] == "asc"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_empty_response_stops(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        batches = list(get_rows("key", "unsubscribes", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_metrics_yields_single_row_without_pagination(self, mock_session):
        mock_session.return_value.get.return_value = _response({"nps": 42, "response_count": 10})

        manager = _make_manager()
        batches = list(get_rows("key", "metrics", mock.MagicMock(), manager))

        assert batches == [[{"nps": 42, "response_count": 10}]]
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()
        manager.can_resume.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_retries_429_honoring_retry_after_then_succeeds(self, mock_session):
        rate_limited = _response({}, status_code=429, headers={"Retry-After": "0"})
        ok = _response([{"id": "1"}])
        mock_session.return_value.get.side_effect = [rate_limited, ok]

        manager = _make_manager()
        batches = list(get_rows("key", "people", mock.MagicMock(), manager))

        assert batches == [[{"id": "1"}]]
        assert mock_session.return_value.get.call_count == 2

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
    )
    def test_non_retryable_status_raises_immediately(self, mock_session):
        unauthorized = _response({}, status_code=401)
        unauthorized.raise_for_status.side_effect = Exception("401 Client Error")
        mock_session.return_value.get.return_value = unauthorized

        manager = _make_manager()
        with pytest.raises(Exception, match="401 Client Error"):
            list(get_rows("key", "people", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_count == 1


class TestDelightedSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = DELIGHTED_ENDPOINTS[endpoint]
        response = delighted_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.sort_mode == "asc"
        if config.primary_key:
            assert response.primary_keys == [config.primary_key]
        else:
            assert response.primary_keys is None
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize(
        "endpoint, expected_primary_key",
        [
            ("survey_responses", "id"),
            ("people", "id"),
            ("unsubscribes", "person_id"),
            ("bounces", "person_id"),
        ],
    )
    def test_primary_key_per_endpoint(self, endpoint, expected_primary_key):
        response = delighted_source("key", endpoint, mock.MagicMock(), _make_manager())
        assert response.primary_keys == [expected_primary_key]

    @pytest.mark.parametrize("config", list(DELIGHTED_ENDPOINTS.values()))
    def test_partition_keys_are_stable_event_time_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"created_at", "unsubscribed_at", "bounced_at"}
