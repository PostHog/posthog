from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.semgrep._config import SemgrepSourceConfig
from products.warehouse_sources.sources.semgrep.semgrep import SemgrepResumeConfig, validate_credentials
from products.warehouse_sources.sources.semgrep.settings import ENDPOINTS, SEMGREP_ENDPOINTS
from products.warehouse_sources.sources.semgrep.source import SemgrepSource

DEPLOYMENT = {"id": 123, "slug": "my-org", "name": "My Org"}


def _driver() -> SourceDriver:
    return SourceDriver(SemgrepSource(), SemgrepSourceConfig(api_token="token"))


def _json_response(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _child_requests(requests_made: list[RecordedRequest], marker: str) -> list[RecordedRequest]:
    return [request for request in requests_made if marker in request.path]


class TestSingleEndpoint:
    def test_non_object_payload_raises_value_error(self) -> None:
        # A non-object 200 is a permanent contract violation: data_selector_required fails loud
        # instead of silently syncing 0 rows, and it must not be retried.
        result = _driver().run("deployments", [_json_response([{"id": 1}])])

        assert isinstance(result.raised, ValueError)
        assert len(result.requests) == 1

    def test_client_error_raises_http_error(self) -> None:
        # A 401/403 surfaces as an HTTPError so get_non_retryable_errors can match and stop the sync.
        result = _driver().run("deployments", [_json_response({}, status=401)])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestPageNumberFanout:
    def test_paginates_until_short_page_and_injects_deployment(self) -> None:
        page_size = SEMGREP_ENDPOINTS["sast_findings"].page_size
        assert page_size is not None
        full_page = [{"id": i} for i in range(page_size)]

        result = _driver().run(
            "sast_findings",
            [
                _json_response({"deployments": [DEPLOYMENT]}),
                _json_response({"findings": full_page}),
                _json_response({"findings": [{"id": page_size}]}),
            ],
        )

        rows = result.rows
        assert len(rows) == page_size + 1
        # Every row carries the parent deployment, keeping the composite primary key unique.
        assert all(row["deployment_id"] == 123 and row["deployment_slug"] == "my-org" for row in rows)
        # sast_findings requests pin issue_type and dedup so counts match the Semgrep UI.
        findings = _child_requests(result.requests, "/findings")
        assert all(req.param("issue_type") == "sast" and req.param("dedup") == "true" for req in findings)
        assert [req.param("page") for req in findings] == ["0", "1"]
        # Checkpoint saved after the full page points at the next page (page 1); short page ends it.
        assert any((state.fanout_state or {}).get("child_state") == {"page": 1} for state in result.saved_states)

    def test_resumes_from_saved_page(self) -> None:
        # Resume mid-way through my-org at page 2; pages 0-1 must not be re-fetched.
        result = _driver().run(
            "projects",
            [_json_response({"deployments": [DEPLOYMENT]}), _json_response({"projects": [{"id": 7}]})],
            resume_state=SemgrepResumeConfig(
                fanout_state={"completed": [], "current": "/deployments/my-org/projects", "child_state": {"page": 2}}
            ),
        )

        assert [row["id"] for row in result.rows] == [7]
        project_reqs = _child_requests(result.requests, "/projects")
        assert len(project_reqs) == 1
        assert project_reqs[0].param("page") == "2"


class TestCursorFanout:
    def test_follows_cursor_until_absent(self) -> None:
        result = _driver().run(
            "secrets",
            [
                _json_response({"deployments": [DEPLOYMENT]}),
                _json_response({"findings": [{"id": "1"}], "cursor": "abc"}),
                _json_response({"findings": [{"id": "2"}]}),
            ],
        )

        assert [row["id"] for row in result.rows] == ["1", "2"]
        # secrets fans out on the deployment id, not slug.
        secrets = _child_requests(result.requests, "/secrets")
        assert all("/deployments/123/secrets" in req.path for req in secrets)
        assert secrets[0].param("cursor") is None
        assert secrets[1].param("cursor") == "abc"
        assert any((state.fanout_state or {}).get("child_state") == {"cursor": "abc"} for state in result.saved_states)

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "secrets",
            [_json_response({"deployments": [DEPLOYMENT]}), _json_response({"findings": [{"id": "2"}]})],
            resume_state=SemgrepResumeConfig(
                fanout_state={
                    "completed": [],
                    "current": "/deployments/123/secrets",
                    "child_state": {"cursor": "abc"},
                }
            ),
        )

        assert [row["id"] for row in result.rows] == ["2"]
        secrets = _child_requests(result.requests, "/secrets")
        assert len(secrets) == 1
        assert secrets[0].param("cursor") == "abc"


class TestBodyCursorFanout:
    @parameterized.expand(
        [
            # scans returns no `hasMore`, so the missing cursor ends it.
            ("scans", "scans", "limit", {}),
            # The dependency endpoints keep returning a cursor on the last page; `hasMore` ends it.
            ("dependencies", "dependencies", "pageSize", {"hasMore": False, "cursor": "999"}),
            ("dependency_repositories", "repositorySummaries", "pageSize", {"hasMore": False, "cursor": "999"}),
        ]
    )
    def test_posts_page_size_and_cursor_in_body(
        self, endpoint: str, data_key: str, page_size_param: str, last_page_extra: dict[str, Any]
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _json_response({"deployments": [DEPLOYMENT]}),
                _json_response({data_key: [{"id": "1"}], "cursor": "c1", "hasMore": True}),
                _json_response({data_key: [{"id": "2"}], **last_page_extra}),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 2
        assert all(row["deployment_id"] == 123 and row["deployment_slug"] == "my-org" for row in result.rows)
        children = result.requests[1:]
        assert len(children) == 2
        assert all(req.method == "POST" and req.path.startswith("/api/v1/deployments/123/") for req in children)
        page_size = SEMGREP_ENDPOINTS[endpoint].page_size
        assert [req.json() for req in children] == [
            {page_size_param: page_size},
            {page_size_param: page_size, "cursor": "c1"},
        ]
        assert any((state.fanout_state or {}).get("child_state") == {"cursor": "c1"} for state in result.saved_states)

    def test_resumes_from_saved_body_cursor(self) -> None:
        result = _driver().run(
            "scans",
            [_json_response({"deployments": [DEPLOYMENT]}), _json_response({"scans": [{"id": "2"}]})],
            resume_state=SemgrepResumeConfig(
                fanout_state={
                    "completed": [],
                    "current": "/deployments/123/scans/search",
                    "child_state": {"cursor": "abc"},
                }
            ),
        )

        assert [row["id"] for row in result.rows] == ["2"]
        scans = _child_requests(result.requests, "/scans/search")
        assert len(scans) == 1
        assert scans[0].json() == {"limit": 500, "cursor": "abc"}


def _dependency(path: str = "package-lock.json", line: str = "10", version: str = "4.17.21") -> dict[str, Any]:
    return {
        "repositoryId": "42",
        "ecosystem": "npm",
        "package": {"name": "lodash", "versionSpecifier": version},
        "definedAt": {"path": path, "startLine": line},
        "transitivity": "DIRECT",
    }


class TestDependencyKey:
    @parameterized.expand(
        [
            ("same_dependency", _dependency(), _dependency(), True),
            ("other_version", _dependency(), _dependency(version="4.17.20"), False),
            ("other_lockfile", _dependency(), _dependency(path="web/package-lock.json"), False),
            ("other_line", _dependency(), _dependency(line="11"), False),
            # Missing nested objects must not raise, and still key the row.
            ("bare_rows", {"ecosystem": "npm"}, {"ecosystem": "npm"}, True),
            ("bare_vs_null_objects", {"ecosystem": "npm"}, {"ecosystem": "npm", "package": None}, True),
        ]
    )
    def test_dependency_key(self, _name: str, first: dict[str, Any], second: dict[str, Any], same: bool) -> None:
        result = _driver().run(
            "dependencies",
            [
                _json_response({"deployments": [DEPLOYMENT]}),
                _json_response({"dependencies": [first, second], "hasMore": False}),
            ],
        )

        keys = [row["dependency_key"] for row in result.rows]
        assert len(keys) == 2 and all(keys)
        assert (keys[0] == keys[1]) is same


class TestLockfilesChain:
    @staticmethod
    def _respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/deployments"):
            return _json_response({"deployments": [DEPLOYMENT]})
        if request.path.endswith("/dependencies/repositories"):
            if request.json().get("cursor") is None:
                return _json_response(
                    {"repositorySummaries": [{"id": 1, "name": "org/api"}], "cursor": "r1", "hasMore": True}
                )
            return _json_response({"repositorySummaries": [{"id": 2, "name": "org/web"}], "hasMore": False})
        if request.path.endswith("/repositories/1/lockfiles"):
            if request.json().get("cursor") is None:
                return _json_response(
                    {"lockfileSummaries": [{"lockfilePath": "a/uv.lock"}], "cursor": "l1", "hasMore": True}
                )
            return _json_response({"lockfileSummaries": [{"lockfilePath": "b/uv.lock"}], "hasMore": False})
        return _json_response({"lockfileSummaries": [{"lockfilePath": "package-lock.json"}], "hasMore": False})

    def test_fans_out_over_every_repository_page_and_lockfile_page(self) -> None:
        result = _driver().run("dependency_lockfiles", self._respond)

        assert result.raised is None
        assert [
            (
                row["deployment_id"],
                row["deployment_slug"],
                row["repository_id"],
                row["repository_name"],
                row["lockfilePath"],
            )
            for row in result.rows
        ] == [
            (123, "my-org", 1, "org/api", "a/uv.lock"),
            (123, "my-org", 1, "org/api", "b/uv.lock"),
            (123, "my-org", 2, "org/web", "package-lock.json"),
        ]
        # No prefixed parent columns leak into the table.
        assert not any(key.startswith("_") for row in result.rows for key in row)
        lockfile_requests = _child_requests(result.requests, "/lockfiles")
        assert [(req.method, req.path, req.json()) for req in lockfile_requests] == [
            ("POST", "/api/v1/deployments/123/dependencies/repositories/1/lockfiles", {"pageSize": 100}),
            (
                "POST",
                "/api/v1/deployments/123/dependencies/repositories/1/lockfiles",
                {"pageSize": 100, "cursor": "l1"},
            ),
            ("POST", "/api/v1/deployments/123/dependencies/repositories/2/lockfiles", {"pageSize": 100}),
        ]


class TestSemgrepSourceResponse:
    @staticmethod
    def _empty_listing(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/deployments"):
            return _json_response({"deployments": [DEPLOYMENT]})
        return _json_response(
            {"findings": [], "projects": [], "scans": [], "dependencies": [], "repositorySummaries": []}
        )

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, name: str) -> None:
        config = SEMGREP_ENDPOINTS[name]
        response = _driver().run(name, self._empty_listing).response
        assert response is not None
        assert response.name == name
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        # Only the two-level lockfile chain saves no checkpoint.
        assert response.supports_resume is (config.parent == "deployments")
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
        else:
            assert response.partition_keys is None

    def test_fan_out_endpoints_key_on_deployment(self) -> None:
        # Guards against dropping the parent id from a fan-out child's key, which would seed
        # duplicate rows if a token ever spans multiple deployments.
        for name, config in SEMGREP_ENDPOINTS.items():
            if name == "deployments":
                assert config.primary_keys == ["id"]
            else:
                assert config.primary_keys[0] == "deployment_id"
                assert len(config.primary_keys) > 1

    def test_partition_keys_are_stable_creation_timestamps(self) -> None:
        # Partitioning on a churning field (updated_at) rewrites partitions on every sync.
        partitioned = {name: cfg.partition_key for name, cfg in SEMGREP_ENDPOINTS.items() if cfg.partition_key}
        assert partitioned == {
            "sast_findings": "created_at",
            "sca_findings": "created_at",
            "secrets": "createdAt",
            "scans": "started_at",
        }


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network(always(ScriptedResponse(status=200, json={"deployments": []}))) as network:
            assert validate_credentials("token") == (True, 200)

        assert network.requests_log[0].headers["authorization"] == "Bearer token"
