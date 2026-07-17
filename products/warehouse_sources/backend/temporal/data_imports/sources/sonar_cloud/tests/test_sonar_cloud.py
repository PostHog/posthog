from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud import sonar_cloud
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.settings import MAX_PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.sonar_cloud import (
    SonarCloudResumeConfig,
    _base_url,
    _total,
    get_rows,
    sonar_cloud_source,
    validate_credentials,
)


class FakeResumeManager:
    """Minimal ResumableSourceManager stand-in that records saved state."""

    def __init__(self, state: SonarCloudResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[SonarCloudResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> SonarCloudResumeConfig | None:
        return self._state

    def save_state(self, data: SonarCloudResumeConfig) -> None:
        self.saved.append(data)


def _page(rows: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return {"components": rows, "paging": {"pageIndex": 1, "pageSize": MAX_PAGE_SIZE, "total": total}}


class TestBaseUrl:
    @parameterized.expand(
        [
            ("eu", "https://sonarcloud.io/api"),
            ("us", "https://sonarqube.us/api"),
            ("US", "https://sonarqube.us/api"),
            ("", "https://sonarcloud.io/api"),
            ("unknown", "https://sonarcloud.io/api"),
        ]
    )
    def test_region_host(self, region: str, expected: str) -> None:
        assert _base_url(region) == expected


class TestTotal:
    @parameterized.expand(
        [
            ("nested_paging", {"paging": {"total": 42}}, 42),
            ("flat_metrics_shape", {"p": 1, "ps": 100, "total": 7}, 7),
            ("missing", {"metrics": []}, None),
        ]
    )
    def test_total_extraction(self, _name: str, data: dict[str, Any], expected: int | None) -> None:
        # metrics/search returns p/ps/total at the top level while issues/projects nest them under
        # `paging`; a regression that only reads one shape would silently over- or under-fetch the other.
        assert _total(data) == expected


class TestGetRowsPagination:
    def test_stops_on_short_page(self) -> None:
        # A page smaller than the requested size means we've reached the end; the loop must stop rather
        # than requesting an empty next page forever.
        pages = [_page([{"key": "a"}, {"key": "b"}], total=2)]
        with patch.object(sonar_cloud, "make_tracked_session", return_value=MagicMock()):
            with patch.object(sonar_cloud, "_fetch", side_effect=pages) as fetch:
                batches = list(get_rows("t", "org", "eu", "projects", MagicMock(), FakeResumeManager()))
        assert [r["key"] for batch in batches for r in batch] == ["a", "b"]
        assert fetch.call_count == 1

    def test_walks_multiple_pages_until_total(self) -> None:
        full = [{"key": str(i)} for i in range(MAX_PAGE_SIZE)]
        pages = [
            {"components": full, "paging": {"total": MAX_PAGE_SIZE + 1}},
            {"components": [{"key": "last"}], "paging": {"total": MAX_PAGE_SIZE + 1}},
        ]
        manager = FakeResumeManager()
        with patch.object(sonar_cloud, "make_tracked_session", return_value=MagicMock()):
            with patch.object(sonar_cloud, "_fetch", side_effect=pages) as fetch:
                batches = list(get_rows("t", "org", "eu", "projects", MagicMock(), manager))
        assert fetch.call_count == 2
        assert sum(len(b) for b in batches) == MAX_PAGE_SIZE + 1
        # State is saved after yielding the first (full) page so a crash re-yields rather than skips.
        assert manager.saved == [SonarCloudResumeConfig(page=2)]

    def test_resumes_from_saved_page(self) -> None:
        # Resume state points at page 2; the first request must be for page 2, not page 1.
        pages = [{"components": [{"key": "p2"}], "paging": {"total": MAX_PAGE_SIZE + 1}}]
        with patch.object(sonar_cloud, "make_tracked_session", return_value=MagicMock()):
            with patch.object(sonar_cloud, "_build_url", wraps=sonar_cloud._build_url) as build:
                with patch.object(sonar_cloud, "_fetch", side_effect=pages):
                    list(
                        get_rows(
                            "t", "org", "eu", "projects", MagicMock(), FakeResumeManager(SonarCloudResumeConfig(page=2))
                        )
                    )
        assert build.call_args_list[0].kwargs.get("params", build.call_args_list[0].args[2])["p"] == 2

    def test_result_cap_stops_and_warns(self) -> None:
        # The v1 API hard-caps results at 10000 rows; the loop must stop at the cap even when the
        # reported total is higher, and it should log that rows were dropped.
        cap_pages = 10000 // MAX_PAGE_SIZE
        full = [{"key": str(i)} for i in range(MAX_PAGE_SIZE)]
        pages = [{"components": full, "paging": {"total": 999999}} for _ in range(cap_pages)]
        logger = MagicMock()
        with patch.object(sonar_cloud, "make_tracked_session", return_value=MagicMock()):
            with patch.object(sonar_cloud, "_fetch", side_effect=pages) as fetch:
                list(get_rows("t", "org", "eu", "projects", logger, FakeResumeManager()))
        assert fetch.call_count == cap_pages
        assert logger.warning.called


class TestGetRowsNonPaginated:
    def test_quality_gates_single_request(self) -> None:
        data = {"qualitygates": [{"id": "1", "name": "Sonar way"}]}
        manager = FakeResumeManager()
        with patch.object(sonar_cloud, "make_tracked_session", return_value=MagicMock()):
            with patch.object(sonar_cloud, "_fetch", return_value=data) as fetch:
                batches = list(get_rows("t", "org", "eu", "quality_gates", MagicMock(), manager))
        assert fetch.call_count == 1
        assert batches == [[{"id": "1", "name": "Sonar way"}]]
        assert manager.saved == []


class TestValidateCredentials:
    @parameterized.expand([(200, 200), (401, 401), (403, 403), (500, 500)])
    def test_returns_status_code(self, status: int, expected: int) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status)
        with patch.object(sonar_cloud, "make_tracked_session", return_value=session):
            assert validate_credentials("token", "org", "eu") == expected

    def test_transport_failure_returns_zero(self) -> None:
        with patch.object(sonar_cloud, "make_tracked_session", side_effect=Exception("boom")):
            assert validate_credentials("token", "org", "eu") == 0


class TestSourceResponse:
    def test_partitioned_endpoint(self) -> None:
        response = sonar_cloud_source("t", "org", "eu", "issues", MagicMock(), FakeResumeManager())
        assert response.name == "issues"
        assert response.primary_keys == ["key"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["creationDate"]

    def test_non_partitioned_endpoint(self) -> None:
        response = sonar_cloud_source("t", "org", "eu", "metrics", MagicMock(), FakeResumeManager())
        assert response.partition_mode is None
        assert response.partition_keys is None
