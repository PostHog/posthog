from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.instatus import (
    InstatusResumeConfig,
    InstatusRetryableError,
    _build_url,
    _fetch_page,
    _get_headers,
    _list_page_ids,
    get_rows,
    instatus_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instatus.settings import INSTATUS_ENDPOINTS

_TRANSPORT = "products.warehouse_sources.backend.temporal.data_imports.sources.instatus.instatus.make_tracked_session"


def _make_manager(resume_state: InstatusResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    return resp


def _session_returning(*bodies: Any) -> mock.MagicMock:
    """Build a session whose successive .get() calls return the given JSON bodies."""
    session = mock.MagicMock()
    session.get.side_effect = [_response(b) for b in bodies]
    return session


class TestInstatus:
    def test_headers_use_bearer_and_json_content_type(self):
        headers = _get_headers("abc123")
        assert headers["Authorization"] == "Bearer abc123"
        # Instatus requires the JSON content type on every request, including GETs.
        assert headers["Content-Type"] == "application/json"

    @pytest.mark.parametrize(
        "path, expected",
        [
            ("/v2/pages", "https://api.instatus.com/v2/pages?per_page=100&page=1"),
            ("/v1/p1/components", "https://api.instatus.com/v1/p1/components?per_page=100&page=1"),
        ],
    )
    def test_build_url(self, path, expected):
        assert _build_url(path, {"per_page": 100, "page": 1}) == expected

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    @mock.patch("time.sleep")  # neutralize tenacity's exponential backoff so retries are instant
    def test_fetch_page_retryable_statuses_raise(self, _mock_sleep, status_code):
        session = mock.MagicMock()
        session.get.return_value = _response([], status_code=status_code)
        # reraise=True surfaces the final InstatusRetryableError after retries are exhausted.
        with pytest.raises(InstatusRetryableError):
            _fetch_page(session, "https://api.instatus.com/v2/pages", mock.MagicMock())

    def test_fetch_page_client_error_raises_for_status(self):
        resp = _response({"error": {"message": "Could not authenticate"}}, status_code=401)
        resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=resp)
        session = mock.MagicMock()
        session.get.return_value = resp
        with pytest.raises(requests.HTTPError):
            _fetch_page(session, "https://api.instatus.com/v2/pages", mock.MagicMock())

    def test_fetch_page_ok_response_returned(self):
        session = mock.MagicMock()
        session.get.return_value = _response([{"id": "p1"}])
        resp = _fetch_page(session, "https://api.instatus.com/v2/pages", mock.MagicMock())
        assert resp.json() == [{"id": "p1"}]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(_TRANSPORT)
    def test_status_mapping(self, mock_session, status_code, expected_ok):
        body = [] if status_code == 200 else {"error": {"message": "nope"}}
        mock_session.return_value.get.return_value = _response(body, status_code=status_code)
        ok, error = validate_credentials("key")
        assert ok is expected_ok
        if not ok:
            assert error

    @mock.patch(_TRANSPORT)
    def test_probes_pages_endpoint(self, mock_session):
        mock_session.return_value.get.return_value = _response([], status_code=200)
        validate_credentials("key")
        url = mock_session.return_value.get.call_args.args[0]
        assert url.startswith("https://api.instatus.com/v2/pages")

    @mock.patch(_TRANSPORT)
    def test_request_exception_is_failure(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        ok, error = validate_credentials("key")
        assert ok is False
        assert "boom" in (error or "")


class TestGetRowsTopLevel:
    @mock.patch(_TRANSPORT)
    def test_paginates_pages_until_empty(self, mock_session):
        mock_session.return_value = _session_returning(
            [{"id": "p1"}, {"id": "p2"}],
            [{"id": "p3"}],
            [],  # empty page terminates
        )
        manager = _make_manager()

        batches = list(get_rows("key", "pages", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["p1", "p2", "p3"]
        # State saved once per non-empty yielded page.
        assert manager.save_state.call_count == 2
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert [(s.page, s.parent_page_id) for s in saved] == [(1, None), (2, None)]

    @mock.patch(_TRANSPORT)
    def test_resumes_from_saved_page(self, mock_session):
        mock_session.return_value = _session_returning(
            [{"id": "p9"}],  # page 3 (resumed)
            [],
        )
        manager = _make_manager(InstatusResumeConfig(page=3, parent_page_id=None))

        list(get_rows("key", "pages", mock.MagicMock(), manager))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "page=3" in first_url


class TestGetRowsFanOut:
    @mock.patch(_TRANSPORT)
    def test_fans_out_over_pages_and_injects_page_id(self, mock_session):
        mock_session.return_value = _session_returning(
            # _list_page_ids walks /v2/pages first
            [{"id": "p1"}, {"id": "p2"}],
            [],
            # components for p1
            [{"id": "c1"}],
            [],
            # components for p2
            [{"id": "c2"}],
            [],
        )
        manager = _make_manager()

        batches = list(get_rows("key", "components", mock.MagicMock(), manager))
        rows = [row for batch in batches for row in batch]

        # page_id injected so the composite [page_id, id] key stays unique table-wide.
        assert rows == [{"id": "c1", "page_id": "p1"}, {"id": "c2", "page_id": "p2"}]
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert [(s.page, s.parent_page_id) for s in saved] == [(1, "p1"), (1, "p2")]

    @mock.patch(_TRANSPORT)
    def test_resumes_fan_out_at_saved_parent_and_page(self, mock_session):
        mock_session.return_value = _session_returning(
            # pages relisted on resume
            [{"id": "p1"}, {"id": "p2"}],
            [],
            # resume at p2, page 2 — p1 is skipped entirely
            [{"id": "c2b"}],
            [],
        )
        manager = _make_manager(InstatusResumeConfig(page=2, parent_page_id="p2"))

        batches = list(get_rows("key", "components", mock.MagicMock(), manager))
        rows = [row for batch in batches for row in batch]

        assert rows == [{"id": "c2b", "page_id": "p2"}]
        child_urls = [c.args[0] for c in mock_session.return_value.get.call_args_list if "/components" in c.args[0]]
        assert child_urls[0] == "https://api.instatus.com/v1/p2/components?per_page=100&page=2"


class TestListPageIds:
    def test_collects_ids_across_pages(self):
        session = _session_returning(
            [{"id": "p1"}, {"id": "p2"}],
            [{"id": "p3"}],
            [],
        )
        assert _list_page_ids(session, mock.MagicMock()) == ["p1", "p2", "p3"]


class TestInstatusSourceResponse:
    @pytest.mark.parametrize("endpoint", list(INSTATUS_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint):
        config = INSTATUS_ENDPOINTS[endpoint]
        response = instatus_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize(
        "endpoint, expected_keys",
        [
            ("pages", ["id"]),
            ("components", ["page_id", "id"]),
            ("subscribers", ["page_id", "id"]),
            ("incidents", ["page_id", "id"]),
        ],
    )
    def test_primary_keys_are_unique_table_wide(self, endpoint, expected_keys):
        # Fan-out children carry the parent page id in their key so rows from different pages
        # never collide on a bare resource id.
        assert INSTATUS_ENDPOINTS[endpoint].primary_key == expected_keys

    @pytest.mark.parametrize(
        "endpoint, expected_partition",
        [
            ("pages", "createdAt"),
            ("components", "createdAt"),
            ("templates", "createdAt"),
            ("incidents", "started"),
            ("maintenances", "start"),
            ("subscribers", None),
            ("metrics", None),
        ],
    )
    def test_partition_keys_are_stable_fields(self, endpoint, expected_partition):
        # Partition only on immutable creation-time fields, never updatedAt.
        assert INSTATUS_ENDPOINTS[endpoint].partition_key == expected_partition
