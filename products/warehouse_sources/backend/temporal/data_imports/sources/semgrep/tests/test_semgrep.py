from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep import semgrep
from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.semgrep import (
    SEMGREP_BASE_URL,
    SemgrepResumeConfig,
    SemgrepRetryableError,
    _build_url,
    get_rows,
    semgrep_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.settings import (
    ENDPOINTS,
    SEMGREP_ENDPOINTS,
)

DEPLOYMENT = {"id": 123, "slug": "my-org", "name": "My Org"}
OTHER_DEPLOYMENT = {"id": 456, "slug": "other-org", "name": "Other Org"}


class _FakeResumableManager:
    def __init__(self, state: SemgrepResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SemgrepResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SemgrepResumeConfig | None:
        return self._state

    def save_state(self, data: SemgrepResumeConfig) -> None:
        self.saved.append(data)


def _response_with_status(status_code: int, body: bytes = b"") -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = body
    return response


def _query_param(url: str, name: str) -> str | None:
    if f"{name}=" not in url:
        return None
    return url.split(f"{name}=")[1].split("&")[0]


class TestBuildUrl:
    def test_page_zero_is_kept(self) -> None:
        # page=0 is the first page; it must not be dropped as a falsy value.
        url = _build_url("/deployments/my-org/projects", {"page": 0, "page_size": 100})
        assert "page=0" in url

    def test_no_params_yields_bare_url(self) -> None:
        assert _build_url("/deployments", {}) == f"{SEMGREP_BASE_URL}/deployments"

    def test_none_values_are_omitted(self) -> None:
        url = _build_url("/deployments/123/secrets", {"limit": 100, "cursor": None})
        assert "cursor" not in url


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(status)
        # No-op the backoff sleep so the 5 attempts run instantly.
        with patch.object(semgrep._fetch_page.retry, "sleep", lambda *a, **k: None):  # type: ignore[attr-defined]
            with pytest.raises(SemgrepRetryableError):
                semgrep._fetch_page(session, f"{SEMGREP_BASE_URL}/deployments", MagicMock())
        assert session.get.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(status)
        with pytest.raises(requests.HTTPError):
            semgrep._fetch_page(session, f"{SEMGREP_BASE_URL}/deployments", MagicMock())

    def test_non_object_payload_raises_value_error(self) -> None:
        # A non-object 200 is a permanent contract violation, so it must bypass the retry decorator.
        session = MagicMock()
        session.get.return_value = _response_with_status(200, b'[{"id": 1}]')
        with pytest.raises(ValueError):
            semgrep._fetch_page(session, f"{SEMGREP_BASE_URL}/deployments", MagicMock())
        assert session.get.call_count == 1


class TestGetRows:
    @staticmethod
    def _collect(
        endpoint: str,
        manager: _FakeResumableManager,
        monkeypatch: Any,
        responses: dict[str, dict[str, Any]],
        deployments: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict], list[str]]:
        """Drive get_rows with canned responses keyed on (page|cursor) query param per path."""
        fetched_urls: list[str] = []

        def fake_fetch(session: Any, url: str, logger: Any) -> dict[str, Any]:
            fetched_urls.append(url)
            if url == f"{SEMGREP_BASE_URL}/deployments":
                return {"deployments": deployments if deployments is not None else [DEPLOYMENT]}
            key = _query_param(url, "page") or _query_param(url, "cursor") or ""
            path = url.split(SEMGREP_BASE_URL)[1].split("?")[0]
            return responses.get(f"{path}|{key}", {})

        monkeypatch.setattr(semgrep, "_fetch_page", fake_fetch)
        monkeypatch.setattr(semgrep, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for page in get_rows(
            api_token="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(page)
        return rows, fetched_urls

    def test_deployments_is_a_single_unpaginated_request(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, urls = self._collect("deployments", manager, monkeypatch, {})
        assert rows == [DEPLOYMENT]
        assert urls == [f"{SEMGREP_BASE_URL}/deployments"]
        assert manager.saved == []

    def test_paged_endpoint_paginates_until_short_page_and_injects_deployment(self, monkeypatch: Any) -> None:
        page_size = SEMGREP_ENDPOINTS["sast_findings"].page_size
        assert page_size is not None
        full_page = [{"id": i} for i in range(page_size)]
        manager = _FakeResumableManager()
        rows, urls = self._collect(
            "sast_findings",
            manager,
            monkeypatch,
            {
                "/deployments/my-org/findings|0": {"findings": full_page},
                "/deployments/my-org/findings|1": {"findings": [{"id": page_size}]},
            },
        )
        assert len(rows) == page_size + 1
        # Every row carries the parent deployment, keeping the composite primary key unique.
        assert all(row["deployment_id"] == 123 and row["deployment_slug"] == "my-org" for row in rows)
        # State is saved after the full page (pointing at the next page), then we stop on the short one.
        assert manager.saved == [SemgrepResumeConfig(deployment_id="123", page=1)]
        # sast_findings requests must pin issue_type and dedup so counts match the Semgrep UI.
        finding_urls = [url for url in urls if "findings" in url]
        assert all("issue_type=sast" in url and "dedup=true" in url for url in finding_urls)

    def test_sca_findings_requests_sca_issue_type(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _, urls = self._collect(
            "sca_findings",
            manager,
            monkeypatch,
            {"/deployments/my-org/findings|0": {"findings": [{"id": 1}]}},
        )
        assert any("issue_type=sca" in url for url in urls)

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect("projects", manager, monkeypatch, {"/deployments/my-org/projects|0": {"projects": []}})
        assert rows == []
        assert manager.saved == []

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SemgrepResumeConfig(deployment_id="123", page=2))
        rows, urls = self._collect(
            "projects",
            manager,
            monkeypatch,
            {"/deployments/my-org/projects|2": {"projects": [{"id": 7}]}},
        )
        # Resuming skips pages 0-1; the short page 2 finishes the sync.
        assert [row["id"] for row in rows] == [7]
        project_urls = [url for url in urls if "projects" in url]
        assert len(project_urls) == 1
        assert "page=2" in project_urls[0]

    def test_vanished_bookmarked_deployment_starts_over(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SemgrepResumeConfig(deployment_id="999", page=5))
        rows, urls = self._collect(
            "projects",
            manager,
            monkeypatch,
            {"/deployments/my-org/projects|0": {"projects": [{"id": 1}]}},
        )
        assert [row["id"] for row in rows] == [1]
        assert any("page=0" in url for url in urls)

    def test_fans_out_over_every_deployment_and_bookmarks_the_next(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect(
            "projects",
            manager,
            monkeypatch,
            {
                "/deployments/my-org/projects|0": {"projects": [{"id": 1}]},
                "/deployments/other-org/projects|0": {"projects": [{"id": 2}]},
            },
            deployments=[DEPLOYMENT, OTHER_DEPLOYMENT],
        )
        assert {(row["id"], row["deployment_slug"]) for row in rows} == {(1, "my-org"), (2, "other-org")}
        # A crash between deployments must resume at the second one, not re-run the first.
        assert SemgrepResumeConfig(deployment_id="456") in manager.saved

    def test_cursor_endpoint_follows_cursor_until_absent(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, urls = self._collect(
            "secrets",
            manager,
            monkeypatch,
            {
                "/deployments/123/secrets|": {"findings": [{"id": "1"}], "cursor": "abc"},
                "/deployments/123/secrets|abc": {"findings": [{"id": "2"}]},
            },
        )
        assert [row["id"] for row in rows] == ["1", "2"]
        secrets_urls = [url for url in urls if "secrets" in url]
        assert _query_param(secrets_urls[0], "cursor") is None
        assert _query_param(secrets_urls[1], "cursor") == "abc"
        # State is saved after yielding the first page so a crash re-pulls, never skips, a page.
        assert manager.saved == [SemgrepResumeConfig(deployment_id="123", cursor="abc")]

    def test_cursor_endpoint_terminates_on_repeated_cursor(self, monkeypatch: Any) -> None:
        # If the API keeps echoing the final cursor, the sync must stop instead of looping forever.
        manager = _FakeResumableManager()
        rows, urls = self._collect(
            "secrets",
            manager,
            monkeypatch,
            {
                "/deployments/123/secrets|": {"findings": [{"id": "1"}], "cursor": "abc"},
                "/deployments/123/secrets|abc": {"findings": [{"id": "2"}], "cursor": "abc"},
            },
        )
        assert [row["id"] for row in rows] == ["1", "2"]
        assert len([url for url in urls if "secrets" in url]) == 2

    def test_cursor_endpoint_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(SemgrepResumeConfig(deployment_id="123", cursor="abc"))
        rows, urls = self._collect(
            "secrets",
            manager,
            monkeypatch,
            {"/deployments/123/secrets|abc": {"findings": [{"id": "2"}]}},
        )
        assert [row["id"] for row in rows] == ["2"]
        secrets_urls = [url for url in urls if "secrets" in url]
        assert len(secrets_urls) == 1
        assert _query_param(secrets_urls[0], "cursor") == "abc"


class TestSemgrepSourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, name: str) -> None:
        config = SEMGREP_ENDPOINTS[name]
        response = semgrep_source(
            api_token="token",
            endpoint=name,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == name
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None

    def test_fan_out_endpoints_key_on_deployment_and_id(self) -> None:
        # Guards against dropping the parent id from a fan-out child's key, which would seed
        # duplicate rows if a token ever spans multiple deployments.
        for name, config in SEMGREP_ENDPOINTS.items():
            if name == "deployments":
                assert config.primary_keys == ["id"]
            else:
                assert config.primary_keys == ["deployment_id", "id"]

    def test_partition_keys_are_stable_creation_timestamps(self) -> None:
        # Partitioning on a churning field (updated_at) rewrites partitions on every sync.
        partitioned = {name: cfg.partition_key for name, cfg in SEMGREP_ENDPOINTS.items() if cfg.partition_key}
        assert partitioned == {"sast_findings": "created_at", "sca_findings": "created_at", "secrets": "createdAt"}
