from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.hyperspell import (
    HyperspellResumeConfig,
    HyperspellRetryableError,
    _base_url,
    _build_url,
    _fetch_page,
    _get_headers,
    get_rows,
    hyperspell_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.settings import HYPERSPELL_ENDPOINTS

_TRANSPORT = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.hyperspell.make_tracked_session"
)


def _make_manager(resume_state: HyperspellResumeConfig | None = None) -> mock.MagicMock:
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


class TestHyperspellTransport:
    def test_headers_use_bearer(self):
        headers = _get_headers("abc123", None)
        assert headers["Authorization"] == "Bearer abc123"
        assert "X-As-User" not in headers

    def test_headers_add_as_user_when_user_id_given(self):
        # X-As-User scopes an app-level API key to one user's data.
        headers = _get_headers("abc123", "user-42")
        assert headers["X-As-User"] == "user-42"

    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "https://api.hyperspell.com"),
            ("eu", "https://api.eu.hyperspell.com"),
            ("unknown", "https://api.hyperspell.com"),
        ],
    )
    def test_base_url_by_region(self, region, expected):
        assert _base_url(region) == expected

    @pytest.mark.parametrize(
        "params, expected",
        [
            ({"size": 100}, "https://api.hyperspell.com/memories/list?size=100"),
            ({}, "https://api.hyperspell.com/memories/list"),
        ],
    )
    def test_build_url(self, params, expected):
        assert _build_url("https://api.hyperspell.com", "/memories/list", params) == expected

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    @mock.patch("time.sleep")  # neutralize tenacity's exponential backoff so retries are instant
    def test_fetch_page_retryable_statuses_raise(self, _mock_sleep, status_code):
        session = mock.MagicMock()
        session.get.return_value = _response({}, status_code=status_code)
        # reraise=True surfaces the final HyperspellRetryableError after retries are exhausted.
        with pytest.raises(HyperspellRetryableError):
            _fetch_page(session, "https://api.hyperspell.com/memories/list", mock.MagicMock())

    def test_fetch_page_client_error_raises_for_status(self):
        resp = _response({"message": "Not a valid JWT", "error": "InvalidAPIKey"}, status_code=401)
        resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=resp)
        session = mock.MagicMock()
        session.get.return_value = resp
        with pytest.raises(requests.HTTPError):
            _fetch_page(session, "https://api.hyperspell.com/memories/list", mock.MagicMock())

    def test_fetch_page_ok_response_returned(self):
        session = mock.MagicMock()
        session.get.return_value = _response({"items": []})
        resp = _fetch_page(session, "https://api.hyperspell.com/memories/list", mock.MagicMock())
        assert resp.json() == {"items": []}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(_TRANSPORT)
    def test_status_mapping(self, mock_session, status_code, expected_ok):
        body: dict[str, Any] = {"items": [], "next_cursor": None} if status_code == 200 else {"message": "nope"}
        mock_session.return_value.get.return_value = _response(body, status_code=status_code)
        ok, error = validate_credentials("key", "us", None)
        assert ok is expected_ok
        if not ok:
            assert error

    @pytest.mark.parametrize(
        "region, expected_host",
        [("us", "https://api.hyperspell.com"), ("eu", "https://api.eu.hyperspell.com")],
    )
    @mock.patch(_TRANSPORT)
    def test_probes_memories_endpoint_in_region(self, mock_session, region, expected_host):
        mock_session.return_value.get.return_value = _response({"items": [], "next_cursor": None})
        validate_credentials("key", region, None)
        url = mock_session.return_value.get.call_args.args[0]
        assert url == f"{expected_host}/memories/list?size=1"

    @mock.patch(_TRANSPORT)
    def test_request_exception_is_failure(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        ok, error = validate_credentials("key", "us", None)
        assert ok is False
        assert "boom" in (error or "")


class TestGetRowsPaginated:
    @mock.patch(_TRANSPORT)
    def test_follows_next_cursor_until_exhausted(self, mock_session):
        mock_session.return_value = _session_returning(
            {"items": [{"resource_id": "a"}, {"resource_id": "b"}], "next_cursor": "c1"},
            {"items": [{"resource_id": "c"}], "next_cursor": None},
        )
        manager = _make_manager()

        batches = list(get_rows("key", "us", None, "memories", mock.MagicMock(), manager))

        assert [row["resource_id"] for batch in batches for row in batch] == ["a", "b", "c"]
        urls = [c.args[0] for c in mock_session.return_value.get.call_args_list]
        assert urls[0] == "https://api.hyperspell.com/memories/list?size=100"
        assert urls[1] == "https://api.hyperspell.com/memories/list?size=100&cursor=c1"
        # State saved once per non-empty yielded page, with the cursor that fetched that page.
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert [s.cursor for s in saved] == [None, "c1"]

    @mock.patch(_TRANSPORT)
    def test_resumes_from_saved_cursor(self, mock_session):
        mock_session.return_value = _session_returning(
            {"items": [{"resource_id": "z"}], "next_cursor": None},
        )
        manager = _make_manager(HyperspellResumeConfig(cursor="c9"))

        batches = list(get_rows("key", "us", None, "memories", mock.MagicMock(), manager))

        assert [row["resource_id"] for batch in batches for row in batch] == ["z"]
        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "cursor=c9" in first_url

    @mock.patch(_TRANSPORT)
    def test_empty_listing_yields_nothing(self, mock_session):
        mock_session.return_value = _session_returning({"items": [], "next_cursor": None})
        manager = _make_manager()

        assert list(get_rows("key", "us", None, "memories", mock.MagicMock(), manager)) == []
        manager.save_state.assert_not_called()

    @pytest.mark.parametrize(
        "endpoint, expected_size_param",
        [("memories", "size=100"), ("entities", "limit=500"), ("context_documents", "limit=100")],
    )
    @mock.patch(_TRANSPORT)
    def test_page_size_param_per_endpoint(self, mock_session, endpoint, expected_size_param):
        # Hyperspell uses `size` on some listings and `limit` on others.
        data_key = HYPERSPELL_ENDPOINTS[endpoint].data_key
        mock_session.return_value = _session_returning({data_key: [], "next_cursor": None})
        list(get_rows("key", "us", None, endpoint, mock.MagicMock(), _make_manager()))
        url = mock_session.return_value.get.call_args.args[0]
        assert expected_size_param in url


class TestGetRowsUnpaginated:
    @pytest.mark.parametrize("endpoint", ["connections", "integrations"])
    @mock.patch(_TRANSPORT)
    def test_single_request_without_pagination_params(self, mock_session, endpoint):
        config = HYPERSPELL_ENDPOINTS[endpoint]
        mock_session.return_value = _session_returning({config.data_key: [{"id": "x1"}, {"id": "x2"}]})
        manager = _make_manager()

        batches = list(get_rows("key", "us", None, endpoint, mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["x1", "x2"]
        assert mock_session.return_value.get.call_count == 1
        url = mock_session.return_value.get.call_args.args[0]
        assert "?" not in url

    @mock.patch(_TRANSPORT)
    def test_uses_eu_base_url(self, mock_session):
        mock_session.return_value = _session_returning({"connections": []})
        list(get_rows("key", "eu", None, "connections", mock.MagicMock(), _make_manager()))
        url = mock_session.return_value.get.call_args.args[0]
        assert url.startswith("https://api.eu.hyperspell.com/")


class TestHyperspellSourceResponse:
    @pytest.mark.parametrize("endpoint", list(HYPERSPELL_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint):
        config = HYPERSPELL_ENDPOINTS[endpoint]
        response = hyperspell_source("key", "us", None, endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == config.sort_mode
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_memories_caps_chunk_byte_size(self):
        # Memory rows embed the full nested document payload, so the byte cap must be lowered.
        response = hyperspell_source("key", "us", None, "memories", mock.MagicMock(), _make_manager())
        assert response.chunk_size_bytes == 100 * 1024 * 1024
        other = hyperspell_source("key", "us", None, "connections", mock.MagicMock(), _make_manager())
        assert other.chunk_size_bytes is None

    @pytest.mark.parametrize(
        "endpoint, expected_keys",
        [
            ("memories", ["source", "resource_id"]),
            ("connections", ["id"]),
            ("queries", ["query_id"]),
            ("context_documents", ["document_id"]),
        ],
    )
    def test_primary_keys_are_unique_table_wide(self, endpoint, expected_keys):
        # memories carries a composite key: resource_id is only unique within its source provider.
        assert HYPERSPELL_ENDPOINTS[endpoint].primary_key == expected_keys

    @pytest.mark.parametrize(
        "endpoint, expected_partition",
        [
            ("memories", "ingested_at"),
            ("entities", "created_at"),
            ("queries", "time"),
            ("context_documents", "created_at"),
            ("connections", None),
            ("integrations", None),
        ],
    )
    def test_partition_keys_are_stable_creation_timestamps(self, endpoint, expected_partition):
        assert HYPERSPELL_ENDPOINTS[endpoint].partition_key == expected_partition
