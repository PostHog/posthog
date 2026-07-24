import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.n8n import (
    N8nResumeConfig,
    _build_url,
    hostname_of,
    n8n_source,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.settings import ENDPOINTS, N8N_ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.n8n.n8n"
# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(
    items: list[dict[str, Any]] | None, *, next_cursor: str | None = None, drop_data: bool = False
) -> Response:
    body: dict[str, Any] = {"nextCursor": next_cursor}
    if not drop_data:
        body["data"] = items or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: N8nResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock):
    return n8n_source("https://n.example.com", "key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_credentials(self, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        assert validate_credentials("https://myorg.app.n8n.cloud", "key") is True
        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://myorg.app.n8n.cloud/api/v1/workflows?limit=1"
        assert call.kwargs["headers"]["X-N8N-API-KEY"] == "key"

    @pytest.mark.parametrize("status_code", [401, 403, 500])
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_non_200_fails_validation(self, mock_session, status_code):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert validate_credentials("https://myorg.app.n8n.cloud", "bad") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_network_error_fails_validation(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("https://myorg.app.n8n.cloud", "key") is False

    def test_invalid_url_fails_validation(self):
        # A host that can't be normalized never reaches the network — just reports "not validated".
        assert validate_credentials("ftp://nope", "key") is False


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_and_stops(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}, {"id": "2"}], next_cursor=None)])

        manager = _make_manager()
        rows = _rows(_source("workflows", manager))

        assert [row["id"] for row in rows] == ["1", "2"]
        # A single page never advances the cursor, so no resume state is persisted.
        manager.save_state.assert_not_called()
        assert params[0]["limit"] == 250
        assert params[0]["excludePinnedData"] == "true"
        assert "cursor" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_saves_cursor_after_each_page(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": "1"}], next_cursor="CURSOR_A"),
                _response([{"id": "2"}], next_cursor="CURSOR_B"),
                _response([{"id": "3"}], next_cursor=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("tags", manager))

        assert [row["id"] for row in rows] == ["1", "2", "3"]
        # State saved once per page that has a following page (not for the last page).
        saved = [call.args[0].next_cursor for call in manager.save_state.call_args_list]
        assert saved == ["CURSOR_A", "CURSOR_B"]
        # The second request carries the cursor from the first page.
        assert params[1]["cursor"] == "CURSOR_A"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "9"}], next_cursor=None)])

        manager = _make_manager(N8nResumeConfig(next_cursor="SAVED"))
        _rows(_source("workflows", manager))

        assert params[0]["cursor"] == "SAVED"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_still_terminates(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([], next_cursor=None)])

        manager = _make_manager()
        rows = _rows(_source("projects", manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response(None, drop_data=True)])

        # A 200 body without "data" means the response shape changed — fail loud, not silently 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("workflows", _make_manager()))


class TestN8nSource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_primary_key_and_partitioning(self, endpoint):
        config = N8N_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

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
        response = _source("executions", _make_manager())
        assert response.partition_keys == ["startedAt"]
