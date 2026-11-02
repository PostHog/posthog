from typing import Any, Literal

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sonarcloud import (
    SonarCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.settings import MAX_PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.sonar_cloud import (
    SonarCloudResumeConfig,
    _base_url,
    _total,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.source import SonarCloudSource

LOGGER_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.sonar_cloud.logger"


def _response(
    rows: list[dict[str, Any]], total: int | None, *, key: str = "components", flat_total: bool = False
) -> ScriptedResponse:
    body: dict[str, Any] = {key: rows}
    if total is not None:
        # metrics/search reports p/ps/total at the top level; issues/projects nest total under `paging`.
        body["total" if flat_total else "paging"] = total if flat_total else {"total": total}
    return ScriptedResponse(json=body)


def _run(
    endpoint: str,
    script: list[ScriptedResponse],
    resume_state: SonarCloudResumeConfig | None = None,
    region: Literal["eu", "us"] = "eu",
) -> DriveResult:
    config = SonarCloudSourceConfig(token="t", organization="org", region=region)
    return SourceDriver(SonarCloudSource(), config).run(endpoint, script, resume_state=resume_state)


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


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        # Resume state points at page 2; the first request must be for page 2, not page 1.
        result = _run(
            "projects",
            [_response([{"key": "p2"}], total=MAX_PAGE_SIZE + 1)],
            resume_state=SonarCloudResumeConfig(page=2),
        )

        assert result.requests[0].param("p") == "2"

    @mock.patch(LOGGER_PATCH)
    def test_result_cap_stops_and_warns(self, mock_logger: mock.MagicMock) -> None:
        # The v1 API hard-caps results at 10000 rows; the loop must stop at the cap even when the
        # reported total is higher, and it should log that rows were dropped.
        cap_pages = 10000 // MAX_PAGE_SIZE
        full = [{"key": str(i)} for i in range(MAX_PAGE_SIZE)]

        result = _run("projects", [_response(full, total=999999) for _ in range(cap_pages)])

        assert len(result.requests) == cap_pages
        assert mock_logger.warning.called


class TestNonPaginated:
    def test_quality_gates_single_request(self) -> None:
        result = _run("quality_gates", [_response([{"id": "1", "name": "Sonar way"}], total=None, key="qualitygates")])

        assert len(result.requests) == 1
        assert result.rows == [{"id": "1", "name": "Sonar way"}]
        assert result.saved_states == []


class TestValidateCredentials:
    @parameterized.expand([(403, 403)])
    def test_returns_status_code(self, status: int, expected: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            assert validate_credentials("token", "org", "eu") == expected
