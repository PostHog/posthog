from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.dbt import (
    DISCOVERY_TOKEN_ERROR,
    DbtHostNotAllowedError,
    DbtResumeConfig,
    DbtRetryableError,
    _coerce_datetime,
    _raise_for_graphql_errors,
    get_base_url,
    get_discovery_url,
    get_endpoint_permissions,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.source import DbtSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dbt import DbtSourceConfig

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dbt.dbt"


def _page(rows: list[dict[str, Any]], *, count: int | None = None, total_count: int | None = None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "status": {"code": 200, "is_success": True},
            "data": rows,
            "extra": {
                "pagination": {
                    "count": count if count is not None else len(rows),
                    "total_count": total_count if total_count is not None else len(rows),
                },
            },
        },
    )


def _driver(*, custom_base_url: str | None = None) -> SourceDriver:
    return SourceDriver(
        DbtSource(), DbtSourceConfig(account_id="12345", api_token="token", custom_base_url=custom_base_url)
    )


class TestGetBaseUrl:
    def test_non_https_custom_url_rejected(self):
        with pytest.raises(DbtHostNotAllowedError):
            get_base_url("us", "http://internal-host")


class TestCoerceDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC), datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)),
            (datetime(2026, 6, 1, 12, 0, 0), datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)),
            (date(2026, 6, 1), datetime(2026, 6, 1, tzinfo=UTC)),
            ("2026-06-01T12:00:00Z", datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)),
            ("2026-06-01 12:00:00+00:00", datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)),
            ("2026-06-01T12:00:00", datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)),
            ("not-a-date", None),
            (12345, None),
            (None, None),
        ],
    )
    def test_coerce(self, value, expected):
        assert _coerce_datetime(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, schema_name, expected_valid, expected_error_fragment",
        [
            (200, None, True, None),
            (401, None, False, "Invalid dbt API token"),
            # A 403 at source-create means the token authenticated but lacks the permission for
            # this probe — creation must go through so per-endpoint checks can guide the user.
            (403, None, True, None),
            (403, "runs", False, "permissions"),
            (404, None, False, "not found"),
        ],
    )
    def test_status_mapping(self, status_code, schema_name, expected_valid, expected_error_fragment):
        with scripted_network([ScriptedResponse(status=status_code, json={"status": {}})]):
            valid, error = validate_credentials(
                api_token="token", account_id="12345", region="us", custom_base_url=None, schema_name=schema_name
            )

        assert valid is expected_valid
        if expected_error_fragment is None:
            assert error is None
        else:
            assert expected_error_fragment in (error or "")

    def test_probes_account_endpoint_without_following_redirects(self):
        with scripted_network([ScriptedResponse(status=302, headers={"Location": "http://127.0.0.1/"})]) as network:
            valid, _error = validate_credentials(
                api_token="token", account_id="12345", region="emea", custom_base_url=None
            )

        assert valid is False
        assert len(network.requests_log) == 1
        assert network.requests_log[0].url == "https://emea.dbt.com/api/v2/accounts/12345/"
        assert network.requests_log[0].headers["authorization"] == "Token token"

    def test_redirect_is_rejected(self):
        # A custom host could 3xx to an internal address, defeating the host check (SSRF).
        with scripted_network([ScriptedResponse(status=302, headers={"Location": "http://127.0.0.1/"})]) as network:
            valid, error = validate_credentials(
                api_token="token", account_id="12345", region="us", custom_base_url=None
            )

        assert valid is False
        assert error is not None
        assert len(network.requests_log) == 1

    def test_non_https_custom_url_fails_without_request(self):
        with scripted_network([]) as network:
            valid, _error = validate_credentials(
                api_token="token", account_id="12345", region="us", custom_base_url="http://internal"
            )

        assert valid is False
        assert network.requests_log == []


class TestGetEndpointPermissions:
    def test_denied_endpoints_get_a_reason(self):
        with scripted_network(
            route(
                {
                    "/users/": [
                        ScriptedResponse(status=403, json={"status": {"user_message": "Insufficient permissions"}})
                    ],
                    "/projects/": [_page([{"id": 1}])],
                }
            )
        ) as network:
            result = get_endpoint_permissions(
                api_token="token",
                account_id="12345",
                region="us",
                custom_base_url=None,
                team_id=1,
                endpoints=["users", "projects"],
            )

        assert result["projects"] is None
        assert "Insufficient permissions" in (result["users"] or "")
        assert [request.param("limit") for request in network.requests_log] == ["1", "1"]

    def test_network_errors_do_not_report_missing_permission(self):
        # A blip is not a denial — only a real 401/403/404 should flag the table.
        with scripted_network(always(ConnectionError("boom"))) as network:
            result = get_endpoint_permissions(
                api_token="token",
                account_id="12345",
                region="us",
                custom_base_url=None,
                team_id=1,
                endpoints=["projects", "repositories"],
            )

        assert result == {"projects": None, "repositories": None}
        # repositories has no account-level path; its probe is the projects list it fans out over.
        assert {request.path for request in network.requests_log} == {"/api/v3/accounts/12345/projects/"}

    def test_discovery_endpoints_report_one_shared_probe_result(self):
        # An Admin API token is not automatically accepted by the metadata service, and the
        # rejection arrives as HTTP 200 with an errors body.
        with scripted_network(
            route(
                {
                    "/graphql": [ScriptedResponse(json={"errors": [{"message": "No token was provided."}]})],
                    "/projects/": [_page([{"id": 1}])],
                }
            )
        ) as network:
            result = get_endpoint_permissions(
                api_token="token",
                account_id="12345",
                region="us",
                custom_base_url=None,
                team_id=1,
                endpoints=["models", "projects"],
            )

        assert result["models"] == "No token was provided."
        assert result["projects"] is None
        assert [request.method for request in network.requests_log] == ["POST", "GET"]
        assert network.requests_log[0].path == "/graphql"

    def test_unsafe_custom_host_is_rejected_without_probing(self):
        # The probes are separate outbound requests, so an internal custom host must be blocked
        # here too — not just in validate_credentials — before any request goes out (SSRF).
        with (
            mock.patch(f"{MODULE}._is_host_safe", return_value=(False, "Host not allowed")),
            mock.patch(f"{MODULE}.make_tracked_session") as mock_session,
        ):
            result = get_endpoint_permissions(
                api_token="token",
                account_id="12345",
                region="us",
                custom_base_url="https://internal.local",
                team_id=1,
                endpoints=["projects", "users"],
            )

        mock_session.return_value.get.assert_not_called()
        assert result["projects"] is not None
        assert result["users"] is not None


class TestGetRows:
    def test_full_refresh_paginates_until_total_count(self):
        page1_rows = [{"id": index} for index in range(3)]
        page2_rows = [{"id": 100 + index} for index in range(2)]
        result = _driver().run(
            "projects",
            [_page(page1_rows, count=100, total_count=137), _page(page2_rows, count=37, total_count=137)],
        )

        assert result.raised is None
        assert result.items == [page1_rows, page2_rows]
        assert len(result.requests) == 2
        assert result.urls[0].startswith("https://cloud.getdbt.com/api/v3/accounts/12345/projects/")
        assert result.params("offset") == ["0", "100"]
        assert result.requests[0].param("order_by") is None
        assert result.requests[0].headers["authorization"] == "Token token"

    def test_runs_incremental_stops_once_page_dips_below_watermark(self):
        watermark = datetime(2026, 6, 10, tzinfo=UTC)
        page1_rows = [{"id": 3, "created_at": "2026-06-20T00:00:00Z"}]
        page2_rows: list[dict[str, Any]] = [
            {"id": 2, "created_at": "2026-06-11T00:00:00Z"},
            # Within the 24h lookback window below the watermark: re-pulled so late status
            # changes land; merge dedupes it on the primary key.
            {"id": 1, "created_at": "2026-06-09T12:00:00Z"},
            # Missing cursor value: kept to stay on the safe side.
            {"id": 0},
            # Below the effective watermark: already synced, walking stops here.
            {"id": -1, "created_at": "2026-06-01T00:00:00Z"},
        ]
        result = _driver().run(
            "runs",
            [_page(page1_rows, count=100, total_count=500), _page(page2_rows, count=100, total_count=500)],
            db_incremental_field_last_value=watermark,
            incremental_field="created_at",
        )

        assert result.raised is None
        assert result.items == [page1_rows, page2_rows[:3]]
        # The third page (offset=200) must never be requested — that's the whole point of the
        # newest-first walk: incremental syncs don't re-crawl history.
        assert result.params("offset") == ["0", "100"]

    @pytest.mark.parametrize(
        "data",
        [
            [{"developer": {"total": 5, "in_use": 3}, "read_only": {"total": 10, "in_use": 0}, "note": None}],
            {"developer": {"total": 5, "in_use": 3}, "read_only": {"total": 10, "in_use": 0}, "note": None},
        ],
    )
    def test_license_allocations_become_one_row_per_license_type(self, data):
        # The spec types `data` as a list, but the allocation is one object per account, so accept both.
        result = _driver().run("license_allocations", [ScriptedResponse(json={"data": data})])

        assert result.raised is None
        assert result.rows == [
            {"license_type": "developer", "total": 5, "in_use": 3},
            {"license_type": "read_only", "total": 10, "in_use": 0},
        ]
        assert result.paths == ["/api/v2/accounts/12345/licenses/"]

    def test_custom_base_url_is_used(self):
        result = _driver(custom_base_url="https://ab123.us1.dbt.com/").run("projects", [_page([])])

        assert result.raised is None
        assert result.urls[0].startswith("https://ab123.us1.dbt.com/api/v3/accounts/12345/")


class TestDbtSourceResponse:
    def test_full_refresh_response_shape(self):
        result = _driver().run("projects", [_page([])])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == "projects"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None


class TestGetDiscoveryUrl:
    def test_custom_url_overrides_region(self):
        assert (
            get_discovery_url("us", "  https://ab123.metadata.us1.dbt.com/graphql/  ")
            == "https://ab123.metadata.us1.dbt.com/graphql"
        )

    def test_non_https_custom_url_rejected(self):
        with pytest.raises(DbtHostNotAllowedError):
            get_discovery_url("us", "http://internal-host/graphql")


class TestRaiseForGraphqlErrors:
    @pytest.mark.parametrize(
        "message, expected_exception, expected_fragment",
        [
            ("Query rate limit exceeded", DbtRetryableError, "rate limited"),
            ("Too many requests", DbtRetryableError, "rate limited"),
            ("No token was provided.", Exception, DISCOVERY_TOKEN_ERROR),
            ("You do not have permission to perform this action", Exception, DISCOVERY_TOKEN_ERROR),
            ("Environment 1 not found", Exception, "dbt Discovery API error"),
        ],
    )
    def test_error_classification(self, message, expected_exception, expected_fragment):
        # The Discovery API reports failures with HTTP 200 and an errors body, so there is no
        # status code to classify on: a throttle read as terminal fails the sync, and a bad token
        # read as retryable burns five attempts before failing anyway.
        with pytest.raises(expected_exception) as error:
            _raise_for_graphql_errors({"errors": [{"message": message}]})

        assert expected_fragment in str(error.value)

    def test_body_with_neither_data_nor_errors_raises(self):
        with pytest.raises(Exception, match="Unexpected dbt Discovery API response"):
            _raise_for_graphql_errors({"extensions": {}})


def _graphql_connection(
    applied_field: str, nodes: list[dict[str, Any]], *, has_next: bool = False, end_cursor: Optional[str] = None
) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": {
                "environment": {
                    "applied": {
                        applied_field: {
                            "edges": [{"node": node} for node in nodes],
                            "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                        }
                    }
                }
            }
        }
    )


def _graphql_list(applied_field: str, rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": {"environment": {"applied": {applied_field: rows}}}})


class TestRunFanout:
    def test_missing_child_is_skipped_rather_than_failing_the_sync(self):
        # Runs age out and cancelled runs never save artifacts, so a 404 on one run must not take
        # the whole table down with it.
        result = _driver().run(
            "run_artifacts",
            [
                _page(
                    [{"id": 7, "created_at": "2026-06-20T00:00:00Z"}, {"id": 8, "created_at": "2026-06-19T00:00:00Z"}]
                ),
                ScriptedResponse(status=404, json={"status": {"user_message": "Not found"}}),
                ScriptedResponse(json={"data": ["manifest.json"]}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"run_id": 8, "run_created_at": "2026-06-19T00:00:00Z", "path": "manifest.json"}]]

    def test_incremental_does_not_fan_out_below_the_watermark(self):
        # Without the newest-first stop, every sync re-expands each historical run, which costs
        # one extra request per run forever.
        result = _driver().run(
            "run_steps",
            [
                _page(
                    [
                        {"id": 9, "created_at": "2026-06-20T00:00:00Z"},
                        {"id": 1, "created_at": "2026-01-01T00:00:00Z"},
                    ],
                    count=100,
                    total_count=500,
                ),
                ScriptedResponse(
                    json={"data": {"id": 9, "run_steps": [{"index": 1, "name": "dbt build", "status": 10}]}}
                ),
            ],
            db_incremental_field_last_value=datetime(2026, 6, 10, tzinfo=UTC),
            incremental_field="run_created_at",
        )

        assert result.raised is None
        assert result.items == [
            [{"index": 1, "name": "dbt build", "status": 10, "run_id": 9, "run_created_at": "2026-06-20T00:00:00Z"}]
        ]
        # The aged run is never expanded, and the second runs page is never requested.
        assert result.paths == ["/api/v2/accounts/12345/runs/", "/api/v2/accounts/12345/runs/9/"]


class TestDiscoverySync:
    def test_environment_without_applied_state_yields_nothing(self):
        result = _driver().run(
            "sources",
            [
                _page([{"id": 10, "type": "deployment"}]),
                ScriptedResponse(json={"data": {"environment": {"applied": None}}}),
            ],
        )

        assert result.raised is None
        assert result.rows == []

    @pytest.mark.parametrize("end_cursor", [None, "cursor-1"])
    def test_a_page_that_does_not_advance_the_cursor_fails(self, end_cursor):
        # hasNextPage with no new cursor would re-request the page just read until the activity
        # times out. Ending the walk quietly instead would write a partial table that reads as
        # complete.
        result = _driver().run(
            "models",
            [
                _page([{"id": 10, "type": "deployment"}]),
                _graphql_connection("models", [{"uniqueId": "model.a.b"}], has_next=True, end_cursor="cursor-1"),
                _graphql_connection("models", [{"uniqueId": "model.a.c"}], has_next=True, end_cursor=end_cursor),
            ],
            resume_state=DbtResumeConfig(),
        )

        assert isinstance(result.raised, Exception)
        assert "without advancing the cursor" in str(result.raised)

    def test_model_historical_runs_asks_once_per_model(self):
        # modelHistoricalRuns takes a single model at a time, so the model list has to be walked
        # first; querying the connection directly returns nothing.
        result = _driver().run(
            "model_historical_runs",
            [
                _page([{"id": 10, "type": "deployment"}]),
                _graphql_connection("models", [{"uniqueId": "model.a.b"}, {"uniqueId": "model.a.c"}]),
                _graphql_list("modelHistoricalRuns", [{"uniqueId": "model.a.b", "runId": 1}]),
                _graphql_list("modelHistoricalRuns", [{"uniqueId": "model.a.c", "runId": 2}]),
            ],
        )

        assert result.raised is None
        assert result.items == [
            [
                {"uniqueId": "model.a.b", "runId": 1, "environmentId": 10},
                {"uniqueId": "model.a.c", "runId": 2, "environmentId": 10},
            ]
        ]
        assert [request.json()["variables"]["uniqueId"] for request in result.requests[2:]] == [
            "model.a.b",
            "model.a.c",
        ]


class TestProjectFanout:
    def test_walks_every_project_and_pages_within_each(self):
        result = _driver().run(
            "repositories",
            route(
                {
                    "/accounts/12345/projects/": [_page([{"id": 1}, {"id": 2}, {"id": 3}])],
                    "/projects/1/repositories/": [
                        _page([{"id": 10, "project_id": 1}], count=100, total_count=101),
                        _page([{"id": 11, "project_id": 1}], count=1, total_count=101),
                    ],
                    "/projects/2/repositories/": [_page([])],
                    "/projects/3/repositories/": [_page([{"id": 30, "project_id": 3}])],
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [10, 11, 30]
        assert result.paths == [
            "/api/v3/accounts/12345/projects/",
            "/api/v3/accounts/12345/projects/1/repositories/",
            "/api/v3/accounts/12345/projects/1/repositories/",
            "/api/v3/accounts/12345/projects/2/repositories/",
            "/api/v3/accounts/12345/projects/3/repositories/",
        ]
        assert result.saved_states == [
            DbtResumeConfig(offset=100, parent_offset=0),
            DbtResumeConfig(parent_offset=1),
        ]

    def test_resumes_inside_the_saved_project(self):
        result = _driver().run(
            "repositories",
            route(
                {
                    "/accounts/12345/projects/": [_page([{"id": 1}, {"id": 2}])],
                    "/projects/2/repositories/": [_page([{"id": 21, "project_id": 2}], count=1, total_count=101)],
                }
            ),
            resume_state=DbtResumeConfig(offset=100, parent_offset=1),
        )

        assert result.raised is None
        assert result.rows == [{"id": 21, "project_id": 2}]
        assert result.paths == ["/api/v3/accounts/12345/projects/", "/api/v3/accounts/12345/projects/2/repositories/"]
        assert result.requests[1].param("offset") == "100"
