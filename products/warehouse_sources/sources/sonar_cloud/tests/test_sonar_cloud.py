from collections.abc import Callable
from typing import Any, Literal

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.sonar_cloud._config import SonarCloudSourceConfig
from products.warehouse_sources.sources.sonar_cloud.settings import MAX_PAGE_SIZE, MEASURE_METRIC_KEYS
from products.warehouse_sources.sources.sonar_cloud.sonar_cloud import (
    SonarCloudResumeConfig,
    _base_url,
    _total,
    validate_credentials,
)
from products.warehouse_sources.sources.sonar_cloud.source import SonarCloudSource

LOGGER_PATCH = "products.warehouse_sources.sources.sonar_cloud.sonar_cloud.logger"


def _response(
    rows: list[dict[str, Any]], total: int | None, *, key: str = "components", flat_total: bool = False
) -> ScriptedResponse:
    body: dict[str, Any] = {key: rows}
    if total is not None:
        # metrics/search reports p/ps/total at the top level; issues/projects nest total under `paging`.
        body["total" if flat_total else "paging"] = total if flat_total else {"total": total}
    return ScriptedResponse(json=body)


def _paging(index: int, size: int, total: int) -> dict[str, int]:
    return {"pageIndex": index, "pageSize": size, "total": total}


def _projects(*keys: str) -> ScriptedResponse:
    return _response([{"key": key, "organization": "org"} for key in keys], total=len(keys))


def _component_tree(project: str, page: int, total: int, components: list[str]) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "paging": _paging(page, 2, total),
            "baseComponent": {"key": project, "qualifier": "TRK", "measures": [{"metric": "ncloc", "value": "30"}]},
            "components": [
                {
                    "key": f"{project}:{path}",
                    "qualifier": "FIL",
                    "path": path,
                    "measures": [{"metric": "ncloc", "value": "10"}],
                }
                for path in components
            ],
        }
    )


def _measures_script(request: RecordedRequest) -> ScriptedResponse:
    if request.path.endswith("components/search_projects"):
        return _projects("P1", "P2")
    project, page = request.param("component"), request.param("p")
    if project == "P1" and page == "1":
        return _component_tree("P1", 1, 3, ["a.py", "b.py"])
    if project == "P1" and page == "2":
        return _component_tree("P1", 2, 3, ["c.py"])
    if project == "P2" and page == "1":
        return _component_tree("P2", 1, 0, [])
    raise AssertionError(f"unexpected request {request.url}")


def _run(
    endpoint: str,
    script: list[ScriptedResponse] | Callable[[RecordedRequest], ScriptedResponse],
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


class TestMeasures:
    def test_walks_component_pages_and_keeps_the_project_row_once(self) -> None:
        # component_tree returns the project in `baseComponent` on every page, so a regression that
        # drops it loses the project-level values, and one that keeps every copy duplicates them.
        result = _run("measures", _measures_script)

        assert [(row["project_key"], row["key"], row["metric"], row["value"]) for row in result.rows] == [
            ("P1", "P1", "ncloc", "30"),
            ("P1", "P1:a.py", "ncloc", "10"),
            ("P1", "P1:b.py", "ncloc", "10"),
            ("P1", "P1:c.py", "ncloc", "10"),
            ("P2", "P2", "ncloc", "30"),
        ]
        tree_requests = [r for r in result.requests if r.path.endswith("measures/component_tree")]
        assert [(r.param("component"), r.param("p")) for r in tree_requests] == [("P1", "1"), ("P1", "2"), ("P2", "1")]
        assert tree_requests[0].param("metricKeys") == ",".join(MEASURE_METRIC_KEYS)
        assert tree_requests[0].param("strategy") == "all"

    def test_resumes_mid_project_on_the_saved_page(self) -> None:
        first = _run("measures", _measures_script)
        mid_p1 = first.saved_states[0]
        assert mid_p1.fanout_state["child_state"] == {"page": 2}

        resumed = _run("measures", _measures_script, resume_state=mid_p1)

        tree_requests = [r for r in resumed.requests if r.path.endswith("measures/component_tree")]
        assert [(r.param("component"), r.param("p")) for r in tree_requests] == [("P1", "2"), ("P2", "1")]
        # The first attempt already wrote P1's project row from page 1, and a resumed full refresh
        # appends, so the page-2 copy of `baseComponent` must not come back.
        assert [(row["project_key"], row["key"]) for row in resumed.rows] == [("P1", "P1:c.py"), ("P2", "P2")]


class TestMeasuresHistory:
    def test_pages_by_paging_total_and_flattens_history(self) -> None:
        pages = {
            "1": {
                "paging": _paging(1, 2, 3),
                "measures": [
                    {"metric": "ncloc", "history": [{"date": "d1", "value": "1"}, {"date": "d2", "value": "2"}]},
                    {"metric": "coverage", "history": [{"date": "d1"}, {"date": "d2", "value": "50.0"}]},
                ],
            },
            "2": {
                "paging": _paging(2, 2, 3),
                "measures": [
                    {"metric": "ncloc", "history": [{"date": "d3", "value": "3"}]},
                    {"metric": "coverage", "history": [{"date": "d3", "value": "60.0"}]},
                ],
            },
        }

        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("components/search_projects"):
                return _projects("P1")
            return ScriptedResponse(json=pages[request.param("p") or ""])

        result = _run("measures_history", script)

        assert [(row["project_key"], row["metric"], row["date"], row["value"]) for row in result.rows] == [
            ("P1", "ncloc", "d1", "1"),
            ("P1", "ncloc", "d2", "2"),
            ("P1", "coverage", "d1", None),
            ("P1", "coverage", "d2", "50.0"),
            ("P1", "ncloc", "d3", "3"),
            ("P1", "coverage", "d3", "60.0"),
        ]
        assert len(result.requests) == 3


class TestIssueChangelog:
    def test_requests_each_issue_once_and_tags_rows(self) -> None:
        changelogs = {
            "I1": [{"creationDate": "2026-01-01T00:00:00+0000", "diffs": [{"key": "status", "newValue": "CLOSED"}]}],
            "I2": [],
        }

        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("issues/search"):
                return _response(
                    [{"key": "I1", "project": "P1"}, {"key": "I2", "project": "P1"}], total=2, key="issues"
                )
            return ScriptedResponse(json={"changelog": changelogs[request.param("issue") or ""]})

        result = _run("issue_changelog", script)

        assert [(row["issue_key"], row["project_key"], row["creationDate"]) for row in result.rows] == [
            ("I1", "P1", "2026-01-01T00:00:00+0000")
        ]
        changelog_requests = [r for r in result.requests if r.path.endswith("issues/changelog")]
        assert [r.param("issue") for r in changelog_requests] == ["I1", "I2"]
        # The changelog is not paginated; a page or page-size param would be an undocumented one.
        assert all(r.param("p") is None and r.param("ps") is None for r in changelog_requests)


class TestProjectFanOut:
    @parameterized.expand(
        [
            ("project_quality_profiles", "qualityprofiles/search", "profiles", "org"),
            ("pull_requests", "project_pull_requests/list", "pullRequests", None),
        ]
    )
    def test_requests_each_project_once_and_tags_rows(
        self, endpoint: str, child_path: str, data_key: str, organization: str | None
    ) -> None:
        children = {"P1": [{"key": "A"}, {"key": "B"}], "P2": [{"key": "A"}]}

        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("components/search_projects"):
                return _projects("P1", "P2")
            return ScriptedResponse(json={data_key: children[request.param("project") or ""]})

        result = _run(endpoint, script)

        # The same child key under two projects must stay two rows, told apart by the project key.
        assert [(row["project_key"], row["key"]) for row in result.rows] == [("P1", "A"), ("P1", "B"), ("P2", "A")]
        child_requests = [r for r in result.requests if r.path.endswith(child_path)]
        assert [(r.param("project"), r.param("organization")) for r in child_requests] == [
            ("P1", organization),
            ("P2", organization),
        ]
        assert all(r.param("p") is None and r.param("ps") is None for r in child_requests)


class TestComponents:
    def test_walks_tree_pages_and_skips_the_project_row(self) -> None:
        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("components/search_projects"):
                return _projects("P1")
            return _component_tree(
                "P1",
                int(request.param("p") or "0"),
                3,
                {"1": ["a.py", "b.py"], "2": ["c.py"]}[request.param("p") or ""],
            )

        result = _run("components", script)

        assert [(row["project_key"], row["key"], row["qualifier"]) for row in result.rows] == [
            ("P1", "P1:a.py", "FIL"),
            ("P1", "P1:b.py", "FIL"),
            ("P1", "P1:c.py", "FIL"),
        ]
        tree_requests = [r for r in result.requests if r.path.endswith("components/tree")]
        assert [(r.param("component"), r.param("p"), r.param("strategy")) for r in tree_requests] == [
            ("P1", "1", "all"),
            ("P1", "2", "all"),
        ]
