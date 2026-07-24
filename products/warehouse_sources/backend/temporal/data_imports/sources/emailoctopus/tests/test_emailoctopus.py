import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus import emailoctopus
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.emailoctopus import (
    EMAILOCTOPUS_BASE_URL as BASE,
    EmailOctopusResumeConfig,
    _base_url_for_version,
    _build_contact_params,
    _format_incremental_value,
    emailoctopus_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.settings import (
    EMAILOCTOPUS_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the emailoctopus module.
EO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.emailoctopus.make_tracked_session"
)


def _resp(body: dict[str, Any], status: int = 200) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = "http://test"
    return resp


def _make_manager(resume_state: EmailOctopusResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, page_map: dict[str, Any], calls: list[tuple[str, Any]] | None = None) -> None:
    """Route each request to a canned response keyed by url (+ status param for contacts).

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy at
    prepare_request time. ``send`` returns the response for the last prepared request, matching how
    the client prepares-then-sends each page in lockstep.
    """
    session.headers = {}
    state: dict[str, Any] = {"key": None}

    def _prepare(request: Any) -> mock.MagicMock:
        url = request.url
        params = dict(request.params or {})
        if calls is not None:
            calls.append((url, params))
        key = f"{url}?status={params['status']}" if "status" in params else url
        state["key"] = key
        prepared = mock.MagicMock()
        prepared.url = url
        return prepared

    def _send(prepared: Any, **kwargs: Any) -> requests.Response:
        result = page_map[state["key"]]
        if isinstance(result, Exception):
            raise result
        return result

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, api_version: str = "v2", **kwargs: Any) -> Any:
    return emailoctopus_source(
        api_key="eo_key",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        api_version=api_version,
        **kwargs,
    )


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("microseconds_dropped", datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45Z"),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2024-01-19T12:14:28Z", "2024-01-19T12:14:28Z"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected

    def test_no_offset_suffix(self) -> None:
        # EmailOctopus's ISO 8601 filters use a Z suffix, never the +00:00 offset isoformat() emits.
        result = _format_incremental_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert "+00:00" not in result
        assert result.endswith("Z")


class TestBuildContactParams:
    def test_status_only_when_no_incremental(self) -> None:
        params = _build_contact_params("subscribed", incremental_field=None, filter_value=None)
        assert params == {"limit": 100, "status": "subscribed"}

    def test_no_filter_when_value_missing(self) -> None:
        params = _build_contact_params("pending", incremental_field="created_at", filter_value=None)
        assert "created_at.gte" not in params

    @parameterized.expand(
        [
            ("last_updated", "last_updated_at", "last_updated_at.gte"),
            ("created", "created_at", "created_at.gte"),
        ]
    )
    def test_server_side_filter(self, _name: str, field: str, expected_param: str) -> None:
        params = _build_contact_params("subscribed", incremental_field=field, filter_value="2026-01-01T00:00:00Z")
        assert params[expected_param] == "2026-01-01T00:00:00Z"
        assert params["status"] == "subscribed"


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        with mock.patch(EO_SESSION_PATCH, return_value=session):
            assert validate_credentials("eo_key") is expected

    def test_network_error_is_invalid(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(EO_SESSION_PATCH, return_value=session):
            assert validate_credentials("eo_key") is False

    def test_tracked_session_redacts_api_key(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(EO_SESSION_PATCH, return_value=session) as make_session:
            validate_credentials("eo_secret")
        # The key must be passed as a redaction value so it can't leak into tracked HTTP logs.
        make_session.assert_called_once_with(redact_values=("eo_secret",))


class TestApiVersionDispatch:
    # EmailOctopus serves every version from the one REST host, so both supported labels — and any
    # undeclared pin honored verbatim by resolve_api_version — must resolve to it.
    @parameterized.expand([("v1",), ("v2",), ("some-undeclared-label",)])
    def test_base_url_resolves_to_rest_host(self, api_version: str) -> None:
        assert _base_url_for_version(api_version) == BASE

    @parameterized.expand([("v1",), ("v2",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_threads_version_into_request_host(self, api_version: str, MockSession) -> None:
        # Route each version to a distinct sentinel host so the assertion fails if the version stops
        # being threaded into the base-URL selection (e.g. reverts to a hardcoded host).
        session = MockSession.return_value
        sentinel = f"https://host-{api_version}.test"
        calls: list[tuple[str, Any]] = []
        _wire(session, {f"{sentinel}/lists": _resp({"data": [{"id": "L1"}], "paging": {"next": None}})}, calls)

        with mock.patch.object(emailoctopus, "_base_url_for_version", lambda v: f"https://host-{v}.test"):
            _rows(_source("lists", _make_manager(), api_version=api_version))

        assert calls
        assert all(url.startswith(sentinel) for url, _ in calls)


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_following_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = f"{BASE}/lists?starting_after=cur1&limit=100"
        _wire(
            session,
            {
                f"{BASE}/lists": _resp({"data": [{"id": "L1"}], "paging": {"next": {"url": next_url}}}),
                next_url: _resp({"data": [{"id": "L2"}], "paging": {"next": None}}),
            },
        )
        rows = _rows(_source("lists", _make_manager()))
        assert rows == [{"id": "L1"}, {"id": "L2"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url_without_refetching_first_page(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = f"{BASE}/campaigns?starting_after=cur5&limit=100"
        calls: list[tuple[str, Any]] = []
        _wire(session, {resume_url: _resp({"data": [{"id": "C9"}], "paging": {"next": None}})}, calls)

        rows = _rows(_source("campaigns", _make_manager(EmailOctopusResumeConfig(next_url=resume_url))))

        assert rows == [{"id": "C9"}]
        # The initial /campaigns URL is never fetched — we jump straight to the saved cursor.
        assert all(url == resume_url for url, _ in calls)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_url_checkpoint_only_while_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = f"{BASE}/lists?starting_after=cur1&limit=100"
        _wire(
            session,
            {
                f"{BASE}/lists": _resp({"data": [{"id": "L1"}], "paging": {"next": {"url": next_url}}}),
                next_url: _resp({"data": [{"id": "L2"}], "paging": {"next": None}}),
            },
        )
        manager = _make_manager()
        _rows(_source("lists", manager))

        # Page one has a next URL (its cursor is checkpointed); the last page does not.
        manager.save_state.assert_called_once_with(EmailOctopusResumeConfig(next_url=next_url))


class TestContactsFanOut:
    def _one_list_pages(self, contacts: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        pages: dict[str, Any] = {f"{BASE}/lists": _resp({"data": [{"id": "L1"}], "paging": {"next": None}})}
        for status in ("subscribed", "unsubscribed", "pending"):
            pages[f"{BASE}/lists/L1/contacts?status={status}"] = _resp(
                {"data": contacts.get(status, []), "paging": {"next": None}}
            )
        return pages

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_lists_and_statuses_attaching_list_id(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            self._one_list_pages(
                {"subscribed": [{"id": "c-sub"}], "unsubscribed": [{"id": "c-unsub"}], "pending": [{"id": "c-pend"}]}
            ),
        )
        rows = _rows(_source("contacts", _make_manager()))
        assert rows == [
            {"id": "c-sub", "list_id": "L1"},
            {"id": "c-unsub", "list_id": "L1"},
            {"id": "c-pend", "list_id": "L1"},
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_applies_server_side_incremental_filter_on_every_status(self, MockSession) -> None:
        session = MockSession.return_value
        calls: list[tuple[str, Any]] = []
        _wire(session, self._one_list_pages({}), calls)

        _rows(
            _source(
                "contacts",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="last_updated_at",
            )
        )
        contact_calls = [params for url, params in calls if "contacts" in url]
        assert contact_calls
        assert all(params["last_updated_at.gte"] == "2026-01-01T00:00:00Z" for params in contact_calls)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_filter_on_first_sync_without_watermark(self, MockSession) -> None:
        session = MockSession.return_value
        calls: list[tuple[str, Any]] = []
        _wire(session, self._one_list_pages({}), calls)

        _rows(
            _source(
                "contacts",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
                incremental_field="last_updated_at",
            )
        )
        contact_calls = [params for url, params in calls if "contacts" in url]
        assert contact_calls
        assert all("last_updated_at.gte" not in params for params in contact_calls)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_list_deleted_mid_fan_out_is_skipped(self, MockSession) -> None:
        session = MockSession.return_value
        pages: dict[str, Any] = {
            f"{BASE}/lists": _resp({"data": [{"id": "L1"}, {"id": "GONE"}], "paging": {"next": None}}),
        }
        for status in ("subscribed", "unsubscribed", "pending"):
            pages[f"{BASE}/lists/L1/contacts?status={status}"] = _resp(
                {"data": [{"id": "c1"}] if status == "subscribed" else [], "paging": {"next": None}}
            )
            # A deleted list 404s independently for each status query; all are skipped.
            pages[f"{BASE}/lists/GONE/contacts?status={status}"] = _resp({}, status=404)
        _wire(session, pages)

        rows = _rows(_source("contacts", _make_manager()))
        assert rows == [{"id": "c1", "list_id": "L1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_404_error_propagates(self, MockSession) -> None:
        session = MockSession.return_value
        pages = self._one_list_pages({})
        # A non-404 client error is not swallowed by the 404 skip — it fails the sync.
        pages[f"{BASE}/lists/L1/contacts?status=subscribed"] = _resp({}, status=403)
        _wire(session, pages)

        with pytest.raises(requests.HTTPError):
            _rows(_source("contacts", _make_manager()))


class TestSourceResponse:
    @parameterized.expand(
        [
            ("lists", ["id"]),
            ("campaigns", ["id"]),
            ("contacts", ["list_id", "id"]),
        ]
    )
    def test_primary_keys_and_partitioning(self, endpoint: str, expected_pks: list[str]) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.partition_keys == [EMAILOCTOPUS_ENDPOINTS[endpoint].partition_key]
        assert EMAILOCTOPUS_ENDPOINTS[endpoint].partition_key == "created_at"
