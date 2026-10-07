import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro import jamf_pro as jamf_pro_module
from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.jamf_pro import (
    JamfProConfigurationError,
    JamfProCredentials,
    JamfProHostNotAllowedError,
    JamfProPaginationLimitError,
    JamfProResponseTooLargeError,
    JamfProResponseTooSlowError,
    JamfProResumeConfig,
    JamfProTokenManager,
    _build_params,
    _build_url,
    _format_incremental_value,
    get_rows,
    jamf_pro_source,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.settings import JAMF_PRO_ENDPOINTS

CLIENT_CREDENTIALS = JamfProCredentials(method="client_credentials", client_id="cid", client_secret="secret")
BASIC_CREDENTIALS = JamfProCredentials(method="basic", username="admin", password="hunter2")

TOKEN_JSON = {"access_token": "tok", "expires_in": 1199, "token_type": "Bearer"}


def _response(*, status_code: int = 200, json_data: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    # Responses are read via stream=True + iter_content, so serve the body in that shape. A fresh
    # iterator per call lets a single mock response stand in for repeated fetches.
    if json_data is not None:
        body = json.dumps(json_data).encode()
    else:
        body = text.encode()
    response.iter_content.side_effect = lambda *args, **kwargs: iter([body] if body else [])
    if status_code >= 400:
        error = requests.HTTPError(
            f"{status_code} Client Error: for url: https://example.jamfcloud.com", response=response
        )
        response.raise_for_status.side_effect = error
    return response


def _session(post_responses: list[Any] | None = None, get_responses: list[Any] | None = None) -> mock.MagicMock:
    session = mock.MagicMock()
    if post_responses is not None:
        session.post.side_effect = post_responses
    if get_responses is not None:
        session.get.side_effect = get_responses
    return session


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("example.jamfcloud.com", "example.jamfcloud.com"),
            ("https://example.jamfcloud.com", "example.jamfcloud.com"),
            ("http://example.jamfcloud.com/", "example.jamfcloud.com"),
            ("  example.jamfcloud.com  ", "example.jamfcloud.com"),
            ("example.jamfcloud.com/api/v1", "example.jamfcloud.com"),
            ("https://jamf.example.org/api/v1/computers-inventory", "jamf.example.org"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected


class TestBuildParams:
    def test_computers_incremental_builds_rsql_filter_and_sorts_by_cursor(self):
        params = _build_params(
            JAMF_PRO_ENDPOINTS["computers"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert params["filter"] == 'general.reportDate>="2024-01-01T00:00:00.000Z"'
        assert params["sort"] == "general.reportDate:asc"

    def test_computers_first_incremental_sync_has_no_filter_but_sorts_by_cursor(self):
        params = _build_params(
            JAMF_PRO_ENDPOINTS["computers"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )
        assert "filter" not in params
        assert params["sort"] == "general.reportDate:asc"

    def test_computers_full_refresh_has_no_filter(self):
        params = _build_params(
            JAMF_PRO_ENDPOINTS["computers"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert "filter" not in params
        assert params["sort"] == "id:asc"

    def test_non_incremental_endpoint_never_sends_filter(self):
        # Endpoints without a documented RSQL timestamp filter must not send one — the API
        # would reject the request.
        params = _build_params(
            JAMF_PRO_ENDPOINTS["scripts"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert "filter" not in params

    @pytest.mark.parametrize(
        "should_use_incremental_field, last_value, expected_filter",
        [
            (False, None, 'dateSent>="1970-01-01T00:00:00.000Z"'),
            (True, None, 'dateSent>="1970-01-01T00:00:00.000Z"'),
            (True, datetime(2024, 1, 1, tzinfo=UTC), 'dateSent>="2024-01-01T00:00:00.000Z"'),
        ],
    )
    def test_mdm_commands_always_sends_a_filter(self, should_use_incremental_field, last_value, expected_filter):
        params = _build_params(
            JAMF_PRO_ENDPOINTS["mdm_commands"],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )
        assert params["filter"] == expected_filter
        assert params["sort"] == "dateSent:asc"

    @pytest.mark.parametrize(
        "should_use_incremental_field, last_value, expected",
        [
            (False, None, {}),
            (True, datetime(2024, 1, 1, tzinfo=UTC), {"filter": 'updated>="2024-01-01T00:00:00.000Z"'}),
        ],
    )
    def test_update_statuses_sends_no_paging_params(self, should_use_incremental_field, last_value, expected):
        params = _build_params(
            JAMF_PRO_ENDPOINTS["managed_software_update_statuses"],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )
        assert params == expected

    def test_computers_requests_inventory_sections(self):
        params = _build_params(
            JAMF_PRO_ENDPOINTS["computers"], should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        url = _build_url("example.jamfcloud.com", JAMF_PRO_ENDPOINTS["computers"], params)
        # Sections must be repeated params, not a single comma-joined value.
        assert "section=GENERAL" in url
        assert "section=HARDWARE" in url


class TestTokenManager:
    def test_client_credentials_mints_oauth_token(self):
        session = _session(post_responses=[_response(json_data=TOKEN_JSON)])
        manager = JamfProTokenManager(session, "example.jamfcloud.com", CLIENT_CREDENTIALS)

        assert manager.get_token() == "tok"
        url = session.post.call_args.args[0]
        assert url == "https://example.jamfcloud.com/api/oauth/token"
        assert session.post.call_args.kwargs["data"]["grant_type"] == "client_credentials"

    def test_basic_mints_token_with_http_basic(self):
        session = _session(post_responses=[_response(json_data={"token": "tok2", "expires": "2100-01-01T00:00:00Z"})])
        manager = JamfProTokenManager(session, "example.jamfcloud.com", BASIC_CREDENTIALS)

        assert manager.get_token() == "tok2"
        url = session.post.call_args.args[0]
        assert url == "https://example.jamfcloud.com/api/v1/auth/token"
        assert session.post.call_args.kwargs["auth"] == ("admin", "hunter2")

    def test_token_is_cached_until_expiry(self):
        session = _session(post_responses=[_response(json_data=TOKEN_JSON)])
        manager = JamfProTokenManager(session, "example.jamfcloud.com", CLIENT_CREDENTIALS)

        manager.get_token()
        manager.get_token()
        assert session.post.call_count == 1

    def test_token_is_reminted_when_close_to_expiry(self):
        # Jamf tokens live ~20 minutes; a long-running sync must re-mint instead of sending an
        # expired token and failing every request with a 401.
        session = _session(
            post_responses=[
                _response(json_data={**TOKEN_JSON, "access_token": "first"}),
                _response(json_data={**TOKEN_JSON, "access_token": "second"}),
            ]
        )
        manager = JamfProTokenManager(session, "example.jamfcloud.com", CLIENT_CREDENTIALS)
        manager.get_token()
        manager._deadline = 0.0  # simulate the token reaching its expiry margin

        assert manager.get_token() == "second"
        assert session.post.call_count == 2

    @pytest.mark.parametrize(
        "credentials",
        [
            JamfProCredentials(method="client_credentials", client_id="cid", client_secret=None),
            JamfProCredentials(method="basic", username=None, password="pw"),
        ],
    )
    def test_missing_credential_fields_raise_configuration_error(self, credentials):
        manager = JamfProTokenManager(_session(), "example.jamfcloud.com", credentials)
        with pytest.raises(JamfProConfigurationError):
            manager.get_token()

    def test_redirect_on_token_endpoint_is_rejected(self):
        # The host is customer-controlled; following a redirect could leak credentials to an
        # arbitrary Location (SSRF).
        session = _session(post_responses=[_response(status_code=302)])
        manager = JamfProTokenManager(session, "example.jamfcloud.com", CLIENT_CREDENTIALS)
        with pytest.raises(JamfProHostNotAllowedError):
            manager.get_token()

    def test_401_raises_http_error(self):
        session = _session(post_responses=[_response(status_code=401)])
        manager = JamfProTokenManager(session, "example.jamfcloud.com", CLIENT_CREDENTIALS)
        with pytest.raises(requests.HTTPError):
            manager.get_token()

    def test_slow_token_response_is_rejected(self):
        # A host dribbling the token body under the read timeout must not hold a worker open past the
        # wall-clock budget. A negative budget forces the deadline into the past on the first chunk.
        token_resp = _response(json_data=TOKEN_JSON)
        session = _session(post_responses=[token_resp])
        manager = JamfProTokenManager(session, "example.jamfcloud.com", CLIENT_CREDENTIALS)
        with mock.patch.object(jamf_pro_module, "MAX_DOWNLOAD_SECONDS", -1):
            with pytest.raises(JamfProResponseTooSlowError):
                manager.get_token()
        token_resp.close.assert_called()


class TestValidateCredentials:
    def _patch_session(self, session: mock.MagicMock):
        return mock.patch.object(jamf_pro_module, "make_tracked_session", return_value=session)

    def test_successful_token_mint_is_enough_at_source_create(self):
        session = _session(post_responses=[_response(json_data=TOKEN_JSON)])
        with self._patch_session(session) as factory:
            assert validate_credentials("example.jamfcloud.com", CLIENT_CREDENTIALS) == (True, None)
        # Privileges are per-resource in Jamf, so create-time must not probe endpoints.
        session.get.assert_not_called()
        # The mint response body carries the bearer token; it must stay out of sample capture.
        assert factory.call_args.kwargs == {"capture": False}

    def test_invalid_credentials(self):
        session = _session(post_responses=[_response(status_code=401)])
        with self._patch_session(session):
            valid, msg = validate_credentials("example.jamfcloud.com", CLIENT_CREDENTIALS)
        assert valid is False
        assert msg == "Invalid Jamf Pro credentials"

    def test_incomplete_credentials_return_friendly_error(self):
        with self._patch_session(_session()):
            valid, msg = validate_credentials("example.jamfcloud.com", JamfProCredentials(method="client_credentials"))
        assert valid is False
        assert "incomplete" in (msg or "")

    @pytest.mark.parametrize("bad_host", ["", "not a host!", "https://"])
    def test_invalid_host_short_circuits(self, bad_host):
        valid, msg = validate_credentials(bad_host, CLIENT_CREDENTIALS)
        assert valid is False
        assert msg == "Invalid Jamf Pro URL"

    def test_blocks_unsafe_host(self):
        session = _session()
        with (
            mock.patch.object(jamf_pro_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(session),
        ):
            valid, msg = validate_credentials("10.0.0.1", CLIENT_CREDENTIALS, team_id=99)
        assert valid is False
        assert msg == "internal address"
        session.post.assert_not_called()

    def test_scoped_probe_403_fails(self):
        session = _session(post_responses=[_response(json_data=TOKEN_JSON)], get_responses=[_response(status_code=403)])
        with self._patch_session(session):
            valid, msg = validate_credentials("example.jamfcloud.com", CLIENT_CREDENTIALS, schema_name="computers")
        assert valid is False
        assert "computers" in (msg or "")

    def test_scoped_probe_200_succeeds(self):
        session = _session(
            post_responses=[_response(json_data=TOKEN_JSON)],
            get_responses=[_response(json_data={"totalCount": 1, "results": [{"id": "1"}]})],
        )
        with self._patch_session(session):
            assert validate_credentials("example.jamfcloud.com", CLIENT_CREDENTIALS, schema_name="computers") == (
                True,
                None,
            )

    @pytest.mark.parametrize(
        "schema_name, expected_path, expected_query",
        [
            ("patch_reports", "/api/v3/patch-software-title-configurations", ""),
            ("patch_summaries", "/api/v3/patch-software-title-configurations", ""),
            (
                "mdm_commands",
                "/api/v2/mdm/commands",
                "page=0&page-size=1&filter=dateSent%3E%3D%221970-01-01T00%3A00%3A00.000Z%22",
            ),
        ],
    )
    def test_scoped_probe_targets_an_addressable_url(self, schema_name, expected_path, expected_query):
        session = _session(post_responses=[_response(json_data=TOKEN_JSON)], get_responses=[_response(json_data=[])])
        with self._patch_session(session):
            assert validate_credentials("example.jamfcloud.com", CLIENT_CREDENTIALS, schema_name=schema_name) == (
                True,
                None,
            )
        url = session.get.call_args.args[0]
        path, _, query = url.removeprefix("https://example.jamfcloud.com").partition("?")
        assert path == expected_path
        assert query == expected_query

    def test_request_exception_returns_failure(self):
        session = mock.MagicMock()
        session.post.side_effect = requests.exceptions.ConnectionError("boom")
        with self._patch_session(session):
            valid, msg = validate_credentials("example.jamfcloud.com", CLIENT_CREDENTIALS)
        assert valid is False
        assert "boom" in (msg or "")


class TestGetRows:
    def _run(
        self,
        manager: mock.MagicMock,
        get_responses: list[Any],
        endpoint: str = "computers",
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[Any], mock.MagicMock]:
        session = _session(post_responses=[_response(json_data=TOKEN_JSON)], get_responses=get_responses)
        with mock.patch.object(jamf_pro_module, "make_tracked_session", return_value=session):
            rows: list[Any] = []
            for batch in get_rows(
                host="example.jamfcloud.com",
                credentials=CLIENT_CREDENTIALS,
                endpoint=endpoint,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                team_id=1,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            ):
                rows.extend(batch)
        return rows, session

    def _manager(self, resume: Optional[JamfProResumeConfig] = None) -> mock.MagicMock:
        manager = mock.MagicMock()
        manager.can_resume.return_value = resume is not None
        manager.load_state.return_value = resume
        return manager

    def test_paginates_until_total_count_reached(self):
        manager = self._manager()
        page1 = _response(json_data={"totalCount": 150, "results": [{"id": str(i)} for i in range(100)]})
        page2 = _response(json_data={"totalCount": 150, "results": [{"id": str(i)} for i in range(100, 150)]})
        rows, session = self._run(manager, [page1, page2])

        assert len(rows) == 150
        assert session.get.call_count == 2
        assert "page=0" in session.get.call_args_list[0].args[0]
        assert "page=1" in session.get.call_args_list[1].args[0]
        # State is saved once, AFTER yielding page 0 and only because more pages remain.
        manager.save_state.assert_called_once_with(JamfProResumeConfig(page=1))

    def test_stops_on_empty_results_without_total_count(self):
        manager = self._manager()
        page1 = _response(json_data={"results": [{"id": "1"}]})
        empty = _response(json_data={"results": []})
        rows, session = self._run(manager, [page1, empty])

        assert [r["id"] for r in rows] == ["1"]
        assert session.get.call_count == 2

    def test_resumes_from_saved_page(self):
        manager = self._manager(resume=JamfProResumeConfig(page=3))
        page = _response(json_data={"totalCount": 301, "results": [{"id": "301"}]})
        _rows, session = self._run(manager, [page])

        assert "page=3" in session.get.call_args_list[0].args[0]

    def test_computers_rows_expose_top_level_report_date(self):
        # The pipeline reads the incremental watermark from a top-level column, so the nested
        # general.reportDate must be hoisted onto every row.
        manager = self._manager()
        page = _response(
            json_data={
                "totalCount": 1,
                "results": [{"id": "1", "general": {"reportDate": "2024-06-01T00:00:00.000Z"}}],
            }
        )
        rows, _session_ = self._run(manager, [page])

        assert rows[0]["report_date"] == "2024-06-01T00:00:00.000Z"
        assert rows[0]["general"]["reportDate"] == "2024-06-01T00:00:00.000Z"

    def test_computers_rows_missing_general_get_null_report_date(self):
        manager = self._manager()
        page = _response(json_data={"totalCount": 1, "results": [{"id": "1"}]})
        rows, _session_ = self._run(manager, [page])

        assert rows[0]["report_date"] is None

    def test_incremental_run_sends_rsql_filter(self):
        manager = self._manager()
        page = _response(json_data={"totalCount": 1, "results": [{"id": "1", "general": {}}]})
        _rows, session = self._run(
            manager,
            [page],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )

        url = session.get.call_args_list[0].args[0]
        assert "filter=general.reportDate%3E%3D%222024-01-01T00%3A00%3A00.000Z%22" in url

    def test_unpaginated_endpoint_yields_array_response(self):
        manager = self._manager()
        page = _response(json_data=[{"id": "1", "name": "HQ"}])
        rows, session = self._run(manager, [page], endpoint="sites")

        assert rows == [{"id": "1", "name": "HQ"}]
        assert session.get.call_count == 1
        manager.save_state.assert_not_called()

    def test_fan_out_walks_each_parent_and_tags_child_rows(self):
        manager = self._manager()
        parents = _response(json_data=[{"id": "10"}, {"id": "2"}, {"id": "7"}])
        parent_2_page_0 = _response(json_data={"totalCount": 201, "results": [{"deviceId": "a"}] * 200})
        parent_2_page_1 = _response(json_data={"totalCount": 201, "results": [{"deviceId": "b"}]})
        parent_7_missing = _response(status_code=404)
        parent_10_page_0 = _response(json_data={"totalCount": 1, "results": [{"deviceId": "c"}]})
        rows, session = self._run(
            manager,
            [parents, parent_2_page_0, parent_2_page_1, parent_7_missing, parent_10_page_0],
            endpoint="patch_reports",
        )

        urls = [call.args[0] for call in session.get.call_args_list]
        assert urls[0] == "https://example.jamfcloud.com/api/v3/patch-software-title-configurations"
        assert [url.split("?")[0].rsplit("/", 2)[1] for url in urls[1:]] == ["2", "2", "7", "10"]
        assert "page=1" in urls[2]
        assert len(rows) == 202
        assert {row["softwareTitleConfigurationId"] for row in rows} == {"2", "10"}
        assert rows[-1] == {"deviceId": "c", "softwareTitleConfigurationId": "10"}
        assert manager.save_state.call_args_list == [
            mock.call(JamfProResumeConfig(page=1, parent_id="2")),
            mock.call(JamfProResumeConfig(page=0, parent_id="7")),
            mock.call(JamfProResumeConfig(page=0, parent_id="10")),
        ]

    def test_fan_out_has_one_request_budget_across_all_parents(self):
        manager = self._manager()
        parents = _response(json_data=[{"id": str(parent_id)} for parent_id in range(4)])
        child_page = _response(json_data={"totalCount": 1, "results": [{"deviceId": "a"}]})
        session = _session(
            post_responses=[_response(json_data=TOKEN_JSON)],
            get_responses=[parents, child_page, child_page, child_page],
        )
        with (
            mock.patch.object(jamf_pro_module, "make_tracked_session", return_value=session),
            mock.patch.object(jamf_pro_module, "MAX_PAGES", 3),
        ):
            with pytest.raises(JamfProPaginationLimitError):
                list(
                    get_rows(
                        host="example.jamfcloud.com",
                        credentials=CLIENT_CREDENTIALS,
                        endpoint="patch_reports",
                        logger=mock.MagicMock(),
                        resumable_source_manager=manager,
                        team_id=1,
                    )
                )

        # The parent-list request is outside the child-page budget; only three children are fetched.
        assert session.get.call_count == 4

    def test_fan_out_resumes_from_saved_parent_and_page(self):
        manager = self._manager(resume=JamfProResumeConfig(page=3, parent_id="7"))
        parents = _response(json_data=[{"id": "2"}, {"id": "7"}, {"id": "10"}])
        parent_7 = _response(json_data={"totalCount": 601, "results": [{"deviceId": "a"}]})
        parent_10 = _response(json_data={"totalCount": 1, "results": [{"deviceId": "b"}]})
        _rows, session = self._run(manager, [parents, parent_7, parent_10], endpoint="patch_reports")

        urls = [call.args[0] for call in session.get.call_args_list]
        assert "/7/patch-report?" in urls[1]
        assert "page=3" in urls[1]
        assert "/10/patch-report?" in urls[2]
        assert "page=0" in urls[2]

    def test_fan_out_single_object_child_becomes_one_row(self):
        manager = self._manager()
        parents = _response(json_data=[{"id": "1"}])
        summary = _response(json_data={"softwareTitleId": "s1", "upToDate": 4, "outOfDate": 1})
        rows, _session_ = self._run(manager, [parents, summary], endpoint="patch_summaries")

        assert rows == [{"softwareTitleId": "s1", "upToDate": 4, "outOfDate": 1, "softwareTitleConfigurationId": "1"}]

    def test_fan_out_pages_through_a_paginated_parent(self):
        manager = self._manager()
        parents_page_0 = _response(json_data={"totalCount": 201, "results": [{"id": str(i)} for i in range(200)]})
        parents_page_1 = _response(json_data={"totalCount": 201, "results": [{"id": "200"}]})
        child = _response(json_data={"totalCount": 1, "results": [{"deviceId": "d1", "statusEnum": "COMPLETE"}]})
        rows, session = self._run(
            manager, [parents_page_0, parents_page_1] + [child] * 201, endpoint="patch_policy_logs"
        )

        urls = [call.args[0] for call in session.get.call_args_list]
        assert urls[0].startswith("https://example.jamfcloud.com/api/v2/patch-policies?")
        assert "page=1" in urls[1]
        assert "/patch-policies/200/logs?" in urls[-1]
        assert len(rows) == 201
        assert rows[-1] == {"deviceId": "d1", "statusEnum": "COMPLETE", "patchPolicyId": "200"}

    def test_fan_out_refuses_an_unbounded_parent_list(self):
        manager = self._manager()
        endless_parents = _response(json_data={"totalCount": 10**9, "results": [{"id": "1"}, {"id": "2"}]})
        session = _session(post_responses=[_response(json_data=TOKEN_JSON)], get_responses=[endless_parents] * 3)
        with (
            mock.patch.object(jamf_pro_module, "make_tracked_session", return_value=session),
            mock.patch.object(jamf_pro_module, "MAX_PARENT_IDS", 3),
        ):
            with pytest.raises(JamfProPaginationLimitError):
                list(
                    get_rows(
                        host="example.jamfcloud.com",
                        credentials=CLIENT_CREDENTIALS,
                        endpoint="patch_policy_logs",
                        logger=mock.MagicMock(),
                        resumable_source_manager=manager,
                        team_id=1,
                    )
                )

        assert all("/logs" not in call.args[0] for call in session.get.call_args_list)

    @pytest.mark.parametrize(
        "endpoint, expected_parent_ids",
        [
            ("mobile_device_smart_group_memberships", ["1"]),
            ("mobile_device_static_group_memberships", ["2"]),
        ],
    )
    def test_mobile_group_membership_fans_out_by_group_type_and_keeps_only_device_ids(
        self, endpoint, expected_parent_ids
    ):
        manager = self._manager()
        groups = _response(json_data=[{"id": 1, "isSmartGroup": True}, {"id": 2, "isSmartGroup": False}])
        members = _response(
            json_data={
                "totalCount": 1,
                "results": [{"mobileDeviceId": "5", "displayName": "iPad", "airPlayPassword": "pw"}],
            }
        )
        rows, session = self._run(manager, [groups, members], endpoint=endpoint)

        urls = [call.args[0] for call in session.get.call_args_list]
        assert [url.split("?")[0].rsplit("/", 1)[1] for url in urls[1:]] == expected_parent_ids
        assert rows == [{"mobileDeviceId": "5", "mobileDeviceGroupId": expected_parent_ids[0]}]

    def test_unpaginated_incremental_endpoint_sends_filter(self):
        manager = self._manager()
        page = _response(json_data={"totalCount": 1, "results": [{"osUpdatesStatusId": "1"}]})
        rows, session = self._run(
            manager,
            [page],
            endpoint="managed_software_update_statuses",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )

        assert rows == [{"osUpdatesStatusId": "1"}]
        assert session.get.call_args.args[0] == (
            "https://example.jamfcloud.com/api/v1/managed-software-updates/update-statuses"
            "?filter=updated%3E%3D%222024-01-01T00%3A00%3A00.000Z%22"
        )

    def test_blocks_unsafe_host_before_any_request(self):
        manager = self._manager()
        with mock.patch.object(jamf_pro_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(JamfProHostNotAllowedError):
                list(
                    get_rows(
                        host="10.0.0.1",
                        credentials=CLIENT_CREDENTIALS,
                        endpoint="computers",
                        logger=mock.MagicMock(),
                        resumable_source_manager=manager,
                        team_id=1,
                    )
                )

    def test_rejects_redirect_response(self):
        manager = self._manager()
        with pytest.raises(JamfProHostNotAllowedError):
            self._run(manager, [_response(status_code=302)])

    @pytest.mark.parametrize(
        "endpoint, data_capture",
        [
            ("computers", True),
            # scriptContents routinely embeds deployment credentials, so the scripts data
            # session must stay out of sample capture too.
            ("scripts", False),
        ],
    )
    def test_token_mint_session_is_excluded_from_sample_capture(self, endpoint, data_capture):
        # The mint response body carries the bearer token, which the name-based sample
        # scrubbers can't recognise — re-enabling capture there would persist a live credential.
        manager = self._manager()
        page = _response(json_data={"totalCount": 1, "results": [{"id": "1"}]})
        session = _session(post_responses=[_response(json_data=TOKEN_JSON)], get_responses=[page])
        with mock.patch.object(jamf_pro_module, "make_tracked_session", return_value=session) as factory:
            list(
                get_rows(
                    host="example.jamfcloud.com",
                    credentials=CLIENT_CREDENTIALS,
                    endpoint=endpoint,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    team_id=1,
                )
            )
        assert factory.call_args_list == [mock.call(capture=False), mock.call(capture=data_capture)]

    def test_requests_do_not_follow_redirects(self):
        manager = self._manager()
        page = _response(json_data={"totalCount": 1, "results": [{"id": "1", "general": {}}]})
        _rows, session = self._run(manager, [page])

        assert session.get.call_args.kwargs["allow_redirects"] is False
        assert session.post.call_args.kwargs["allow_redirects"] is False

    def test_oversized_page_body_is_rejected(self):
        # The instance URL is customer-controlled; a hostile server returning a body larger than the
        # cap must fail the sync rather than buffer it whole into a shared worker's memory.
        manager = self._manager()
        big_page = _response(json_data={"results": [{"id": "1"}]})
        big_page.iter_content.side_effect = lambda *a, **k: iter([b"x" * 2048])
        session = _session(post_responses=[_response(json_data=TOKEN_JSON)], get_responses=[big_page])
        with (
            mock.patch.object(jamf_pro_module, "make_tracked_session", return_value=session),
            mock.patch.object(jamf_pro_module, "MAX_RESPONSE_BYTES", 1024),
        ):
            with pytest.raises(JamfProResponseTooLargeError):
                list(
                    get_rows(
                        host="example.jamfcloud.com",
                        credentials=CLIENT_CREDENTIALS,
                        endpoint="computers",
                        logger=mock.MagicMock(),
                        resumable_source_manager=manager,
                        team_id=1,
                    )
                )

    def test_slow_page_body_is_rejected(self):
        # The token mints within budget; the page body then dribbles past the wall-clock budget and
        # must be aborted. The read timeout only bounds each socket read, not total transfer time.
        manager = self._manager()
        clock = {"t": 0.0}
        token_resp = _response(json_data=TOKEN_JSON)
        page_resp = _response(json_data={"results": [{"id": "1"}]})

        def slow_page_chunks(*args, **kwargs):
            clock["t"] += jamf_pro_module.MAX_DOWNLOAD_SECONDS + 1  # jump past the budget mid-download
            yield b'{"results": []}'

        page_resp.iter_content.side_effect = slow_page_chunks
        session = _session(post_responses=[token_resp], get_responses=[page_resp])
        with (
            mock.patch.object(jamf_pro_module.time, "monotonic", lambda: clock["t"]),
            mock.patch.object(jamf_pro_module, "make_tracked_session", return_value=session),
        ):
            with pytest.raises(JamfProResponseTooSlowError):
                list(
                    get_rows(
                        host="example.jamfcloud.com",
                        credentials=CLIENT_CREDENTIALS,
                        endpoint="computers",
                        logger=mock.MagicMock(),
                        resumable_source_manager=manager,
                        team_id=1,
                    )
                )
        page_resp.close.assert_called()

    def test_pagination_stops_when_server_never_terminates(self):
        # A server returning a non-empty page forever with no totalCount would otherwise loop until
        # the activity's week-long timeout; the hard page cap breaks that.
        manager = self._manager()
        session = _session(post_responses=[_response(json_data=TOKEN_JSON)])
        session.get.return_value = _response(json_data={"results": [{"id": "1"}]})
        with (
            mock.patch.object(jamf_pro_module, "make_tracked_session", return_value=session),
            mock.patch.object(jamf_pro_module, "MAX_PAGES", 3),
        ):
            with pytest.raises(JamfProPaginationLimitError):
                list(
                    get_rows(
                        host="example.jamfcloud.com",
                        credentials=CLIENT_CREDENTIALS,
                        endpoint="computers",
                        logger=mock.MagicMock(),
                        resumable_source_manager=manager,
                        team_id=1,
                    )
                )
        # Pages 0, 1, 2 fetched; the loop raises before fetching page 3.
        assert session.get.call_count == 3


class TestJamfProSourceResponse:
    @pytest.mark.parametrize("endpoint", list(JAMF_PRO_ENDPOINTS.keys()))
    def test_response_shape(self, endpoint):
        response = jamf_pro_source(
            host="example.jamfcloud.com",
            credentials=CLIENT_CREDENTIALS,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(),
            team_id=1,
        )
        assert response.name == endpoint
        assert response.sort_mode == "asc"
