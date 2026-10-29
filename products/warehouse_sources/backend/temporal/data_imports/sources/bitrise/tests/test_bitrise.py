from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.bitrise import (
    BitriseResumeConfig,
    _build_after_param,
    _to_unix_timestamp,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.settings import (
    BITRISE_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.source import BitriseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bitrise import (
    BitriseSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(BitriseSource(), BitriseSourceConfig(api_token="token"))


def _response(body: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


class TestToUnixTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), 1767323045),
            (datetime(2026, 1, 2, 3, 4, 5), 1767323045),
            (date(2026, 1, 2), 1767312000),
            ("2026-01-02T03:04:05Z", 1767323045),
            ("2026-01-02T03:04:05+00:00", 1767323045),
            (1767323045, 1767323045),
            ("not-a-date", None),
        ],
    )
    def test_conversion(self, value: Any, expected: int | None) -> None:
        assert _to_unix_timestamp(value) == expected


class TestBuildAfterParam:
    @pytest.mark.parametrize(
        "should_use_incremental_field, last_value",
        [
            (False, datetime(2026, 1, 2, tzinfo=UTC)),
            (True, None),
            (True, "garbage"),
        ],
    )
    def test_no_filter_when_not_incremental(self, should_use_incremental_field: bool, last_value: Any) -> None:
        assert _build_after_param(should_use_incremental_field, last_value) is None


class TestValidateCredentials:
    def test_valid_personal_access_token(self) -> None:
        with scripted_network([_response({"data": {}})]) as network:
            assert validate_credentials("token") is True

        # /me succeeded, no fallback probe needed.
        assert [request.path for request in network.requests_log] == ["/v0.1/me"]
        assert network.requests_log[0].headers["authorization"] == "token"

    def test_invalid_token(self) -> None:
        with scripted_network(
            [
                _response({"message": "Unauthorized"}, status_code=401),
                _response({"message": "Unauthorized"}, status_code=401),
            ]
        ) as network:
            assert validate_credentials("bad") is False

        assert [request.path for request in network.requests_log] == ["/v0.1/me", "/v0.1/apps"]
        assert network.requests_log[1].param("limit") == "1"
        assert all(request.headers["authorization"] == "bad" for request in network.requests_log)

    def test_swallows_exceptions(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            assert validate_credentials("token") is False

        assert {request.path for request in network.requests_log} == {"/v0.1/me"}


class TestFlatCursorListings:
    @pytest.mark.parametrize(
        "endpoint, path",
        [
            ("apps", "/v0.1/apps"),
            ("activities", "/v0.1/me/activities"),
        ],
    )
    def test_paginates_via_next_anchor_and_saves_state(self, endpoint: str, path: str) -> None:
        result = _driver().run(
            endpoint,
            [
                _response({"data": [{"slug": "row1"}], "paging": {"next": "anchor1"}}),
                _response({"data": [{"slug": "row2"}], "paging": {}}),
            ],
        )

        assert result.raised is None
        assert [row["slug"] for row in result.rows] == ["row1", "row2"]
        assert result.paths == [path, path]
        assert result.params("limit") == ["50", "50"]
        # The second page carries the anchor returned by the first.
        assert result.params("next") == [None, "anchor1"]
        # State saved once, after the first page yielded and only while more pages remain.
        assert result.saved_states == [BitriseResumeConfig(next="anchor1")]

    def test_resumes_from_saved_anchor(self) -> None:
        result = _driver().run(
            "apps",
            [_response({"data": [{"slug": "app3"}], "paging": {}})],
            resume_state=BitriseResumeConfig(next="anchor2"),
        )

        assert result.raised is None
        assert [row["slug"] for row in result.rows] == ["app3"]
        assert result.params("next") == ["anchor2"]


class TestBuilds:
    def test_fans_out_over_apps_and_injects_app_slug(self) -> None:
        result = _driver().run(
            "builds",
            [
                _response({"data": [{"slug": "app1"}, {"slug": "app2"}], "paging": {}}),
                _response({"data": [{"slug": "b1", "triggered_at": "2026-01-01T00:00:00Z"}], "paging": {}}),
                _response({"data": [{"slug": "b2", "triggered_at": "2026-01-02T00:00:00Z"}], "paging": {}}),
            ],
        )

        assert result.raised is None
        assert [(row["slug"], row["app_slug"]) for row in result.rows] == [("b1", "app1"), ("b2", "app2")]
        assert result.paths[1:] == ["/v0.1/apps/app1/builds", "/v0.1/apps/app2/builds"]
        # The parent app slug binds the path, not the query string.
        assert result.requests[1].param("sort_by") == "created_at"
        assert result.requests[1].param("app_slug") is None

    def test_resumes_from_bookmarked_app(self) -> None:
        result = _driver().run(
            "builds",
            [
                _response({"data": [{"slug": "app1"}, {"slug": "app2"}], "paging": {}}),
                _response({"data": [{"slug": "b9"}], "paging": {}}),
            ],
            resume_state=BitriseResumeConfig(
                fanout_state={
                    "completed": ["/apps/app1/builds"],
                    "current": "/apps/app2/builds",
                    "child_state": {"cursor": "page3"},
                }
            ),
        )

        # app1 is skipped entirely; app2 resumes from its saved page anchor.
        assert result.raised is None
        assert [(row["slug"], row["app_slug"]) for row in result.rows] == [("b9", "app2")]
        assert result.paths == ["/v0.1/apps", "/v0.1/apps/app2/builds"]
        assert result.requests[1].param("next") == "page3"


class TestPipelines:
    def test_fans_out_over_apps_and_injects_app_slug(self) -> None:
        result = _driver().run(
            "pipelines",
            [
                _response({"data": [{"slug": "app1"}], "paging": {}}),
                _response({"data": [{"slug": "p1", "triggered_at": "2026-01-01T00:00:00Z"}], "paging": {}}),
            ],
        )

        assert result.raised is None
        assert [(row["slug"], row["app_slug"]) for row in result.rows] == [("p1", "app1")]
        assert result.paths[1] == "/v0.1/apps/app1/pipelines"

    def test_incremental_passes_an_rfc3339_after_param(self) -> None:
        result = _driver().run(
            "pipelines",
            [
                _response({"data": [{"slug": "app1"}], "paging": {}}),
                _response({"data": [], "paging": {}}),
            ],
            incremental_field="triggered_at",
            db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
        )

        # Unlike builds, the pipelines filter is a date string rather than a Unix timestamp.
        assert result.raised is None
        assert result.requests[1].param("after") == "2026-01-01T00:00:00Z"


class TestBranches:
    def test_maps_branch_names_to_rows(self) -> None:
        result = _driver().run(
            "branches",
            [
                _response({"data": [{"slug": "app1"}], "paging": {}}),
                _response({"data": ["main", "release/1.0"]}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"app_slug": "app1", "branch": "main"},
            {"app_slug": "app1", "branch": "release/1.0"},
        ]
        assert result.paths[1] == "/v0.1/apps/app1/branches"


class TestSinglePageAppChildren:
    @pytest.mark.parametrize(
        "endpoint, path, expected_limit",
        [
            ("archived_builds", "/v0.1/apps/{app}/archived-builds", "1000"),
            ("build_requests", "/v0.1/apps/{app}/build-requests", None),
        ],
    )
    def test_fans_out_over_apps_with_one_request_per_app(
        self, endpoint: str, path: str, expected_limit: str | None
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _response({"data": [{"slug": "app1"}, {"slug": "app2"}, {"slug": "gone"}], "paging": {}}),
                # A paging anchor must not trigger a second request: the endpoint takes no anchor param.
                _response({"data": [{"slug": "r1"}], "paging": {"next": "ignored"}}),
                _response({"data": [{"slug": "r2"}, {"slug": "r3"}]}),
                # An app deleted between enumeration and its fetch must not fail the sync.
                _response({"message": "Not Found"}, status_code=404),
            ],
        )

        assert result.raised is None
        assert [(row["slug"], row["app_slug"]) for row in result.rows] == [
            ("r1", "app1"),
            ("r2", "app2"),
            ("r3", "app2"),
        ]
        assert result.paths[1:] == [path.format(app=app) for app in ("app1", "app2", "gone")]
        assert [request.param("limit") for request in result.requests[1:]] == [expected_limit] * 3
        assert all(request.param("app_slug") is None for request in result.requests[1:])


class TestAvailableStacks:
    @pytest.mark.parametrize(
        "body, expected_rows",
        [
            (
                {
                    "linux-docker-android-22.04": {
                        "id": "linux-docker-android-22.04",
                        "os": "linux",
                        "status": "stable",
                    },
                    "osx-xcode-16.0.x": {"id": "osx-xcode-16.0.x", "os": "macos", "removal-date": "2027-01-01"},
                },
                [
                    {"id": "linux-docker-android-22.04", "os": "linux", "status": "stable"},
                    {"id": "osx-xcode-16.0.x", "os": "macos", "removal-date": "2027-01-01"},
                ],
            ),
            # The map key stands in for a missing or empty `id`.
            (
                {"osx-xcode-edge": {"title": "Xcode edge"}, "linux-edge": {"id": "", "os": "linux"}},
                [{"title": "Xcode edge", "id": "osx-xcode-edge"}, {"id": "linux-edge", "os": "linux"}],
            ),
            # Non-object values are not stacks.
            ({"osx-xcode-16.0.x": {"id": "osx-xcode-16.0.x"}, "note": "x"}, [{"id": "osx-xcode-16.0.x"}]),
            ({}, []),
        ],
    )
    def test_explodes_stack_map_into_rows(self, body: dict[str, Any], expected_rows: list[dict[str, Any]]) -> None:
        result = _driver().run("available_stacks", [_response(body)])

        assert result.raised is None
        assert result.rows == expected_rows
        assert result.paths == ["/v0.1/available-stacks"]


class TestOrganizationMembers:
    def test_fans_out_over_organizations_and_injects_org_slug(self) -> None:
        result = _driver().run(
            "organization_members",
            [
                _response({"data": [{"slug": "org1"}, {"slug": "org2"}]}),
                # The members listing answers with a bare array, not a data envelope.
                _response([{"slug": "u1", "username": "ada", "email": "ada@example.com"}]),
                _response([{"slug": "u2", "username": "grace", "email": "grace@example.com"}]),
            ],
        )

        assert result.raised is None
        assert [(row["slug"], row["org_slug"]) for row in result.rows] == [("u1", "org1"), ("u2", "org2")]
        assert result.paths[1:] == ["/v0.1/organizations/org1/members", "/v0.1/organizations/org2/members"]


class TestArtifacts:
    def test_fans_out_over_builds_and_injects_parent_identifiers(self) -> None:
        result = _driver().run(
            "artifacts",
            [
                _response({"data": [{"slug": "app1"}], "paging": {}}),
                _response({"data": [{"slug": "b1", "triggered_at": "2026-01-01T00:00:00Z"}], "paging": {}}),
                _response({"data": [{"slug": "art1", "title": "app.ipa"}], "paging": {}}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {
                "slug": "art1",
                "title": "app.ipa",
                "app_slug": "app1",
                "build_slug": "b1",
                "build_triggered_at": "2026-01-01T00:00:00Z",
            }
        ]
        assert result.paths[2] == "/v0.1/apps/app1/builds/b1/artifacts"

    def test_incremental_filters_parent_builds(self) -> None:
        result = _driver().run(
            "artifacts",
            [
                _response({"data": [{"slug": "app1"}], "paging": {}}),
                _response({"data": [], "paging": {}}),
            ],
            incremental_field="build_triggered_at",
            db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
        )

        # The after filter is applied at the parent builds level, not the artifact listing.
        assert result.raised is None
        assert result.requests[1].param("after") is not None


class TestUnknownEndpoint:
    def test_raises_value_error(self) -> None:
        result = _driver().run("nope", [])
        assert isinstance(result.raised, ValueError)


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = BITRISE_ENDPOINTS[endpoint]
        result = _driver().run(endpoint, [])
        response = result.response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Fan-out + newest-first ordering: the watermark must only persist at job end.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
