from collections.abc import Iterable
from typing import Any, Optional, cast
from urllib.parse import parse_qs

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.settings import (
    REGION_HOSTS,
    resolve_base_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sigma_computing.sigma_computing import (
    SigmaComputingResumeConfig,
    get_resource,
    sigma_computing_source,
    validate_credentials,
)

BASE_URL = "https://api.sigmacomputing.com"


class _FakeResumeManager(ResumableSourceManager[SigmaComputingResumeConfig]):
    # In-memory stand-in — deliberately doesn't call super().__init__, so no Redis is touched.
    def __init__(self, state: Optional[dict[str, Any]] = None) -> None:
        self._state = state
        self.saved: list[dict[str, Any]] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> Optional[SigmaComputingResumeConfig]:
        return SigmaComputingResumeConfig(paginator_state=self._state) if self._state is not None else None

    def save_state(self, data: SigmaComputingResumeConfig) -> None:
        self.saved.append(data.paginator_state)


def _collect_rows(response: SourceResponse) -> list[dict[str, Any]]:
    items = response.items()
    assert isinstance(items, Iterable)
    pages = cast(list[list[dict[str, Any]]], list(items))
    return [row for page in pages for row in page]


def _mock_token(requests_mock: Any, base_url: str = BASE_URL, token: str = "tok") -> None:
    requests_mock.post(
        f"{base_url}/v2/auth/token",
        json={"access_token": token, "token_type": "Bearer", "expires_in": 3600},
    )


class TestResolveBaseUrl:
    @parameterized.expand([(region, f"https://{host}") for region, host in REGION_HOSTS.items()])
    def test_known_regions(self, region: str, expected: str) -> None:
        assert resolve_base_url(region) == expected

    def test_unknown_region_raises(self) -> None:
        with pytest.raises(ValueError):
            resolve_base_url("mars")


class TestGetResource:
    def test_top_level_resource_shape(self) -> None:
        resource = cast(dict[str, Any], get_resource("Workbooks"))

        assert resource["name"] == "Workbooks"
        assert resource["write_disposition"] == "replace"
        endpoint = resource["endpoint"]
        assert endpoint["path"] == "/v2/workbooks"
        assert endpoint["data_selector"] == "entries"
        assert endpoint["params"] == {"limit": 1000}
        assert endpoint["paginator"] == {"type": "cursor", "cursor_path": "nextPage", "cursor_param": "page"}
        assert resource["table_format"] == "delta"


class TestValidateCredentials:
    def test_success(self, requests_mock: Any) -> None:
        _mock_token(requests_mock)
        requests_mock.get(f"{BASE_URL}/v2/workbooks", json={"entries": [], "nextPage": None, "total": 0})

        result = validate_credentials("gcp_us", "client", "secret")

        assert result == (True, None)
        token_request = requests_mock.request_history[0]
        assert token_request.method == "POST"
        # The token exchange is form-urlencoded, not JSON (matches Sigma's documented header).
        assert parse_qs(token_request.text) == {
            "grant_type": ["client_credentials"],
            "client_id": ["client"],
            "client_secret": ["secret"],
        }

    def test_unknown_region_is_rejected_before_any_request(self, requests_mock: Any) -> None:
        ok, error = validate_credentials("mars", "client", "secret")

        assert ok is False
        assert error is not None and "Unknown Sigma Computing deployment region" in error
        assert requests_mock.call_count == 0

    @pytest.mark.parametrize("token_status", [400, 401, 500])
    def test_token_mint_http_failure(self, requests_mock: Any, token_status: int) -> None:
        requests_mock.post(f"{BASE_URL}/v2/auth/token", status_code=token_status, json={"error": "invalid_client"})

        ok, error = validate_credentials("gcp_us", "client", "secret")

        assert ok is False
        assert error is not None and "Sigma rejected the API client credentials" in error

    def test_token_response_missing_access_token(self, requests_mock: Any) -> None:
        requests_mock.post(f"{BASE_URL}/v2/auth/token", json={"token_type": "Bearer"})

        ok, error = validate_credentials("gcp_us", "client", "secret")

        assert ok is False
        assert error is not None and "no access token returned" in error

    def test_network_failure_during_token_mint(self, requests_mock: Any) -> None:
        import requests as requests_lib

        requests_mock.post(f"{BASE_URL}/v2/auth/token", exc=requests_lib.exceptions.ConnectionError)

        ok, error = validate_credentials("gcp_us", "client", "secret")

        assert ok is False
        assert error is not None

    @pytest.mark.parametrize(
        "status_code, schema_name, expected_ok",
        [
            (200, None, True),
            (401, None, False),
            # A genuine client may hold other scopes but lack Workbooks read, so 403 must not
            # block source creation — but it fails a scoped probe for a specific table.
            (403, None, True),
            (403, "Workbooks", False),
            (500, None, False),
        ],
    )
    def test_probe_status_mapping(
        self, requests_mock: Any, status_code: int, schema_name: Optional[str], expected_ok: bool
    ) -> None:
        _mock_token(requests_mock)
        requests_mock.get(f"{BASE_URL}/v2/workbooks", status_code=status_code, json={})

        ok, _ = validate_credentials("gcp_us", "client", "secret", schema_name=schema_name)

        assert ok is expected_ok


class TestSigmaComputingSourceTopLevel:
    def test_two_page_full_refresh_sync(self, requests_mock: Any) -> None:
        _mock_token(requests_mock)
        requests_mock.get(
            f"{BASE_URL}/v2/workbooks",
            [
                {"json": {"entries": [{"workbookId": "wb1"}], "nextPage": "CURSOR1", "total": 2, "hasMore": True}},
                {"json": {"entries": [{"workbookId": "wb2"}], "nextPage": None, "total": 2, "hasMore": False}},
            ],
        )

        response = sigma_computing_source(
            region="gcp_us",
            client_id="client",
            client_secret="secret",
            endpoint="Workbooks",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_FakeResumeManager(),
        )
        rows = _collect_rows(response)

        assert rows == [{"workbookId": "wb1"}, {"workbookId": "wb2"}]
        assert response.primary_keys == ["workbookId"]
        assert response.sort_mode is None
        assert response.partition_keys == ["createdAt"]

        list_requests = [r for r in requests_mock.request_history if r.path == "/v2/workbooks"]
        assert list_requests[0].qs["limit"] == ["1000"]
        assert "page" not in list_requests[0].qs
        # requests_mock's `.qs` lowercases query values.
        assert list_requests[1].qs["page"] == ["cursor1"]

    def test_resumes_from_saved_cursor(self, requests_mock: Any) -> None:
        _mock_token(requests_mock)
        requests_mock.get(
            f"{BASE_URL}/v2/workbooks",
            json={"entries": [{"workbookId": "wb2"}], "nextPage": None, "total": 1, "hasMore": False},
        )
        manager = _FakeResumeManager(state={"cursor": "SAVED_CURSOR"})

        response = sigma_computing_source(
            region="gcp_us",
            client_id="client",
            client_secret="secret",
            endpoint="Workbooks",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )
        _collect_rows(response)

        list_requests = [r for r in requests_mock.request_history if r.path == "/v2/workbooks"]
        assert list_requests[0].qs["page"] == ["saved_cursor"]

    def test_saves_checkpoint_after_batch(self, requests_mock: Any) -> None:
        _mock_token(requests_mock)
        requests_mock.get(
            f"{BASE_URL}/v2/workbooks",
            json={"entries": [{"workbookId": "wb1"}], "nextPage": "NEXT", "total": 2, "hasMore": True},
        )
        manager = _FakeResumeManager()

        response = sigma_computing_source(
            region="gcp_us",
            client_id="client",
            client_secret="secret",
            endpoint="Workbooks",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )
        # The checkpoint for a page is only saved once the generator resumes past its `yield`
        # (see rest_client.paginate), so fetch the first page and then advance once more to
        # observe the checkpoint saved right after it.
        items = response.items()
        assert isinstance(items, Iterable)
        iterator = iter(items)
        next(iterator)
        next(iterator)

        assert manager.saved == [{"cursor": "NEXT"}]

    @pytest.mark.parametrize(
        "endpoint, path",
        [
            ("Workbooks", "/v2/workbooks"),
            ("DataModels", "/v2/dataModels"),
            ("Connections", "/v2/connections"),
            ("Teams", "/v2/teams"),
            ("Members", "/v2/members"),
            ("Workspaces", "/v2/workspaces"),
        ],
    )
    def test_every_top_level_endpoint_requests_its_documented_path(
        self, requests_mock: Any, endpoint: str, path: str
    ) -> None:
        _mock_token(requests_mock)
        requests_mock.get(f"{BASE_URL}{path}", json={"entries": [], "nextPage": None})

        response = sigma_computing_source(
            region="gcp_us",
            client_id="client",
            client_secret="secret",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_FakeResumeManager(),
        )
        _collect_rows(response)

        # requests_mock lowercases `.path` for case-insensitive matching (e.g. `dataModels`).
        list_requests = [r for r in requests_mock.request_history if r.path == path.lower()]
        assert len(list_requests) == 1
        assert response.name == endpoint


class TestSigmaComputingSourceFanout:
    def test_workbook_elements_injects_parent_workbook_id(self, requests_mock: Any) -> None:
        _mock_token(requests_mock)
        requests_mock.get(
            f"{BASE_URL}/v2/workbooks",
            json={"entries": [{"workbookId": "wb1"}, {"workbookId": "wb2"}], "nextPage": None},
        )
        requests_mock.get(
            f"{BASE_URL}/v2/workbooks/wb1/elements",
            json={"entries": [{"elementId": "e1", "name": "Chart 1"}], "nextPage": None},
        )
        requests_mock.get(
            f"{BASE_URL}/v2/workbooks/wb2/elements",
            json={"entries": [{"elementId": "e2", "name": "Chart 2"}], "nextPage": None},
        )

        response = sigma_computing_source(
            region="gcp_us",
            client_id="client",
            client_secret="secret",
            endpoint="WorkbookElements",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_FakeResumeManager(),
        )
        rows = _collect_rows(response)

        assert rows == [
            {"elementId": "e1", "name": "Chart 1", "workbookId": "wb1"},
            {"elementId": "e2", "name": "Chart 2", "workbookId": "wb2"},
        ]
        assert response.primary_keys == ["workbookId", "elementId"]
        assert response.partition_keys is None

    @pytest.mark.parametrize(
        "endpoint, child_path_suffix, child_row, expected_primary_keys",
        [
            ("WorkbookPages", "pages", {"pageId": "p1", "name": "Page 1"}, ["workbookId", "pageId"]),
            ("WorkbookQueries", "queries", {"elementId": "e1", "sql": "select 1"}, ["workbookId", "elementId"]),
        ],
    )
    def test_other_workbook_scoped_children(
        self,
        requests_mock: Any,
        endpoint: str,
        child_path_suffix: str,
        child_row: dict[str, Any],
        expected_primary_keys: list[str],
    ) -> None:
        _mock_token(requests_mock)
        requests_mock.get(f"{BASE_URL}/v2/workbooks", json={"entries": [{"workbookId": "wb1"}], "nextPage": None})
        requests_mock.get(
            f"{BASE_URL}/v2/workbooks/wb1/{child_path_suffix}",
            json={"entries": [child_row], "nextPage": None},
        )

        response = sigma_computing_source(
            region="gcp_us",
            client_id="client",
            client_secret="secret",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_FakeResumeManager(),
        )
        rows = _collect_rows(response)

        assert rows == [{**child_row, "workbookId": "wb1"}]
        assert response.primary_keys == expected_primary_keys
