import json
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.settings import MAX_PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.sonar_cloud import (
    SonarCloudResumeConfig,
    _base_url,
    _total,
    sonar_cloud_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the sonar_cloud module.
SONAR_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.sonar_cloud.make_tracked_session"
)
LOGGER_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.sonar_cloud.logger"


def _response(
    rows: list[dict[str, Any]], total: int | None, *, key: str = "components", flat_total: bool = False
) -> Response:
    body: dict[str, Any] = {key: rows}
    if total is not None:
        # metrics/search reports p/ps/total at the top level; issues/projects nest total under `paging`.
        body["total" if flat_total else "paging"] = total if flat_total else {"total": total}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: SonarCloudResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting it after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(endpoint: str, manager: mock.MagicMock, region: str = "eu"):
    return sonar_cloud_source(
        token="t",
        organization="org",
        region=region,
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_short_page(self, MockSession) -> None:
        # A page smaller than the requested size means we've reached the end; the loop must stop rather
        # than requesting an empty next page.
        session = MockSession.return_value
        params = _wire(session, [_response([{"key": "a"}, {"key": "b"}], total=2)])

        manager = _make_manager()
        rows = _rows(_source("projects", manager))

        assert [r["key"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1
        assert params[0]["p"] == 1
        assert params[0]["ps"] == MAX_PAGE_SIZE
        assert params[0]["organization"] == "org"
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_multiple_pages_until_total(self, MockSession) -> None:
        session = MockSession.return_value
        full = [{"key": str(i)} for i in range(MAX_PAGE_SIZE)]
        params = _wire(
            session,
            [_response(full, total=MAX_PAGE_SIZE + 1), _response([{"key": "last"}], total=MAX_PAGE_SIZE + 1)],
        )

        manager = _make_manager()
        rows = _rows(_source("projects", manager))

        assert session.send.call_count == 2
        assert len(rows) == MAX_PAGE_SIZE + 1
        assert params[0]["p"] == 1
        assert params[1]["p"] == 2
        # State is saved after yielding the first (full) page so a crash re-yields rather than skips.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == SonarCloudResumeConfig(page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        # Resume state points at page 2; the first request must be for page 2, not page 1.
        session = MockSession.return_value
        params = _wire(session, [_response([{"key": "p2"}], total=MAX_PAGE_SIZE + 1)])

        manager = _make_manager(SonarCloudResumeConfig(page=2))
        _rows(_source("projects", manager))

        assert params[0]["p"] == 2

    @mock.patch(LOGGER_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_result_cap_stops_and_warns(self, MockSession, mock_logger) -> None:
        # The v1 API hard-caps results at 10000 rows; the loop must stop at the cap even when the
        # reported total is higher, and it should log that rows were dropped.
        session = MockSession.return_value
        cap_pages = 10000 // MAX_PAGE_SIZE
        full = [{"key": str(i)} for i in range(MAX_PAGE_SIZE)]
        _wire(session, [_response(full, total=999999) for _ in range(cap_pages)])

        _rows(_source("projects", _make_manager()))

        assert session.send.call_count == cap_pages
        assert mock_logger.warning.called


class TestNonPaginated:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_quality_gates_single_request(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1", "name": "Sonar way"}], total=None, key="qualitygates")])

        manager = _make_manager()
        rows = _rows(_source("quality_gates", manager))

        assert session.send.call_count == 1
        assert rows == [{"id": "1", "name": "Sonar way"}]
        manager.save_state.assert_not_called()


class TestValidateCredentials:
    @parameterized.expand([(200, 200), (401, 401), (403, 403), (500, 500)])
    def test_returns_status_code(self, status: int, expected: int) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(SONAR_SESSION_PATCH, return_value=session):
            assert validate_credentials("token", "org", "eu") == expected

    def test_transport_failure_returns_zero(self) -> None:
        with mock.patch(SONAR_SESSION_PATCH, side_effect=Exception("boom")):
            assert validate_credentials("token", "org", "eu") == 0


class TestSourceResponse:
    def test_partitioned_endpoint(self) -> None:
        response = _source("issues", _make_manager())
        assert response.name == "issues"
        assert response.primary_keys == ["key"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["creationDate"]

    def test_non_partitioned_endpoint(self) -> None:
        response = _source("metrics", _make_manager())
        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_quality_gates_merge_on_id(self) -> None:
        # Quality gate rows carry `id`/`name` but no `key`; merging on the default `key` primary key
        # would never dedupe and duplicate rows on every sync.
        response = _source("quality_gates", _make_manager())
        assert response.primary_keys == ["id"]
