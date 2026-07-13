from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.settings import STATUSPAGE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.statuspage import (
    StatuspageResumeConfig,
    StatuspageRetryableError,
    _build_url,
    _fetch_page,
    _get_headers,
    _list_page_ids,
    get_rows,
    statuspage_source,
    validate_credentials,
)

_TRANSPORT = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.statuspage.make_tracked_session"
)


def _make_manager(resume_state: StatuspageResumeConfig | None = None) -> mock.MagicMock:
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


class TestHeaders:
    def test_uses_static_oauth_prefix(self):
        headers = _get_headers("abc123")
        # Statuspage's static API key is sent with an "OAuth" prefix despite not being an OAuth token.
        assert headers["Authorization"] == "OAuth abc123"


class TestBuildUrl:
    def test_encodes_params(self):
        url = _build_url("/pages", {"per_page": 100, "page": 1})
        assert url == "https://api.statuspage.io/v1/pages?per_page=100&page=1"

    def test_child_path(self):
        url = _build_url("/pages/p1/components", {"per_page": 100, "page": 2})
        assert url == "https://api.statuspage.io/v1/pages/p1/components?per_page=100&page=2"


class TestFetchPage:
    @pytest.mark.parametrize("status_code", [420, 429, 500, 502, 503])
    def test_retryable_statuses_raise(self, status_code, monkeypatch):
        # Skip tenacity's real exponential-backoff sleeps (~3 min of wall clock per case)
        # while still exercising the full retry count and reraise behavior.
        monkeypatch.setattr("tenacity.nap.time.sleep", lambda _seconds: None)
        session = mock.MagicMock()
        session.get.return_value = _response([], status_code=status_code)
        # reraise=True surfaces the final StatuspageRetryableError after retries are exhausted.
        with pytest.raises(StatuspageRetryableError):
            _fetch_page(session, "https://api.statuspage.io/v1/pages", mock.MagicMock())
        assert session.get.call_count == 8

    def test_client_error_raises_for_status(self):
        resp = _response({"error": "Could not authenticate"}, status_code=401)
        resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=resp)
        session = mock.MagicMock()
        session.get.return_value = resp
        with pytest.raises(requests.HTTPError):
            _fetch_page(session, "https://api.statuspage.io/v1/pages", mock.MagicMock())

    def test_ok_response_returned(self):
        session = mock.MagicMock()
        session.get.return_value = _response([{"id": "p1"}])
        resp = _fetch_page(session, "https://api.statuspage.io/v1/pages", mock.MagicMock())
        assert resp.json() == [{"id": "p1"}]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(_TRANSPORT)
    def test_status_mapping(self, mock_session, status_code, expected_ok):
        body = [] if status_code == 200 else {"error": "nope"}
        mock_session.return_value.get.return_value = _response(body, status_code=status_code)
        ok, error = validate_credentials("key")
        assert ok is expected_ok
        if not ok:
            assert error

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
        manager = _make_manager(StatuspageResumeConfig(page=3, parent_page_id=None))

        list(get_rows("key", "pages", mock.MagicMock(), manager))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "page=3" in first_url


class TestGetRowsFanOut:
    @mock.patch(_TRANSPORT)
    def test_fans_out_over_pages_and_injects_page_id(self, mock_session):
        mock_session.return_value = _session_returning(
            # _list_page_ids walks /pages first
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
        manager = _make_manager(StatuspageResumeConfig(page=2, parent_page_id="p2"))

        batches = list(get_rows("key", "components", mock.MagicMock(), manager))
        rows = [row for batch in batches for row in batch]

        assert rows == [{"id": "c2b", "page_id": "p2"}]
        # p1 is skipped entirely and the resumed read starts at p2 page 2 (then page 3 terminates on empty).
        child_urls = [c.args[0] for c in mock_session.return_value.get.call_args_list if "/components" in c.args[0]]
        assert all("/pages/p2/components" in u for u in child_urls)
        assert child_urls[0] == "https://api.statuspage.io/v1/pages/p2/components?per_page=100&page=2"

    @mock.patch(_TRANSPORT)
    def test_subscribers_uses_limit_param(self, mock_session):
        mock_session.return_value = _session_returning(
            [{"id": "p1"}],
            [],
            [{"id": "s1"}],
            [],
        )
        manager = _make_manager()

        list(get_rows("key", "subscribers", mock.MagicMock(), manager))

        child_urls = [c.args[0] for c in mock_session.return_value.get.call_args_list if "/subscribers" in c.args[0]]
        assert child_urls and all("limit=100" in u and "per_page" not in u for u in child_urls)


class TestListPageIds:
    def test_collects_ids_across_pages(self):
        session = _session_returning(
            [{"id": "p1"}, {"id": "p2"}],
            [{"id": "p3"}],
            [],
        )
        assert _list_page_ids(session, mock.MagicMock()) == ["p1", "p2", "p3"]


class TestStatuspageSource:
    @pytest.mark.parametrize("endpoint", list(STATUSPAGE_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint):
        config = STATUSPAGE_ENDPOINTS[endpoint]
        response = statuspage_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    @pytest.mark.parametrize(
        "endpoint, expected_keys",
        [
            ("pages", ["id"]),
            ("components", ["page_id", "id"]),
            ("subscribers", ["page_id", "id"]),
        ],
    )
    def test_primary_keys_are_unique_table_wide(self, endpoint, expected_keys):
        # Fan-out children carry the parent page id in their key so rows from different pages
        # never collide on a bare resource id.
        assert STATUSPAGE_ENDPOINTS[endpoint].primary_key == expected_keys
