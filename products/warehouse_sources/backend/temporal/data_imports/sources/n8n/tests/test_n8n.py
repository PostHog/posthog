from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.n8n import (
    N8nResumeConfig,
    N8nRetryableError,
    _build_url,
    _fetch_page,
    get_rows,
    hostname_of,
    n8n_source,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.settings import ENDPOINTS, N8N_ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.n8n.n8n"

# `_fetch_page` is wrapped by tenacity's @retry; call the underlying function directly so a
# retryable status raises immediately instead of sleeping through the backoff schedule.
_fetch_undecorated = _fetch_page.__wrapped__  # type: ignore[attr-defined]


def _make_manager(resume_state: N8nResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = status_code < 400
    return resp


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://myorg.app.n8n.cloud", "https://myorg.app.n8n.cloud"),
            ("myorg.app.n8n.cloud", "https://myorg.app.n8n.cloud"),
            ("https://n8n.example.com/", "https://n8n.example.com"),
            ("http://n8n.internal:5678", "http://n8n.internal:5678"),
            # A pasted API base URL is tolerated by trimming the /api/v1 suffix.
            ("https://myorg.app.n8n.cloud/api/v1", "https://myorg.app.n8n.cloud"),
            ("https://myorg.app.n8n.cloud/api/v1/", "https://myorg.app.n8n.cloud"),
        ],
    )
    def test_valid_hosts(self, value, expected):
        assert normalize_host(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "ftp://example.com",
            "https://",
            # SSRF: urlparse reads the host as example.com but urllib3 connects to
            # 127.0.0.1 (backslash / userinfo confusion), so these must be rejected.
            r"http://127.0.0.1\@example.com",
            r"http://127.0.0.1%5c@example.com",
            "https://user@127.0.0.1",
        ],
    )
    def test_invalid_hosts_raise(self, value):
        with pytest.raises(ValueError):
            normalize_host(value)

    @pytest.mark.parametrize(
        "cloud, host, expect_raise",
        [
            # On cloud the API key would egress over the public internet, so plaintext
            # http is rejected while https is fine.
            (True, "http://n8n.example.com", True),
            (True, "https://n8n.example.com", False),
            # Self-hosted operators control their network path, so http stays allowed.
            (False, "http://n8n.internal:5678", False),
        ],
    )
    def test_http_requires_https_only_on_cloud(self, cloud, host, expect_raise):
        with mock.patch(f"{_MODULE}.is_cloud", return_value=cloud):
            if expect_raise:
                with pytest.raises(ValueError):
                    normalize_host(host)
            else:
                assert normalize_host(host) == host

    def test_hostname_of(self):
        assert hostname_of("https://myorg.app.n8n.cloud/api/v1") == "myorg.app.n8n.cloud"


class TestBuildUrl:
    def test_no_params_returns_base(self):
        assert _build_url("https://x/api/v1/workflows", {}) == "https://x/api/v1/workflows"

    def test_params_are_urlencoded(self):
        url = _build_url("https://x/api/v1/workflows", {"limit": 250, "cursor": "a b/c"})
        assert url == "https://x/api/v1/workflows?limit=250&cursor=a+b%2Fc"


class TestFetchPage:
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    def test_retryable_statuses_raise_retryable_error(self, status_code):
        session = mock.MagicMock()
        session.get.return_value = _response({}, status_code=status_code)
        with pytest.raises(N8nRetryableError):
            _fetch_undecorated(session, "https://x", {}, mock.MagicMock())

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    def test_client_errors_raise_for_status(self, status_code):
        session = mock.MagicMock()
        resp = _response({}, status_code=status_code)
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Client Error", response=resp)
        session.get.return_value = resp
        with pytest.raises(requests.HTTPError):
            _fetch_undecorated(session, "https://x", {}, mock.MagicMock())

    def test_non_dict_body_is_wrapped_in_data(self):
        session = mock.MagicMock()
        session.get.return_value = _response([{"id": "1"}])
        body = _fetch_undecorated(session, "https://x", {}, mock.MagicMock())
        assert body == {"data": [{"id": "1"}]}


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_credentials(self, mock_session):
        mock_session.return_value.get.return_value = _response({"data": [], "nextCursor": None})

        assert validate_credentials("https://myorg.app.n8n.cloud", "key") is True
        url = mock_session.return_value.get.call_args.args[0]
        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert url == "https://myorg.app.n8n.cloud/api/v1/workflows?limit=1"
        assert headers["X-N8N-API-KEY"] == "key"

    @pytest.mark.parametrize("status_code", [401, 403, 500])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_non_200_fails_validation(self, mock_session, status_code):
        mock_session.return_value.get.return_value = _response({}, status_code=status_code)
        assert validate_credentials("https://myorg.app.n8n.cloud", "bad") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_network_error_fails_validation(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("https://myorg.app.n8n.cloud", "key") is False


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_single_page_yields_and_stops(self, mock_session):
        mock_session.return_value.get.return_value = _response({"data": [{"id": "1"}, {"id": "2"}], "nextCursor": None})

        manager = _make_manager()
        batches = list(get_rows("https://n.example.com", "key", "workflows", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["1", "2"]
        # A single page never advances the cursor, so no resume state is persisted.
        manager.save_state.assert_not_called()
        url = mock_session.return_value.get.call_args.args[0]
        assert url.startswith("https://n.example.com/api/v1/workflows?")
        assert "limit=250" in url
        assert "excludePinnedData=true" in url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_and_saves_cursor_after_each_page(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"id": "1"}], "nextCursor": "CURSOR_A"}),
            _response({"data": [{"id": "2"}], "nextCursor": "CURSOR_B"}),
            _response({"data": [{"id": "3"}], "nextCursor": None}),
        ]

        manager = _make_manager()
        batches = list(get_rows("https://n.example.com", "key", "tags", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["1", "2", "3"]
        # State saved once per page that has a following page (not for the last page).
        saved = [call.args[0].next_cursor for call in manager.save_state.call_args_list]
        assert saved == ["CURSOR_A", "CURSOR_B"]
        # The second request carries the cursor from the first page.
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "cursor=CURSOR_A" in second_url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_cursor(self, mock_session):
        mock_session.return_value.get.return_value = _response({"data": [{"id": "9"}], "nextCursor": None})

        manager = _make_manager(N8nResumeConfig(next_cursor="SAVED"))
        list(get_rows("https://n.example.com", "key", "workflows", mock.MagicMock(), manager))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "cursor=SAVED" in first_url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_page_still_terminates(self, mock_session):
        mock_session.return_value.get.return_value = _response({"data": [], "nextCursor": None})

        manager = _make_manager()
        batches = list(get_rows("https://n.example.com", "key", "projects", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestN8nSource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_primary_key_and_partitioning(self, endpoint):
        config = N8N_ENDPOINTS[endpoint]
        response = n8n_source("https://n.example.com", "key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_executions_partition_on_started_at(self):
        # Executions have no createdAt/updatedAt; startedAt is the stable creation field.
        response = n8n_source("https://n.example.com", "key", "executions", mock.MagicMock(), _make_manager())
        assert response.partition_keys == ["startedAt"]
