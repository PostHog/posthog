import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from unittest import mock

from requests import HTTPError, Response
from requests.structures import CaseInsensitiveDict

from products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted import (
    PAGE_SIZE,
    DelightedResumeConfig,
    _build_params,
    _next_page_url,
    _to_epoch,
    delighted_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.delighted.settings import (
    DELIGHTED_ENDPOINTS,
    ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the delighted module.
DELIGHTED_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.delighted.delighted.make_tracked_session"
)


def _response(
    body: Any,
    *,
    status_code: int = 200,
    url: str = "https://api.delighted.com/v1/survey_responses.json",
    links_next: str | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.url = url
    resp.reason = "Unauthorized" if status_code == 401 else ""
    resp._content = json.dumps(body).encode()
    hdrs = dict(headers or {})
    if links_next is not None:
        hdrs["Link"] = f'<{links_next}>; rel="next"'
    resp.headers = CaseInsensitiveDict(hdrs)
    return resp


def _make_manager(resume_state: DelightedResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session; return per-request (sent URL, params snapshot) captured at prepare time.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy each time
    the request is prepared. ``prepared.url`` is what the allowed-host check and the paginator see,
    so mirror how ``requests`` merges query params into the URL.
    """
    session.headers = {}
    url_snapshots: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url = request.url
        if request.params:
            sep = "&" if urlsplit(url).query else "?"
            url = f"{url}{sep}{urlencode(request.params)}"
        url_snapshots.append(url)
        param_snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots, param_snapshots


def _query_params(url: str) -> dict[str, str]:
    return {key: values[-1] for key, values in parse_qs(urlsplit(url).query).items()}


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return delighted_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


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
    @mock.patch(DELIGHTED_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        assert validate_credentials("key") is expected

    @mock.patch(DELIGHTED_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False

    @mock.patch(DELIGHTED_SESSION_PATCH)
    def test_validate_credentials_uses_basic_auth_with_blank_password(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("my-key")

        auth = mock_session.return_value.get.call_args.kwargs["auth"]
        prepared = mock.MagicMock()
        prepared.headers = {}
        auth(prepared)
        # base64("my-key:")
        assert prepared.headers["Authorization"] == "Basic bXkta2V5Og=="


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_page_pagination_advances_until_short_page(self, MockSession):
        session = MockSession.return_value
        full_page = [{"person_id": str(i), "bounced_at": i} for i in range(PAGE_SIZE)]
        short_page = [{"person_id": "x", "bounced_at": 999}]
        urls, _ = _wire(
            session,
            [
                _response(full_page, url="https://api.delighted.com/v1/bounces.json?per_page=100"),
                _response(short_page, url="https://api.delighted.com/v1/bounces.json?per_page=100&page=2"),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("bounces", manager))

        assert len(rows) == PAGE_SIZE + 1
        assert rows[-1] == short_page[0]
        assert _query_params(urls[1])["page"] == "2"

        # State is saved only while a next page exists.
        manager.save_state.assert_called_once()
        assert _query_params(manager.save_state.call_args.args[0].next_url)["page"] == "2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_link_header_pagination_follows_next_url(self, MockSession):
        session = MockSession.return_value
        next_url = "https://api.delighted.com/v1/people.json?page_info=abc123&per_page=100"
        urls, _ = _wire(
            session,
            [_response([{"id": "1"}], links_next=next_url), _response([{"id": "2"}])],
        )

        manager = _make_manager()
        rows = _rows(_source("people", manager))

        assert [r["id"] for r in rows] == ["1", "2"]
        assert urls[1] == next_url
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_url == next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_link_header_takes_priority_over_page_counting(self, MockSession):
        session = MockSession.return_value
        next_url = "https://api.delighted.com/v1/survey_responses.json?page_info=zzz"
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        urls, _ = _wire(
            session,
            [_response(full_page, links_next=next_url), _response([])],
        )

        manager = _make_manager()
        _rows(_source("survey_responses", manager))

        assert urls[1] == next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        urls, _ = _wire(session, [_response([{"id": "9"}])])

        resume_url = "https://api.delighted.com/v1/survey_responses.json?page=5&per_page=100"
        manager = _make_manager(DelightedResumeConfig(next_url=resume_url))

        _rows(_source("survey_responses", manager))

        assert urls[0] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fetch_disables_redirects(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([])])

        _rows(_source("survey_responses", _make_manager()))

        assert session.send.call_args.kwargs["allow_redirects"] is False

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_redirect_is_rejected(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [_response([], status_code=302, headers={"Location": "https://internal.example.com/"})],
        )

        with pytest.raises(ValueError, match="[Rr]edirect"):
            _rows(_source("survey_responses", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_offhost_link_header_is_rejected(self, MockSession):
        # A server-controlled Link header pointing off-host must not receive the API credentials:
        # the host pin rejects it before the request leaves the process.
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        _wire(session, [_response(full_page, links_next="https://evil.example.com/steal"), _response([])])

        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("survey_responses", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_offhost_resume_url_is_rejected(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager(DelightedResumeConfig(next_url="https://evil.example.com/steal"))

        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("survey_responses", manager))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_params_for_updated_at_cursor(self, MockSession):
        session = MockSession.return_value
        _, params = _wire(session, [_response([])])

        _rows(
            _source(
                "survey_responses",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field="updated_at",
            )
        )

        assert params[0]["updated_since"] == 1700000000
        assert params[0]["order"] == "asc:updated_at"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_ignores_incremental_field(self, MockSession):
        session = MockSession.return_value
        _, params = _wire(session, [_response([])])

        _rows(
            _source(
                "survey_responses",
                _make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=1700000000,
                incremental_field="updated_at",
            )
        )

        assert "updated_since" not in params[0]
        assert params[0]["order"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_stops(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source("unsubscribes", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_metrics_yields_single_row_without_pagination(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"nps": 42, "response_count": 10}, url="https://api.delighted.com/v1/metrics.json")])

        manager = _make_manager()
        rows = _rows(_source("metrics", manager))

        assert rows == [{"nps": 42, "response_count": 10}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()
        manager.can_resume.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_429_honoring_retry_after_then_succeeds(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status_code=429, headers={"Retry-After": "0"}),
                _response([{"id": "1"}]),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("people", manager))

        assert rows == [{"id": "1"}]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_retryable_status_raises_immediately(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({}, status_code=401, url="https://api.delighted.com/v1/people.json")])

        manager = _make_manager()
        with pytest.raises(HTTPError, match="401"):
            _rows(_source("people", manager))

        assert session.send.call_count == 1


class TestDelightedSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = DELIGHTED_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

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
        response = _source(endpoint, _make_manager())
        assert response.primary_keys == [expected_primary_key]

    @pytest.mark.parametrize("config", list(DELIGHTED_ENDPOINTS.values()))
    def test_partition_keys_are_stable_event_time_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"created_at", "unsubscribed_at", "bounced_at"}
