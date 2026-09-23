from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.dbt import (
    DISCOVERY_TOKEN_ERROR,
    DbtHostNotAllowedError,
    DbtResumeConfig,
    DbtRetryableError,
    _coerce_datetime,
    _raise_for_graphql_errors,
    dbt_source,
    get_base_url,
    get_discovery_url,
    get_endpoint_permissions,
    get_rows,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dbt.dbt"


def _response(*, status_code: int = 200, json_data: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    if not response.ok:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


def _page(rows: list[dict], *, count: Optional[int] = None, total_count: Optional[int] = None) -> mock.MagicMock:
    """A dbt API list response envelope."""
    return _response(
        json_data={
            "status": {"code": 200, "is_success": True},
            "data": rows,
            "extra": {
                "pagination": {
                    "count": count if count is not None else len(rows),
                    "total_count": total_count if total_count is not None else len(rows),
                },
            },
        }
    )


def _manager(resume: Optional[DbtResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _requested_query(session: mock.MagicMock, call_index: int) -> dict[str, list[str]]:
    url = session.get.call_args_list[call_index].args[0]
    return parse_qs(urlparse(url).query)


class TestGetBaseUrl:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "https://cloud.getdbt.com"),
            ("emea", "https://emea.dbt.com"),
            ("au", "https://au.dbt.com"),
            ("unknown", "https://cloud.getdbt.com"),
        ],
    )
    def test_region_mapping(self, region, expected):
        assert get_base_url(region, None) == expected

    @pytest.mark.parametrize(
        "custom, expected",
        [
            ("https://ab123.us1.dbt.com", "https://ab123.us1.dbt.com"),
            ("https://ab123.us1.dbt.com/", "https://ab123.us1.dbt.com"),
            ("  https://single-tenant.example.com  ", "https://single-tenant.example.com"),
            ("", "https://cloud.getdbt.com"),
            ("   ", "https://cloud.getdbt.com"),
            (None, "https://cloud.getdbt.com"),
        ],
    )
    def test_custom_base_url_overrides_region(self, custom, expected):
        assert get_base_url("us", custom) == expected

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
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status_code=status_code, json_data={"status": {}})

            valid, error = validate_credentials(
                api_token="token", account_id="12345", region="us", custom_base_url=None, schema_name=schema_name
            )

        assert valid is expected_valid
        if expected_error_fragment is None:
            assert error is None
        else:
            assert expected_error_fragment in (error or "")

    def test_probes_account_endpoint_without_following_redirects(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status_code=200, json_data={"status": {}})

            validate_credentials(api_token="token", account_id="12345", region="emea", custom_base_url=None)

            call = mock_session.return_value.get.call_args
            assert call.args[0] == "https://emea.dbt.com/api/v2/accounts/12345/"
            assert call.kwargs["headers"]["Authorization"] == "Token token"
            assert call.kwargs["allow_redirects"] is False

    def test_redirect_is_rejected(self):
        # A custom host could 3xx to an internal address, defeating the host check (SSRF).
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status_code=302)

            valid, error = validate_credentials(
                api_token="token", account_id="12345", region="us", custom_base_url=None
            )

        assert valid is False
        assert error is not None

    def test_non_https_custom_url_fails_without_request(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            valid, _error = validate_credentials(
                api_token="token", account_id="12345", region="us", custom_base_url="http://internal"
            )

        assert valid is False
        mock_session.return_value.get.assert_not_called()


class TestGetEndpointPermissions:
    def test_denied_endpoints_get_a_reason(self):
        responses = {
            "https://cloud.getdbt.com/api/v3/accounts/12345/users/?limit=1": _response(
                status_code=403, json_data={"status": {"user_message": "Insufficient permissions"}}
            ),
            "https://cloud.getdbt.com/api/v3/accounts/12345/projects/?limit=1": _page([{"id": 1}]),
        }
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = lambda url, **kwargs: responses[url]

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

    def test_network_errors_do_not_report_missing_permission(self):
        # A blip is not a denial — only a real 401/403/404 should flag the table.
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

            result = get_endpoint_permissions(
                api_token="token",
                account_id="12345",
                region="us",
                custom_base_url=None,
                team_id=1,
                endpoints=["projects"],
            )

        assert result["projects"] is None

    def test_run_fanout_endpoints_probe_the_runs_list(self):
        # A run fan-out has no list path of its own, so the permission that decides whether it can
        # sync is the runs list. Reading the missing path instead would break the schema picker.
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _page([{"id": 1}])

            result = get_endpoint_permissions(
                api_token="token",
                account_id="12345",
                region="us",
                custom_base_url=None,
                team_id=1,
                endpoints=["run_steps", "run_artifacts"],
            )

        assert result == {"run_steps": None, "run_artifacts": None}
        probed = {call.args[0] for call in mock_session.return_value.get.call_args_list}
        assert probed == {"https://cloud.getdbt.com/api/v2/accounts/12345/runs/?limit=1"}

    def test_discovery_endpoints_report_one_shared_probe_result(self):
        # An Admin API token is not automatically accepted by the metadata service, and the
        # rejection arrives as HTTP 200 with an errors body.
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _page([{"id": 1}])
            mock_session.return_value.post.return_value = _response(
                json_data={"errors": [{"message": "No token was provided."}]}
            )

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
        assert mock_session.return_value.post.call_count == 1

    def test_discovery_probe_is_skipped_when_no_discovery_table_is_selected(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _page([{"id": 1}])

            get_endpoint_permissions(
                api_token="token",
                account_id="12345",
                region="us",
                custom_base_url=None,
                team_id=1,
                endpoints=["projects"],
            )

        mock_session.return_value.post.assert_not_called()

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
    def _get_rows(self, session: mock.MagicMock, manager: mock.MagicMock, endpoint: str, **kwargs: Any) -> list[Any]:
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            return list(
                get_rows(
                    api_token="token",
                    account_id="12345",
                    region=kwargs.pop("region", "us"),
                    custom_base_url=kwargs.pop("custom_base_url", None),
                    endpoint=endpoint,
                    team_id=1,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    **kwargs,
                )
            )

    def test_full_refresh_paginates_until_total_count(self):
        session = mock.MagicMock()
        page1_rows = [{"id": index} for index in range(3)]
        page2_rows = [{"id": 100 + index} for index in range(2)]
        session.get.side_effect = [
            _page(page1_rows, count=100, total_count=137),
            _page(page2_rows, count=37, total_count=137),
        ]
        manager = _manager()

        batches = self._get_rows(session, manager, "projects")

        assert batches == [page1_rows, page2_rows]
        assert session.get.call_count == 2
        assert (
            session.get.call_args_list[0].args[0].startswith("https://cloud.getdbt.com/api/v3/accounts/12345/projects/")
        )
        assert _requested_query(session, 0)["offset"] == ["0"]
        assert _requested_query(session, 1)["offset"] == ["100"]
        assert "order_by" not in _requested_query(session, 0)
        assert session.get.call_args_list[0].kwargs["headers"]["Authorization"] == "Token token"

    @pytest.mark.parametrize(
        "endpoint, expected_path",
        [
            ("accounts", "/api/v3/accounts/"),
            ("projects", "/api/v3/accounts/12345/projects/"),
            ("environments", "/api/v3/accounts/12345/environments/"),
            ("users", "/api/v3/accounts/12345/users/"),
            # jobs and runs are v2-only — dbt v3 exposes neither, so the v3 default must keep
            # reading them from v2; unifying them onto v3 would 404 every jobs/runs sync.
            ("jobs", "/api/v2/accounts/12345/jobs/"),
            ("runs", "/api/v2/accounts/12345/runs/"),
        ],
    )
    def test_endpoint_uses_correct_dbt_api_version(self, endpoint, expected_path):
        session = mock.MagicMock()
        session.get.side_effect = [_page([])]

        self._get_rows(session, _manager(), endpoint)

        assert session.get.call_args_list[0].args[0].startswith(f"https://cloud.getdbt.com{expected_path}")

    def test_state_saved_after_yield_only_when_more_pages_remain(self):
        session = mock.MagicMock()
        session.get.side_effect = [
            _page([{"id": 1}], count=100, total_count=137),
            _page([{"id": 2}], count=37, total_count=137),
        ]
        manager = _manager()

        self._get_rows(session, manager, "projects")

        manager.save_state.assert_called_once_with(DbtResumeConfig(offset=100))

    def test_stops_when_offset_reaches_total_count(self):
        session = mock.MagicMock()
        session.get.side_effect = [_page([{"id": 1}], count=100, total_count=100)]
        manager = _manager()

        batches = self._get_rows(session, manager, "projects")

        assert batches == [[{"id": 1}]]
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    def test_empty_page_yields_nothing(self):
        session = mock.MagicMock()
        session.get.side_effect = [_page([])]
        manager = _manager()

        assert self._get_rows(session, manager, "projects") == []

    def test_resume_starts_from_saved_offset(self):
        session = mock.MagicMock()
        session.get.side_effect = [_page([{"id": 1}], count=5, total_count=105)]
        manager = _manager(resume=DbtResumeConfig(offset=100))

        self._get_rows(session, manager, "projects")

        assert _requested_query(session, 0)["offset"] == ["100"]

    def test_runs_walk_newest_first(self):
        session = mock.MagicMock()
        session.get.side_effect = [_page([{"id": 1, "created_at": "2026-06-10T00:00:00Z"}])]
        manager = _manager()

        self._get_rows(session, manager, "runs")

        assert _requested_query(session, 0)["order_by"] == ["-created_at"]

    def test_runs_incremental_stops_once_page_dips_below_watermark(self):
        watermark = datetime(2026, 6, 10, tzinfo=UTC)
        session = mock.MagicMock()
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
        session.get.side_effect = [
            _page(page1_rows, count=100, total_count=500),
            _page(page2_rows, count=100, total_count=500),
        ]
        manager = _manager()

        batches = self._get_rows(
            session,
            manager,
            "runs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
            incremental_field="created_at",
        )

        assert batches == [page1_rows, page2_rows[:3]]
        # The third page (offset=200) must never be requested — that's the whole point of the
        # newest-first walk: incremental syncs don't re-crawl history.
        assert session.get.call_count == 2

    def test_runs_without_watermark_walk_all_pages(self):
        session = mock.MagicMock()
        page1_rows = [{"id": 2, "created_at": "2026-06-10T00:00:00Z"}]
        page2_rows = [{"id": 1, "created_at": "2026-01-01T00:00:00Z"}]
        session.get.side_effect = [
            _page(page1_rows, count=100, total_count=101),
            _page(page2_rows, count=1, total_count=101),
        ]
        manager = _manager()

        batches = self._get_rows(
            session,
            manager,
            "runs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="created_at",
        )

        assert batches == [page1_rows, page2_rows]

    def test_custom_base_url_is_used(self):
        session = mock.MagicMock()
        session.get.side_effect = [_page([])]
        manager = _manager()

        self._get_rows(session, manager, "projects", custom_base_url="https://ab123.us1.dbt.com/")

        assert session.get.call_args_list[0].args[0].startswith("https://ab123.us1.dbt.com/api/v3/accounts/12345/")


class TestDbtSourceResponse:
    def test_runs_response_shape(self):
        response = dbt_source(
            api_token="token",
            account_id="12345",
            region="us",
            custom_base_url=None,
            endpoint="runs",
            team_id=1,
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )

        assert response.name == "runs"
        assert response.primary_keys == ["id"]
        # Runs are walked newest-first; declaring asc here would checkpoint the watermark to
        # ~now after the first batch and corrupt resume semantics.
        assert response.sort_mode == "desc"
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"

    @pytest.mark.parametrize(
        "endpoint, primary_keys",
        [
            # A key that is not unique table-wide seeds duplicate rows that every later merge
            # multi-matches: fan-out children need the parent id, and Discovery rows repeat their
            # uniqueId once per environment.
            ("run_steps", ["run_id", "index"]),
            ("run_artifacts", ["run_id", "path"]),
            ("audit_logs", ["id"]),
            ("models", ["environmentId", "uniqueId"]),
            ("model_historical_runs", ["environmentId", "uniqueId", "runId"]),
        ],
    )
    def test_primary_keys_are_unique_table_wide(self, endpoint, primary_keys):
        response = dbt_source(
            api_token="token",
            account_id="12345",
            region="us",
            custom_base_url=None,
            endpoint=endpoint,
            team_id=1,
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == primary_keys

    def test_full_refresh_response_shape(self):
        response = dbt_source(
            api_token="token",
            account_id="12345",
            region="us",
            custom_base_url=None,
            endpoint="projects",
            team_id=1,
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )

        assert response.name == "projects"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None


class TestGetDiscoveryUrl:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", "https://metadata.cloud.getdbt.com/graphql"),
            ("emea", "https://metadata.emea.dbt.com/graphql"),
            ("au", "https://metadata.au.dbt.com/graphql"),
            ("unknown", "https://metadata.cloud.getdbt.com/graphql"),
        ],
    )
    def test_region_mapping(self, region, expected):
        # The Discovery API lives on its own hostname per region; pointing a region at the wrong
        # one 404s every model/test/source table while the Admin API tables keep working.
        assert get_discovery_url(region, None) == expected

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

    def test_data_without_errors_passes(self):
        _raise_for_graphql_errors({"data": {"environment": None}})

    def test_body_with_neither_data_nor_errors_raises(self):
        with pytest.raises(Exception, match="Unexpected dbt Discovery API response"):
            _raise_for_graphql_errors({"extensions": {}})


def _graphql_connection(
    applied_field: str, nodes: list[dict], *, has_next: bool = False, end_cursor: Optional[str] = None
) -> mock.MagicMock:
    return _response(
        json_data={
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


def _graphql_list(applied_field: str, rows: list[dict]) -> mock.MagicMock:
    return _response(json_data={"data": {"environment": {"applied": {applied_field: rows}}}})


def _posted_variables(session: mock.MagicMock, call_index: int) -> dict[str, Any]:
    return session.post.call_args_list[call_index].kwargs["json"]["variables"]


class TestRunFanout:
    def _get_rows(self, session: mock.MagicMock, manager: mock.MagicMock, endpoint: str, **kwargs: Any) -> list[Any]:
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            return list(
                get_rows(
                    api_token="token",
                    account_id="12345",
                    region="us",
                    custom_base_url=None,
                    endpoint=endpoint,
                    team_id=1,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    **kwargs,
                )
            )

    def test_run_steps_expand_each_run_from_the_run_detail_route(self):
        # run_steps is only an include_related value on the run-detail route, and dbt wants a JSON
        # array literal. If either is wrong, the table stays permanently empty.
        session = mock.MagicMock()
        session.get.side_effect = [
            _page([{"id": 7, "created_at": "2026-06-20T00:00:00Z"}]),
            _response(
                json_data={
                    "data": {
                        "id": 7,
                        "run_steps": [
                            {"index": 1, "name": "dbt deps", "status": 10},
                            {"index": 2, "name": "dbt build", "status": 20},
                        ],
                    }
                }
            ),
        ]

        batches = self._get_rows(session, _manager(), "run_steps")

        assert batches == [
            [
                {"index": 1, "name": "dbt deps", "status": 10, "run_id": 7, "run_created_at": "2026-06-20T00:00:00Z"},
                {"index": 2, "name": "dbt build", "status": 20, "run_id": 7, "run_created_at": "2026-06-20T00:00:00Z"},
            ]
        ]
        assert _requested_query(session, 0)["order_by"] == ["-created_at"]
        assert session.get.call_args_list[1].args[0] == (
            "https://cloud.getdbt.com/api/v2/accounts/12345/runs/7/?include_related=%5B%22run_steps%22%5D"
        )

    def test_run_artifacts_turn_bare_paths_into_rows(self):
        session = mock.MagicMock()
        session.get.side_effect = [
            _page([{"id": 7, "created_at": "2026-06-20T00:00:00Z"}]),
            _response(json_data={"data": ["manifest.json", "run_results.json"]}),
        ]

        batches = self._get_rows(session, _manager(), "run_artifacts")

        assert batches == [
            [
                {"run_id": 7, "run_created_at": "2026-06-20T00:00:00Z", "path": "manifest.json"},
                {"run_id": 7, "run_created_at": "2026-06-20T00:00:00Z", "path": "run_results.json"},
            ]
        ]

    def test_missing_child_is_skipped_rather_than_failing_the_sync(self):
        # Runs age out and cancelled runs never save artifacts, so a 404 on one run must not take
        # the whole table down with it.
        session = mock.MagicMock()
        session.get.side_effect = [
            _page([{"id": 7, "created_at": "2026-06-20T00:00:00Z"}, {"id": 8, "created_at": "2026-06-19T00:00:00Z"}]),
            _response(status_code=404, json_data={"status": {"user_message": "Not found"}}),
            _response(json_data={"data": ["manifest.json"]}),
        ]

        batches = self._get_rows(session, _manager(), "run_artifacts")

        assert batches == [[{"run_id": 8, "run_created_at": "2026-06-19T00:00:00Z", "path": "manifest.json"}]]

    def test_incremental_does_not_fan_out_below_the_watermark(self):
        # Without the newest-first stop, every sync re-expands each historical run, which costs
        # one extra request per run forever.
        session = mock.MagicMock()
        session.get.side_effect = [
            _page(
                [
                    {"id": 9, "created_at": "2026-06-20T00:00:00Z"},
                    {"id": 1, "created_at": "2026-01-01T00:00:00Z"},
                ],
                count=100,
                total_count=500,
            ),
            _response(json_data={"data": {"id": 9, "run_steps": [{"index": 1, "name": "dbt build", "status": 10}]}}),
        ]

        batches = self._get_rows(
            session,
            _manager(),
            "run_steps",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 10, tzinfo=UTC),
            incremental_field="run_created_at",
        )

        assert batches == [
            [{"index": 1, "name": "dbt build", "status": 10, "run_id": 9, "run_created_at": "2026-06-20T00:00:00Z"}]
        ]
        # The aged run is never expanded, and the second runs page is never requested.
        assert session.get.call_count == 2

    def test_resume_restarts_from_the_saved_parent_page(self):
        session = mock.MagicMock()
        session.get.side_effect = [
            _page([{"id": 7, "created_at": "2026-06-20T00:00:00Z"}]),
            _response(json_data={"data": ["manifest.json"]}),
        ]

        self._get_rows(session, _manager(resume=DbtResumeConfig(parent_offset=200)), "run_artifacts")

        assert _requested_query(session, 0)["offset"] == ["200"]


class TestDiscoverySync:
    def _get_rows(self, session: mock.MagicMock, manager: mock.MagicMock, endpoint: str, **kwargs: Any) -> list[Any]:
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            return list(
                get_rows(
                    api_token="token",
                    account_id="12345",
                    region="us",
                    custom_base_url=None,
                    endpoint=endpoint,
                    team_id=1,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    **kwargs,
                )
            )

    def test_only_deployment_environments_are_queried(self):
        # Development environments have no applied state, so querying them spends a request per
        # environment to get nothing back.
        session = mock.MagicMock()
        session.get.side_effect = [
            _page([{"id": 10, "type": "deployment"}, {"id": 11, "type": "development"}, {"type": "deployment"}])
        ]
        session.post.side_effect = [_graphql_connection("models", [{"uniqueId": "model.a.b"}])]

        self._get_rows(session, _manager(), "models")

        assert session.post.call_count == 1
        assert _posted_variables(session, 0)["environmentId"] == 10

    def test_pages_are_walked_and_stamped_with_the_environment(self):
        # environmentId is half the primary key. If a node type ever stops resolving it, unstamped
        # rows from different environments collide on uniqueId and every later merge multi-matches
        # the duplicates.
        session = mock.MagicMock()
        session.get.side_effect = [_page([{"id": 10, "type": "deployment"}])]
        session.post.side_effect = [
            _graphql_connection("tests", [{"uniqueId": "test.a.b"}], has_next=True, end_cursor="cursor-1"),
            _graphql_connection("tests", [{"uniqueId": "test.a.c", "environmentId": 99}]),
        ]
        manager = _manager()

        batches = self._get_rows(session, manager, "tests")

        assert batches == [
            [{"uniqueId": "test.a.b", "environmentId": 10}],
            [{"uniqueId": "test.a.c", "environmentId": 10}],
        ]
        assert _posted_variables(session, 0)["after"] is None
        assert _posted_variables(session, 1)["after"] == "cursor-1"
        manager.save_state.assert_called_once_with(DbtResumeConfig(parent_offset=0, cursor="cursor-1"))

    def test_environment_without_applied_state_yields_nothing(self):
        session = mock.MagicMock()
        session.get.side_effect = [_page([{"id": 10, "type": "deployment"}])]
        session.post.side_effect = [_response(json_data={"data": {"environment": {"applied": None}}})]

        assert self._get_rows(session, _manager(), "sources") == []

    def test_resume_continues_the_saved_cursor(self):
        session = mock.MagicMock()
        session.get.side_effect = [_page([{"id": 10, "type": "deployment"}])]
        session.post.side_effect = [_graphql_connection("seeds", [{"uniqueId": "seed.a.b"}])]

        self._get_rows(session, _manager(resume=DbtResumeConfig(parent_offset=0, cursor="cursor-9")), "seeds")

        assert _posted_variables(session, 0)["after"] == "cursor-9"

    @pytest.mark.parametrize("end_cursor", [None, "cursor-1"])
    def test_a_page_that_does_not_advance_the_cursor_fails(self, end_cursor):
        # hasNextPage with no new cursor would re-request the page just read until the activity
        # times out. Ending the walk quietly instead would write a partial table that reads as
        # complete.
        session = mock.MagicMock()
        session.get.side_effect = [_page([{"id": 10, "type": "deployment"}])]
        session.post.side_effect = [
            _graphql_connection("models", [{"uniqueId": "model.a.b"}], has_next=True, end_cursor="cursor-1"),
            _graphql_connection("models", [{"uniqueId": "model.a.c"}], has_next=True, end_cursor=end_cursor),
        ]

        with pytest.raises(Exception, match="without advancing the cursor"):
            self._get_rows(session, _manager(resume=DbtResumeConfig()), "models")

    def test_model_historical_runs_asks_once_per_model(self):
        # modelHistoricalRuns takes a single model at a time, so the model list has to be walked
        # first; querying the connection directly returns nothing.
        session = mock.MagicMock()
        session.get.side_effect = [_page([{"id": 10, "type": "deployment"}])]
        session.post.side_effect = [
            _graphql_connection("models", [{"uniqueId": "model.a.b"}, {"uniqueId": "model.a.c"}]),
            _graphql_list("modelHistoricalRuns", [{"uniqueId": "model.a.b", "runId": 1}]),
            _graphql_list("modelHistoricalRuns", [{"uniqueId": "model.a.c", "runId": 2}]),
        ]

        batches = self._get_rows(session, _manager(), "model_historical_runs")

        assert batches == [
            [
                {"uniqueId": "model.a.b", "runId": 1, "environmentId": 10},
                {"uniqueId": "model.a.c", "runId": 2, "environmentId": 10},
            ]
        ]
        assert [_posted_variables(session, index)["uniqueId"] for index in (1, 2)] == ["model.a.b", "model.a.c"]
