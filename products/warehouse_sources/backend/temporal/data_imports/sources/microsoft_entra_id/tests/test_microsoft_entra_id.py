import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    BearerTokenAuth,
    OAuth2Auth,
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_entra_id.microsoft_entra_id import (
    GRAPH_DEFAULT_SCOPE,
    MicrosoftEntraIdResumeConfig,
    ODataNextLinkPaginator,
    build_graph_auth,
    check_endpoint_permissions,
    graph_base_url,
    microsoft_entra_id_source,
    odata_datetime,
    odata_ge_filter,
    token_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_entra_id.settings import (
    ENTRA_ENDPOINTS,
    USER_SELECT,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_entra_id.microsoft_entra_id"
AUTH_PATCH = f"{MODULE}.build_graph_auth"
SESSION_PATCH = f"{MODULE}.make_tracked_session"
PRIME_PATCH = f"{MODULE}.prime_access_token"

GRAPH = "https://graph.microsoft.com/v1.0"


def _page(rows: list[dict[str, Any]] | None, next_link: str | None = None, *, status: int = 200) -> Response:
    body: dict[str, Any] = {}
    if rows is not None:
        body["value"] = rows
    if next_link:
        body["@odata.nextLink"] = next_link
    response = Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    return response


def _make_manager(resume_state: MicrosoftEntraIdResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Mock a session, capturing per-request params and URLs at send time.

    ``request.params`` is one dict mutated in place across pages, so it has to be snapshotted when
    each request is prepared rather than inspected afterwards.
    """
    session.headers = {}
    params: list[dict[str, Any]] = []
    urls: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        params.append(dict(request.params or {}))
        urls.append(request.url)
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return params, urls


def _rows(response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast("Iterable[Any]", response.items()) for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> SourceResponse:
    return microsoft_entra_id_source(
        tenant_id="contoso.onmicrosoft.com",
        client_id="client-id",
        client_secret="secret",
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestOdataDatetime:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2024, 3, 1, 9, 30, tzinfo=UTC), "2024-03-01T09:30:00Z"),
            ("naive_datetime", datetime(2024, 3, 1, 9, 30), "2024-03-01T09:30:00Z"),
            ("date", date(2024, 3, 1), "2024-03-01T00:00:00Z"),
            ("iso_z_string", "2024-03-01T09:30:00Z", "2024-03-01T09:30:00Z"),
            ("iso_offset_string", "2024-03-01T11:30:00+02:00", "2024-03-01T09:30:00Z"),
            ("none", None, None),
            ("garbage", "not-a-date", None),
        ]
    )
    def test_renders_utc_literal(self, _name: str, value: Any, expected: str | None) -> None:
        assert odata_datetime(value) == expected

    def test_filter_expression_uses_ge_on_the_cursor_field(self) -> None:
        convert = odata_ge_filter("activityDateTime")
        assert convert(datetime(2024, 3, 1, tzinfo=UTC)) == "activityDateTime ge 2024-03-01T00:00:00Z"

    def test_filter_expression_is_dropped_without_a_watermark(self) -> None:
        # Returning None keeps `$filter` out of the query string entirely on the first sync,
        # rather than sending a half-built expression.
        assert odata_ge_filter("activityDateTime")(None) is None


class TestUrlBuilders:
    @parameterized.expand(
        [
            ("guid", "00000000-0000-0000-0000-000000000000"),
            ("domain", "contoso.onmicrosoft.com"),
            ("organizations", "organizations"),
        ]
    )
    def test_token_url_accepts_valid_tenants(self, _name: str, tenant: str) -> None:
        assert token_url(tenant) == f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    @parameterized.expand(
        [
            ("path_escape", "tenant/../../evil"),
            ("slash", "tenant/evil"),
            ("absolute_url", "https://evil.example.com"),
            ("empty", ""),
            ("leading_dot", ".tenant"),
        ]
    )
    def test_token_url_rejects_tenants_that_escape_the_path_segment(self, _name: str, tenant: str) -> None:
        # The tenant id is interpolated into the token endpoint URL, so anything that could
        # retarget where the client secret is posted must be refused.
        with pytest.raises(ValueError):
            token_url(tenant)

    def test_graph_base_url(self) -> None:
        assert graph_base_url("v1.0") == GRAPH

    @parameterized.expand([("path_escape", "../beta"), ("slash", "v1.0/evil"), ("empty", "")])
    def test_graph_base_url_rejects_bad_versions(self, _name: str, version: str) -> None:
        with pytest.raises(ValueError):
            graph_base_url(version)

    def test_build_graph_auth_uses_client_credentials(self) -> None:
        auth = build_graph_auth("contoso.onmicrosoft.com", "client-id", "secret")
        assert isinstance(auth, OAuth2Auth)
        assert auth.grant_type == "client_credentials"
        assert auth.scopes == GRAPH_DEFAULT_SCOPE
        assert auth.token_url == "https://login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/token"
        # The secret and any minted token must be registered for log/error redaction.
        assert "secret" in auth.secret_values()


class TestPaginator:
    def test_follows_next_link(self) -> None:
        paginator = ODataNextLinkPaginator()
        paginator.update_state(_page([{"id": "1"}], next_link=f"{GRAPH}/users?$skiptoken=abc"))
        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"next_url": f"{GRAPH}/users?$skiptoken=abc"}

    @parameterized.expand([("absent", None), ("empty_string", "")])
    def test_stops_without_a_next_link(self, _name: str, next_link: str | None) -> None:
        paginator = ODataNextLinkPaginator()
        paginator.update_state(_page([{"id": "1"}], next_link=next_link))
        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None

    def test_stops_on_a_non_json_body(self) -> None:
        response = Response()
        response.status_code = 200
        response._content = b"<html>nope</html>"
        paginator = ODataNextLinkPaginator()
        paginator.update_state(response)
        assert paginator.has_next_page is False

    def test_resume_state_round_trip(self) -> None:
        paginator = ODataNextLinkPaginator()
        paginator.set_resume_state({"next_url": f"{GRAPH}/users?$skiptoken=abc"})
        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"next_url": f"{GRAPH}/users?$skiptoken=abc"}


@mock.patch(AUTH_PATCH, return_value=BearerTokenAuth("access-token"))
class TestRequestParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_users_requests_the_curated_projection(self, MockSession: mock.MagicMock, _auth: mock.MagicMock) -> None:
        params, urls = _wire(MockSession.return_value, [_page([{"id": "u1"}])])

        assert [r["id"] for r in _rows(_source("Users", _make_manager()))] == ["u1"]
        assert params[0]["$select"] == USER_SELECT
        assert params[0]["$top"] == 999
        assert urls[0] == f"{GRAPH}/users"

    @parameterized.expand(["DirectoryRoles", "Organization", "SubscribedSkus"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_small_collections_send_no_top(
        self, endpoint: str, MockSession: mock.MagicMock, _auth: mock.MagicMock
    ) -> None:
        # These endpoints document no paging support, so sending `$top` risks a 400 on an
        # unsupported query parameter.
        params, _urls = _wire(MockSession.return_value, [_page([{"id": "1"}])])

        _rows(_source(endpoint, _make_manager()))

        assert "$top" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_audit_logs_filter_on_the_watermark(self, MockSession: mock.MagicMock, _auth: mock.MagicMock) -> None:
        params, _urls = _wire(MockSession.return_value, [_page([{"id": "a1"}])])

        _rows(
            _source(
                "DirectoryAudits",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
            )
        )

        assert params[0]["$filter"] == "activityDateTime ge 2024-03-01T00:00:00Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_incremental_sync_sends_no_filter(self, MockSession: mock.MagicMock, _auth: mock.MagicMock) -> None:
        params, _urls = _wire(MockSession.return_value, [_page([{"id": "a1"}])])

        _rows(
            _source(
                "DirectoryAudits",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
            )
        )

        assert "$filter" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_sync_sends_no_filter(self, MockSession: mock.MagicMock, _auth: mock.MagicMock) -> None:
        params, _urls = _wire(MockSession.return_value, [_page([{"id": "a1"}])])

        _rows(
            _source(
                "DirectoryAudits",
                _make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
            )
        )

        assert "$filter" not in params[0]

    @parameterized.expand(["Users", "Groups", "Applications", "Devices"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_endpoints_without_a_server_filter_never_send_one(
        self, endpoint: str, MockSession: mock.MagicMock, _auth: mock.MagicMock
    ) -> None:
        # Graph exposes no `$filter ge` we can rely on for directory objects, so these stay full
        # refresh even when a watermark exists — sending one would silently drop rows.
        params, _urls = _wire(MockSession.return_value, [_page([{"id": "1"}])])

        _rows(
            _source(
                endpoint,
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
            )
        )

        assert "$filter" not in params[0]

    @parameterized.expand(
        [
            ("advertised_field_is_honoured", "createdDateTime", "createdDateTime ge 2024-03-01T00:00:00Z"),
            ("unknown_field_falls_back", "someOtherField", "createdDateTime ge 2024-03-01T00:00:00Z"),
            ("no_selection_falls_back", None, "createdDateTime ge 2024-03-01T00:00:00Z"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_field_selection(
        self,
        _name: str,
        requested: str | None,
        expected_filter: str,
        MockSession: mock.MagicMock,
        _auth: mock.MagicMock,
    ) -> None:
        params, _urls = _wire(MockSession.return_value, [_page([{"id": "s1"}])])

        _rows(
            _source(
                "SignIns",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
                incremental_field=requested,
            )
        )

        assert params[0]["$filter"] == expected_filter


@mock.patch(AUTH_PATCH, return_value=BearerTokenAuth("access-token"))
class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_next_link_and_checkpoints(self, MockSession: mock.MagicMock, _auth: mock.MagicMock) -> None:
        next_link = f"{GRAPH}/users?$skiptoken=abc"
        _params, urls = _wire(
            MockSession.return_value,
            [_page([{"id": "u1"}], next_link=next_link), _page([{"id": "u2"}])],
        )

        manager = _make_manager()
        rows = _rows(_source("Users", manager))

        assert [r["id"] for r in rows] == ["u1", "u2"]
        assert urls == [f"{GRAPH}/users", next_link]
        # One checkpoint after the first page; the final page has nothing left to resume to.
        manager.save_state.assert_called_once_with(MicrosoftEntraIdResumeConfig(next_url=next_link))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_the_saved_next_link(self, MockSession: mock.MagicMock, _auth: mock.MagicMock) -> None:
        next_link = f"{GRAPH}/users?$skiptoken=abc"
        params, urls = _wire(MockSession.return_value, [_page([{"id": "u2"}])])

        manager = _make_manager(MicrosoftEntraIdResumeConfig(next_url=next_link))
        rows = _rows(_source("Users", manager))

        assert [r["id"] for r in rows] == ["u2"]
        assert urls == [next_link]
        # The resumed link already carries every query parameter, so nothing is re-appended.
        assert params[0] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_collection_yields_nothing_and_stops(
        self, MockSession: mock.MagicMock, _auth: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_page([])])

        manager = _make_manager()

        assert _rows(_source("Users", manager)) == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_value_key_fails_loud(self, MockSession: mock.MagicMock, _auth: mock.MagicMock) -> None:
        # A Graph collection always wraps rows in `value`; a body without it means the response
        # shape changed, which must fail rather than silently sync zero rows.
        _wire(MockSession.return_value, [_page(None)])

        with pytest.raises(ValueError, match="data_selector"):
            _rows(_source("Users", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_next_link_off_graph_is_refused(self, MockSession: mock.MagicMock, _auth: mock.MagicMock) -> None:
        # Host pinning stops a tampered `@odata.nextLink` carrying the bearer token off-host.
        _wire(
            MockSession.return_value,
            [_page([{"id": "u1"}], next_link="https://evil.example.com/v1.0/users"), _page([{"id": "u2"}])],
        )

        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("Users", _make_manager()))


@mock.patch(AUTH_PATCH, return_value=BearerTokenAuth("access-token"))
class TestGroupMembersFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_groups(self, MockSession: mock.MagicMock, _auth: mock.MagicMock) -> None:
        _params, urls = _wire(
            MockSession.return_value,
            [
                _page([{"id": "g1"}, {"id": "g2"}]),
                _page([{"@odata.type": "#microsoft.graph.user", "id": "u1", "displayName": "Ada"}]),
                _page([{"@odata.type": "#microsoft.graph.group", "id": "g3", "displayName": "Nested"}]),
            ],
        )

        rows = _rows(_source("GroupMembers", _make_manager()))

        assert urls == [
            f"{GRAPH}/groups",
            f"{GRAPH}/groups/g1/members",
            f"{GRAPH}/groups/g2/members",
        ]
        assert [(r["group_id"], r["id"], r["member_type"]) for r in rows] == [
            ("g1", "u1", "#microsoft.graph.user"),
            ("g2", "g3", "#microsoft.graph.group"),
        ]
        # The OData discriminator is normalized away; `@` is not a usable warehouse column.
        assert all("@odata.type" not in row and "_Groups_id" not in row for row in rows)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_parent_projection_is_minimal(self, MockSession: mock.MagicMock, _auth: mock.MagicMock) -> None:
        params, _urls = _wire(MockSession.return_value, [_page([{"id": "g1"}]), _page([{"id": "u1"}])])

        _rows(_source("GroupMembers", _make_manager()))

        assert params[0]["$select"] == "id"
        # The child request carries no `$select` — members are a heterogeneous collection.
        assert "$select" not in params[1]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_skips_groups_already_completed(self, MockSession: mock.MagicMock, _auth: mock.MagicMock) -> None:
        # Resume state records finished group paths, so a retry doesn't refetch them.
        _params, urls = _wire(
            MockSession.return_value,
            [_page([{"id": "g1"}, {"id": "g2"}]), _page([{"id": "u2"}])],
        )

        manager = _make_manager(MicrosoftEntraIdResumeConfig(completed=["/groups/g1/members"]))
        rows = _rows(_source("GroupMembers", manager))

        assert urls == [f"{GRAPH}/groups", f"{GRAPH}/groups/g2/members"]
        assert [r["group_id"] for r in rows] == ["g2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_completed_groups(self, MockSession: mock.MagicMock, _auth: mock.MagicMock) -> None:
        _wire(MockSession.return_value, [_page([{"id": "g1"}]), _page([{"id": "u1"}])])

        manager = _make_manager()
        _rows(_source("GroupMembers", manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved[-1] == MicrosoftEntraIdResumeConfig(completed=["/groups/g1/members"])


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("Users", ["id"], "asc", "createdDateTime"),
            ("Groups", ["id"], "asc", "createdDateTime"),
            ("GroupMembers", ["group_id", "id"], "asc", None),
            ("Applications", ["id"], "asc", None),
            ("DirectoryAudits", ["id"], "desc", "activityDateTime"),
            ("SignIns", ["id"], "desc", "createdDateTime"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    @mock.patch(AUTH_PATCH, return_value=BearerTokenAuth("access-token"))
    def test_shape(
        self,
        endpoint: str,
        expected_keys: list[str],
        expected_sort: str,
        partition_key: str | None,
        _auth: mock.MagicMock,
        _session: mock.MagicMock,
    ) -> None:
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == expected_sort
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [partition_key]


@mock.patch(AUTH_PATCH, return_value=BearerTokenAuth("access-token"))
class TestRetryAndErrors:
    @parameterized.expand([("throttled", 429), ("server_error", 503)])
    @mock.patch("time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_transient_status_is_retried(
        self,
        _name: str,
        status: int,
        MockSession: mock.MagicMock,
        _sleep: mock.MagicMock,
        _auth: mock.MagicMock,
    ) -> None:
        # Graph throttles per app per tenant with 429 + Retry-After; the shared client already
        # retries on status, so a throttle must not fail the sync.
        session = MockSession.return_value
        _wire(session, [_page([], status=status), _page([{"id": "u1"}])])

        assert [r["id"] for r in _rows(_source("Users", _make_manager()))] == ["u1"]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_failures_fail_loud(
        self, _name: str, status: int, MockSession: mock.MagicMock, _auth: mock.MagicMock
    ) -> None:
        response = _page([], status=status)
        response.url = f"{GRAPH}/users"
        _wire(MockSession.return_value, [response])

        with pytest.raises(HTTPError):
            _rows(_source("Users", _make_manager()))


class TestValidateCredentials:
    def test_rejects_a_tenant_that_escapes_the_token_url(self) -> None:
        ok, message = validate_credentials("tenant/../evil", "client-id", "secret")
        assert ok is False
        assert message is not None
        assert "tenant" in message.lower()

    def test_reports_a_rejected_client_secret(self) -> None:
        auth = mock.MagicMock()
        with (
            mock.patch(AUTH_PATCH, return_value=auth),
            mock.patch(
                PRIME_PATCH,
                side_effect=OAuth2AuthRequestError(
                    "HTTP 401 from the OAuth2 token endpoint: invalid_client", is_permanent=True
                ),
            ),
        ):
            ok, message = validate_credentials("contoso.onmicrosoft.com", "client-id", "secret")

        assert ok is False
        assert message is not None
        assert "invalid_client" in message
        # The internal classifier marker must never reach the user.
        assert "[oauth2_token_config_error]" not in message

    def test_reports_an_unreachable_identity_platform(self) -> None:
        with (
            mock.patch(AUTH_PATCH, return_value=mock.MagicMock()),
            mock.patch(PRIME_PATCH, side_effect=ConnectionError("boom")),
        ):
            ok, message = validate_credentials("contoso.onmicrosoft.com", "client-id", "secret")

        assert (ok, message) == (
            False,
            "Could not reach the Microsoft identity platform to get an access token. Please try again.",
        )

    def _probe(self, status: int | None, schema_name: str | None = None) -> tuple[bool, str | None]:
        session = mock.MagicMock()
        if status is None:
            session.get.side_effect = ConnectionError("boom")
        else:
            session.get.return_value = mock.MagicMock(status_code=status)
        with (
            mock.patch(AUTH_PATCH, return_value=mock.MagicMock()),
            mock.patch(PRIME_PATCH),
            mock.patch(SESSION_PATCH, return_value=session),
        ):
            return validate_credentials("contoso.onmicrosoft.com", "client-id", "secret", schema_name=schema_name)

    def test_accepts_a_working_probe(self) -> None:
        assert self._probe(200) == (True, None)

    def test_accepts_a_missing_scope_at_source_create(self) -> None:
        # A tenant may only consent to the tables it wants synced, so a 403 on the generic probe
        # must not block creating the source.
        ok, message = self._probe(403)
        assert (ok, message) == (True, None)

    def test_rejects_a_missing_scope_for_a_specific_table(self) -> None:
        ok, message = self._probe(403, schema_name="SignIns")
        assert ok is False
        assert message is not None
        assert "AuditLog.Read.All" in message

    @parameterized.expand([("unauthorized", 401), ("bad_request", 400), ("unreachable", None)])
    def test_rejects_other_outcomes(self, _name: str, status: int | None) -> None:
        ok, message = self._probe(status)
        assert ok is False
        assert message


class TestCheckEndpointPermissions:
    def _run(self, statuses: dict[str, int], endpoints: list[str]) -> dict[str, str | None]:
        session = mock.MagicMock()

        def _get(url: str, **_kwargs: Any) -> mock.MagicMock:
            for name, status in statuses.items():
                if ENTRA_ENDPOINTS[name].permission_probe_path in url:
                    return mock.MagicMock(status_code=status)
            return mock.MagicMock(status_code=200)

        session.get.side_effect = _get
        with (
            mock.patch(AUTH_PATCH, return_value=mock.MagicMock()),
            mock.patch(PRIME_PATCH),
            mock.patch(SESSION_PATCH, return_value=session),
        ):
            return check_endpoint_permissions("contoso.onmicrosoft.com", "client-id", "secret", endpoints)

    def test_reports_only_denied_endpoints(self) -> None:
        result = self._run({"SignIns": 403}, ["Users", "SignIns"])
        assert result["Users"] is None
        assert result["SignIns"] is not None
        assert "AuditLog.Read.All" in result["SignIns"]

    @parameterized.expand([("throttled", 429), ("server_error", 500), ("bad_request", 400)])
    def test_non_denial_failures_are_not_reported_as_missing_permissions(self, _name: str, status: int) -> None:
        # A throttle or a 5xx is not a permission problem; reporting it as one would tell users to
        # grant a permission they already have.
        assert self._run({"Users": status}, ["Users"])["Users"] is None

    def test_token_failure_reports_nothing(self) -> None:
        # A failed token exchange says nothing about per-table access, and the source-level
        # credential check already surfaces it — so don't blame a permission here.
        with (
            mock.patch(AUTH_PATCH, return_value=mock.MagicMock()),
            mock.patch(PRIME_PATCH, side_effect=OAuth2AuthRequestError("nope", is_permanent=True)),
        ):
            assert check_endpoint_permissions("contoso.onmicrosoft.com", "c", "s", ["Users"]) == {"Users": None}


if __name__ == "__main__":
    pytest.main([__file__])
