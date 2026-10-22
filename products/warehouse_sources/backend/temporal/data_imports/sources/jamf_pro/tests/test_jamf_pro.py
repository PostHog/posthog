import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jamfpro import (
    JamfProAuthMethodConfig,
    JamfProSourceConfig,
)
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
    _format_incremental_value,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.settings import JAMF_PRO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.jamf_pro.source import JamfProSource

CLIENT_CREDENTIALS = JamfProCredentials(method="client_credentials", client_id="cid", client_secret="secret")
BASIC_CREDENTIALS = JamfProCredentials(method="basic", username="admin", password="hunter2")

TOKEN_JSON = {"access_token": "tok", "expires_in": 1199, "token_type": "Bearer"}


def _driver(host: str = "example.jamfcloud.com") -> SourceDriver:
    return SourceDriver(
        JamfProSource(),
        JamfProSourceConfig(
            instance_url=host,
            auth_method=JamfProAuthMethodConfig(
                selection="client_credentials", client_id="cid", client_secret="secret"
            ),
        ),
    )


def _script(*responses: ScriptedResponse) -> list[ScriptedResponse]:
    return [ScriptedResponse(json=TOKEN_JSON), *responses]


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


class TestTokenManager:
    def test_basic_mints_token_with_http_basic(self):
        session = _session(post_responses=[_response(json_data={"token": "tok2", "expires": "2100-01-01T00:00:00Z"})])
        manager = JamfProTokenManager(session, "example.jamfcloud.com", BASIC_CREDENTIALS)

        assert manager.get_token() == "tok2"
        url = session.post.call_args.args[0]
        assert url == "https://example.jamfcloud.com/api/v1/auth/token"
        assert session.post.call_args.kwargs["auth"] == ("admin", "hunter2")

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
    def test_successful_token_mint_is_enough_at_source_create(self):
        with scripted_network([ScriptedResponse(json=TOKEN_JSON)]) as network:
            assert validate_credentials("example.jamfcloud.com", CLIENT_CREDENTIALS) == (True, None)
        # Privileges are per-resource in Jamf, so create-time must not probe endpoints.
        assert [request.method for request in network.requests_log] == ["POST"]
        # The mint response body carries the bearer token; it must stay out of sample capture.
        assert network.session_options == [{"capture": False}]

    def test_invalid_credentials(self):
        with scripted_network([ScriptedResponse(status=401)]) as network:
            valid, msg = validate_credentials("example.jamfcloud.com", CLIENT_CREDENTIALS)
        assert valid is False
        assert msg == "Invalid Jamf Pro credentials"
        assert network.requests_log[0].path == "/api/oauth/token"

    def test_incomplete_credentials_return_friendly_error(self):
        with scripted_network([]) as network:
            valid, msg = validate_credentials("example.jamfcloud.com", JamfProCredentials(method="client_credentials"))
        assert valid is False
        assert "incomplete" in (msg or "")
        assert network.requests_log == []

    @pytest.mark.parametrize("bad_host", ["", "not a host!", "https://"])
    def test_invalid_host_short_circuits(self, bad_host):
        valid, msg = validate_credentials(bad_host, CLIENT_CREDENTIALS)
        assert valid is False
        assert msg == "Invalid Jamf Pro URL"

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(jamf_pro_module, "_is_host_safe", return_value=(False, "internal address")),
            scripted_network([]) as network,
        ):
            valid, msg = validate_credentials("10.0.0.1", CLIENT_CREDENTIALS, team_id=99)
        assert valid is False
        assert msg == "internal address"
        assert network.requests_log == []

    def test_scoped_probe_403_fails(self):
        with scripted_network(_script(ScriptedResponse(status=403))) as network:
            valid, msg = validate_credentials("example.jamfcloud.com", CLIENT_CREDENTIALS, schema_name="computers")
        assert valid is False
        assert "computers" in (msg or "")
        assert network.requests_log[1].path == "/api/v1/computers-inventory"

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
        with scripted_network(_script(ScriptedResponse(json=[]))) as network:
            assert validate_credentials("example.jamfcloud.com", CLIENT_CREDENTIALS, schema_name=schema_name) == (
                True,
                None,
            )
        url = network.requests_log[1].url
        path, _, query = url.removeprefix("https://example.jamfcloud.com").partition("?")
        assert path == expected_path
        assert query == expected_query

    def test_request_exception_returns_failure(self):
        with scripted_network([requests.exceptions.ConnectionError("boom")]) as network:
            valid, msg = validate_credentials("example.jamfcloud.com", CLIENT_CREDENTIALS)
        assert valid is False
        assert "boom" in (msg or "")
        assert network.requests_log[0].path == "/api/oauth/token"


class TestGetRows:
    def _drive(
        self,
        get_responses: list[ScriptedResponse],
        endpoint: str = "computers",
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
        resume_state: JamfProResumeConfig | None = None,
    ) -> DriveResult:
        return _driver().run(
            endpoint,
            _script(*get_responses),
            resume_state=resume_state,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

    def _manager(self, resume: Optional[JamfProResumeConfig] = None) -> mock.MagicMock:
        manager = mock.MagicMock()
        manager.can_resume.return_value = resume is not None
        manager.load_state.return_value = resume
        return manager

    def test_stops_on_empty_results_without_total_count(self):
        result = self._drive(
            [
                ScriptedResponse(json={"results": [{"id": "1"}]}),
                ScriptedResponse(json={"results": []}),
            ]
        )

        assert [row["id"] for row in result.rows] == ["1"]
        assert result.params("page") == [None, "0", "1"]
        assert result.raised is None

    def test_resumes_from_saved_page(self):
        result = self._drive(
            [ScriptedResponse(json={"totalCount": 301, "results": [{"id": "301"}]})],
            resume_state=JamfProResumeConfig(page=3),
        )

        assert result.params("page") == [None, "3"]
        assert result.raised is None

    def test_unpaginated_endpoint_yields_array_response(self):
        result = self._drive([ScriptedResponse(json=[{"id": "1", "name": "HQ"}])], endpoint="sites")

        assert result.rows == [{"id": "1", "name": "HQ"}]
        assert len(result.requests) == 2
        assert result.saved_states == []
        assert result.raised is None

    def test_fan_out_walks_each_parent_and_tags_child_rows(self):
        parents = ScriptedResponse(json=[{"id": "10"}, {"id": "2"}, {"id": "7"}])
        parent_2_page_0 = ScriptedResponse(json={"totalCount": 201, "results": [{"deviceId": "a"}] * 200})
        parent_2_page_1 = ScriptedResponse(json={"totalCount": 201, "results": [{"deviceId": "b"}]})
        parent_7_missing = ScriptedResponse(status=404)
        parent_10_page_0 = ScriptedResponse(json={"totalCount": 1, "results": [{"deviceId": "c"}]})
        result = self._drive(
            [parents, parent_2_page_0, parent_2_page_1, parent_7_missing, parent_10_page_0],
            endpoint="patch_reports",
        )

        urls = result.urls[1:]
        assert urls[0] == "https://example.jamfcloud.com/api/v3/patch-software-title-configurations"
        assert [url.split("?")[0].rsplit("/", 2)[1] for url in urls[1:]] == ["2", "2", "7", "10"]
        assert "page=1" in urls[2]
        assert len(result.rows) == 202
        assert {row["softwareTitleConfigurationId"] for row in result.rows} == {"2", "10"}
        assert result.rows[-1] == {"deviceId": "c", "softwareTitleConfigurationId": "10"}
        assert result.saved_states == [
            JamfProResumeConfig(page=1, parent_id="2"),
            JamfProResumeConfig(page=0, parent_id="7"),
            JamfProResumeConfig(page=0, parent_id="10"),
        ]
        assert result.raised is None

    def test_fan_out_has_one_request_budget_across_all_parents(self):
        parents = ScriptedResponse(json=[{"id": str(parent_id)} for parent_id in range(4)])
        child_page = ScriptedResponse(json={"totalCount": 1, "results": [{"deviceId": "a"}]})
        with mock.patch.object(jamf_pro_module, "MAX_PAGES", 3):
            result = self._drive([parents, child_page, child_page, child_page], endpoint="patch_reports")

        # The parent-list request is outside the child-page budget; only three children are fetched.
        assert len(result.requests) == 5
        assert isinstance(result.raised, JamfProPaginationLimitError)

    def test_fan_out_resumes_from_saved_parent_and_page(self):
        parents = ScriptedResponse(json=[{"id": "2"}, {"id": "7"}, {"id": "10"}])
        parent_7 = ScriptedResponse(json={"totalCount": 601, "results": [{"deviceId": "a"}]})
        parent_10 = ScriptedResponse(json={"totalCount": 1, "results": [{"deviceId": "b"}]})
        result = self._drive(
            [parents, parent_7, parent_10],
            endpoint="patch_reports",
            resume_state=JamfProResumeConfig(page=3, parent_id="7"),
        )

        urls = result.urls[1:]
        assert "/7/patch-report?" in urls[1]
        assert "page=3" in urls[1]
        assert "/10/patch-report?" in urls[2]
        assert "page=0" in urls[2]
        assert result.raised is None

    def test_fan_out_single_object_child_becomes_one_row(self):
        parents = ScriptedResponse(json=[{"id": "1"}])
        summary = ScriptedResponse(json={"softwareTitleId": "s1", "upToDate": 4, "outOfDate": 1})
        result = self._drive([parents, summary], endpoint="patch_summaries")

        assert result.rows == [
            {"softwareTitleId": "s1", "upToDate": 4, "outOfDate": 1, "softwareTitleConfigurationId": "1"}
        ]
        assert result.raised is None

    def test_fan_out_pages_through_a_paginated_parent(self):
        parents_page_0 = ScriptedResponse(json={"totalCount": 201, "results": [{"id": str(i)} for i in range(200)]})
        parents_page_1 = ScriptedResponse(json={"totalCount": 201, "results": [{"id": "200"}]})
        child = ScriptedResponse(json={"totalCount": 1, "results": [{"deviceId": "d1", "statusEnum": "COMPLETE"}]})
        result = self._drive([parents_page_0, parents_page_1] + [child] * 201, endpoint="patch_policy_logs")

        urls = result.urls[1:]
        assert urls[0].startswith("https://example.jamfcloud.com/api/v2/patch-policies?")
        assert "page=1" in urls[1]
        assert "/patch-policies/200/logs?" in urls[-1]
        assert len(result.rows) == 201
        assert result.rows[-1] == {"deviceId": "d1", "statusEnum": "COMPLETE", "patchPolicyId": "200"}
        assert result.raised is None

    def test_fan_out_refuses_an_unbounded_parent_list(self):
        endless_parents = ScriptedResponse(json={"totalCount": 10**9, "results": [{"id": "1"}, {"id": "2"}]})
        with mock.patch.object(jamf_pro_module, "MAX_PARENT_IDS", 3):
            result = self._drive([endless_parents] * 3, endpoint="patch_policy_logs")

        assert isinstance(result.raised, JamfProPaginationLimitError)
        assert all("/logs" not in path for path in result.paths)

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
        groups = ScriptedResponse(json=[{"id": 1, "isSmartGroup": True}, {"id": 2, "isSmartGroup": False}])
        members = ScriptedResponse(
            json={
                "totalCount": 1,
                "results": [{"mobileDeviceId": "5", "displayName": "iPad", "airPlayPassword": "pw"}],
            }
        )
        result = self._drive([groups, members], endpoint=endpoint)

        urls = result.urls[1:]
        assert [url.split("?")[0].rsplit("/", 1)[1] for url in urls[1:]] == expected_parent_ids
        assert result.rows == [{"mobileDeviceId": "5", "mobileDeviceGroupId": expected_parent_ids[0]}]
        assert result.raised is None

    def test_unpaginated_incremental_endpoint_sends_filter(self):
        page = ScriptedResponse(json={"totalCount": 1, "results": [{"osUpdatesStatusId": "1"}]})
        result = self._drive(
            [page],
            endpoint="managed_software_update_statuses",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )

        assert result.rows == [{"osUpdatesStatusId": "1"}]
        assert result.urls[1] == (
            "https://example.jamfcloud.com/api/v1/managed-software-updates/update-statuses"
            "?filter=updated%3E%3D%222024-01-01T00%3A00%3A00.000Z%22"
        )
        assert result.raised is None

    def test_blocks_unsafe_host_before_any_request(self):
        with mock.patch.object(jamf_pro_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver("10.0.0.1").run("computers", [])

        assert isinstance(result.raised, JamfProHostNotAllowedError)
        assert result.requests == []

    def test_rejects_redirect_response(self):
        result = self._drive([ScriptedResponse(status=302, headers={"Location": "https://other.example/path"})])

        assert isinstance(result.raised, JamfProHostNotAllowedError)
        assert result.paths == ["/api/oauth/token", "/api/v1/computers-inventory"]

    def test_requests_do_not_follow_redirects(self):
        redirect = ScriptedResponse(status=302, headers={"Location": "https://other.example/path"})
        token_redirect = _driver().run("computers", [redirect])
        page_redirect = self._drive([redirect])

        assert isinstance(token_redirect.raised, JamfProHostNotAllowedError)
        assert token_redirect.paths == ["/api/oauth/token"]
        assert isinstance(page_redirect.raised, JamfProHostNotAllowedError)
        assert page_redirect.paths == ["/api/oauth/token", "/api/v1/computers-inventory"]

    def test_oversized_page_body_is_rejected(self):
        # The instance URL is customer-controlled; a hostile server returning a body larger than the
        # cap must fail the sync rather than buffer it whole into a shared worker's memory.
        with mock.patch.object(jamf_pro_module, "MAX_RESPONSE_BYTES", 1024):
            result = self._drive([ScriptedResponse(body=b"x" * 2048)])

        assert isinstance(result.raised, JamfProResponseTooLargeError)
        assert result.paths == ["/api/oauth/token", "/api/v1/computers-inventory"]

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
        endless_page = ScriptedResponse(json={"results": [{"id": "1"}]})
        with mock.patch.object(jamf_pro_module, "MAX_PAGES", 3):
            result = self._drive([endless_page] * 3)

        # Pages 0, 1, 2 fetched; the loop raises before fetching page 3.
        assert result.params("page") == [None, "0", "1", "2"]
        assert isinstance(result.raised, JamfProPaginationLimitError)


class TestJamfProSourceResponse:
    @pytest.mark.parametrize("endpoint", list(JAMF_PRO_ENDPOINTS.keys()))
    def test_response_shape(self, endpoint):
        config = JAMF_PRO_ENDPOINTS[endpoint]
        fetched_config = JAMF_PRO_ENDPOINTS[config.parent] if config.parent else config
        payload = {"results": []} if fetched_config.paginated else []
        result = _driver().run(endpoint, _script(ScriptedResponse(json=payload)))

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.sort_mode == "asc"
