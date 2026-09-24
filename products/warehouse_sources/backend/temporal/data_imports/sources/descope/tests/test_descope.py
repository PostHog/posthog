import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.descope.descope import (
    DAY_MS,
    DescopeResumeConfig,
    _analytics_body,
    _audit_body,
    _audit_row_id,
    _users_body,
    bearer_token,
    descope_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.descope.settings import (
    ANALYTICS_LOOKBACK_DAYS,
    ENDPOINTS,
    PARTITION_KEYS,
    PRIMARY_KEYS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the descope module.
DESCOPE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.descope.descope.make_tracked_session"
)


SELECTORS = {
    "Users": "users",
    "Audit": "audits",
    "Tenants": "tenants",
    "Roles": "roles",
    "AccessKeys": "keys",
    "Permissions": "permissions",
    "Analytics": "analytics",
    "Groups": "groups",
    "UserHistory": "users",
}


def _response(payload: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(payload).encode()
    return resp


def _make_manager(resume_state: DescopeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's JSON body AT SEND TIME.

    ``request.json`` is a single dict mutated in place across pages (the paginator injects
    ``page`` into it), so inspecting it after the run shows only the final state — snapshot
    a copy when each request is prepared instead.
    """
    session.headers = {}
    body_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        body_snapshots.append(dict(request.json or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return body_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str = "Users", manager: mock.MagicMock | None = None, **kwargs: Any):
    return descope_source(
        "P2abc",
        "mgmt-key",
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        **kwargs,
    )


class TestBearerToken:
    def test_joins_project_id_and_key(self):
        assert bearer_token("P2abc", "secretkey") == "P2abc:secretkey"


class TestUsersBody:
    def test_full_refresh_defaults_to_created_time_sort(self):
        body = _users_body(
            should_use_incremental_field=False, incremental_field=None, db_incremental_field_last_value=None
        )

        assert body["limit"] == 100
        assert body["sort"] == [{"field": "createdTime", "desc": False}]
        assert "fromCreatedTime" not in body
        assert "fromModifiedTime" not in body

    @pytest.mark.parametrize(
        "incremental_field, expected_param",
        [
            ("createdTime", "fromCreatedTime"),
            ("modifiedTime", "fromModifiedTime"),
        ],
    )
    def test_incremental_sets_matching_time_param_and_sort(self, incremental_field, expected_param):
        body = _users_body(
            should_use_incremental_field=True,
            incremental_field=incremental_field,
            db_incremental_field_last_value=1700000000000,
        )

        assert body["sort"] == [{"field": incremental_field, "desc": False}]
        assert body[expected_param] == 1700000000000

    def test_incremental_without_last_value_omits_time_param(self):
        body = _users_body(
            should_use_incremental_field=True, incremental_field="createdTime", db_incremental_field_last_value=None
        )
        assert "fromCreatedTime" not in body


class TestAuditBody:
    def test_full_refresh_body_is_empty(self):
        assert _audit_body(should_use_incremental_field=False, db_incremental_field_last_value=None) == {}

    def test_incremental_body_sets_from(self):
        body = _audit_body(should_use_incremental_field=True, db_incremental_field_last_value=1700000000000)
        assert body == {"from": 1700000000000}

    def test_incremental_without_last_value_stays_empty(self):
        assert _audit_body(should_use_incremental_field=True, db_incremental_field_last_value=None) == {}


class TestAuditRowId:
    def test_deterministic_for_identical_events(self):
        row_a = {
            "userId": "u1",
            "action": "login",
            "occurred": 1700000000000,
            "device": "Desktop",
            "method": "otp",
            "remoteAddress": "1.2.3.4",
        }
        row_b = dict(row_a)

        assert _audit_row_id(row_a)["id"] == _audit_row_id(row_b)["id"]

    def test_differs_for_different_events(self):
        base = {
            "userId": "u1",
            "action": "login",
            "occurred": 1700000000000,
            "device": "Desktop",
            "method": "otp",
            "remoteAddress": "1.2.3.4",
        }
        other = {**base, "userId": "u2"}

        assert _audit_row_id(dict(base))["id"] != _audit_row_id(other)["id"]

    def test_handles_missing_fields(self):
        row = _audit_row_id({})
        assert isinstance(row["id"], str) and len(row["id"]) == 64

    def test_hash_is_stable_across_releases(self):
        # Audit rows already in customers' tables are keyed on this digest. Changing how it is
        # built re-keys every row and duplicates the table on the next merge.
        row = _audit_row_id(
            {
                "userId": "u1",
                "action": "login",
                "occurred": 1700000000000,
                "device": "Desktop",
                "method": "otp",
                "remoteAddress": "1.2.3.4",
            }
        )
        assert row["id"] == "9355be9401127bf98697c12f126210eb29af88dfe8a1eb6e7b665ff3d041acd0"


class TestAnalyticsBody:
    def test_window_starts_one_year_before_now(self):
        now_ms = 1_700_000_000_000
        body = _analytics_body(now_ms)

        assert body["from"] == now_ms - ANALYTICS_LOOKBACK_DAYS * DAY_MS
        assert "to" not in body

    def test_groups_on_every_dimension(self):
        # Dropping a groupBy collapses rows into counts we cannot split apart again.
        body = _analytics_body(1_700_000_000_000)

        assert body["groupByCreated"] == "d"
        assert all(
            body[key] is True
            for key in (
                "groupByAction",
                "groupByDevice",
                "groupByMethod",
                "groupByGeo",
                "groupByTenant",
                "groupByReferrer",
            )
        )


class TestGetResource:
    @pytest.mark.parametrize(
        "endpoint, expected_path, expected_method, expected_selector",
        [
            ("Users", "/v2/mgmt/user/search", "POST", "users"),
            ("Audit", "/v1/mgmt/audit/search", "POST", "audits"),
            ("Tenants", "/v1/mgmt/tenant/all", None, "tenants"),
            ("Roles", "/v1/mgmt/role/search", "POST", "roles"),
            ("AccessKeys", "/v1/mgmt/accesskey/search", "POST", "keys"),
            ("Permissions", "/v1/mgmt/permission/all", None, "permissions"),
            ("Analytics", "/v1/mgmt/analytics/search", "POST", "analytics"),
        ],
    )
    def test_endpoint_shape(self, endpoint, expected_path, expected_method, expected_selector):
        resource = get_resource(
            endpoint, should_use_incremental_field=False, incremental_field=None, db_incremental_field_last_value=None
        )
        endpoint_config = resource["endpoint"]
        assert isinstance(endpoint_config, dict)

        assert endpoint_config["path"] == expected_path
        assert endpoint_config.get("method") == expected_method
        assert endpoint_config["data_selector"] == expected_selector

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError):
            get_resource(
                "Nope", should_use_incremental_field=False, incremental_field=None, db_incremental_field_last_value=None
            )

    @pytest.mark.parametrize("endpoint", ["Users", "Audit"])
    def test_incremental_endpoints_use_merge_when_enabled(self, endpoint):
        resource = get_resource(
            endpoint,
            should_use_incremental_field=True,
            incremental_field="createdTime",
            db_incremental_field_last_value=1,
        )
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    @pytest.mark.parametrize("endpoint", ["Tenants", "Roles", "AccessKeys", "Permissions", "Analytics"])
    def test_full_refresh_endpoints_always_replace(self, endpoint):
        resource = get_resource(
            endpoint, should_use_incremental_field=True, incremental_field=None, db_incremental_field_last_value=None
        )
        assert resource["write_disposition"] == "replace"


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
        ],
    )
    @mock.patch(DESCOPE_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.post.return_value = response

        assert validate_credentials("P2abc", "mgmt-key") is expected

    @mock.patch(DESCOPE_SESSION_PATCH)
    def test_sends_bearer_token(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.post.return_value = response

        validate_credentials("P2abc", "mgmt-key")

        _, kwargs = mock_session.return_value.post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer P2abc:mgmt-key"


class TestUsersPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_page_number_in_json_body(self, MockSession):
        session = MockSession.return_value
        full_page = [{"userId": f"u{i}"} for i in range(100)]
        # PageNumberPaginator only stops on a fully empty page, so a short (but non-empty)
        # second page still triggers a third, empty request before pagination ends.
        bodies = _wire(
            session,
            [
                _response({"users": full_page}),
                _response({"users": [{"userId": "last"}]}),
                _response({"users": []}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager=manager))

        assert len(rows) == 101
        assert bodies[0]["page"] == 0
        assert bodies[1]["page"] == 1
        assert bodies[2]["page"] == 2
        # Checkpoint saved after each page with a next page pending.
        assert manager.save_state.call_args_list == [
            mock.call(DescopeResumeConfig(page=1)),
            mock.call(DescopeResumeConfig(page=2)),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_stops_pagination(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"users": []})])

        manager = _make_manager()
        rows = _rows(_source(manager=manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession):
        session = MockSession.return_value
        bodies = _wire(session, [_response({"users": []})])

        manager = _make_manager(DescopeResumeConfig(page=3))
        _rows(_source(manager=manager))

        assert bodies[0]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_body_carries_watermark(self, MockSession):
        session = MockSession.return_value
        bodies = _wire(session, [_response({"users": []})])

        _rows(
            _source(
                should_use_incremental_field=True,
                incremental_field="modifiedTime",
                db_incremental_field_last_value=1700000000000,
            )
        )

        assert bodies[0]["fromModifiedTime"] == 1700000000000
        assert bodies[0]["sort"] == [{"field": "modifiedTime", "desc": False}]


class TestAuditFetch:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_fetch_synthesizes_row_id(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    {
                        "audits": [
                            {"userId": "u1", "action": "login", "occurred": 1700000000000},
                        ]
                    }
                )
            ],
        )

        rows = _rows(_source(endpoint="Audit"))

        assert session.send.call_count == 1
        assert "id" in rows[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_sends_from_timestamp(self, MockSession):
        session = MockSession.return_value
        bodies = _wire(session, [_response({"audits": []})])

        _rows(
            _source(endpoint="Audit", should_use_incremental_field=True, db_incremental_field_last_value=1700000000000)
        )

        assert bodies[0]["from"] == 1700000000000


class TestFullRefreshEndpoints:
    @pytest.mark.parametrize(
        "endpoint, selector, response_key",
        [
            ("Tenants", "tenants", "tenants"),
            ("Roles", "roles", "roles"),
            ("AccessKeys", "keys", "keys"),
            ("Permissions", "permissions", "permissions"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fetches_full_list_in_one_request(self, MockSession, endpoint, selector, response_key):
        session = MockSession.return_value
        _wire(session, [_response({response_key: [{"id": "1"}, {"id": "2"}]})])

        rows = _rows(_source(endpoint=endpoint))

        assert session.send.call_count == 1
        assert rows == [{"id": "1"}, {"id": "2"}]


class TestDescopeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint):
        session = MockSession.return_value
        _wire(session, [_response({selector: []}) for selector in SELECTORS.values()])

        response = _source(endpoint=endpoint)

        assert response.name == endpoint
        assert response.primary_keys == PRIMARY_KEYS[endpoint]
        assert response.sort_mode == "asc"
        # Permissions, Groups and Analytics carry no timestamp, so they sync unpartitioned;
        # partitioning them on a field their rows lack would fail the write.
        partition_key = PARTITION_KEYS.get(endpoint)
        assert response.partition_mode == ("datetime" if partition_key else None)
        assert response.partition_keys == ([partition_key] if partition_key else None)


class TestGroupsFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_loads_groups_per_tenant_and_stamps_the_tenant_id(self, MockSession):
        session = MockSession.return_value
        bodies = _wire(
            session,
            [
                _response({"tenants": [{"id": "T1"}, {"id": "T2"}]}),
                _response({"groups": [{"id": "g1", "display": "Engineering"}]}),
                _response({"groups": [{"id": "g1", "display": "Support"}]}),
            ],
        )

        rows = _rows(_source(endpoint="Groups"))

        # The group id repeats across tenants, which is why the tenant has to ride on the row —
        # the primary key is ["tenantId", "id"].
        assert rows == [
            {"id": "g1", "display": "Engineering", "tenantId": "T1"},
            {"id": "g1", "display": "Support", "tenantId": "T2"},
        ]
        assert bodies[1] == {"tenantId": "T1"}
        assert bodies[2] == {"tenantId": "T2"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_tenant_without_groups_yields_nothing(self, MockSession):
        session = MockSession.return_value
        # Descope omits the `groups` key entirely for a tenant with none.
        _wire(session, [_response({"tenants": [{"id": "T1"}]}), _response({})])

        assert _rows(_source(endpoint="Groups")) == []


class TestUserHistoryFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_posts_each_user_page_and_checkpoints_after_it(self, MockSession):
        session = MockSession.return_value
        bodies = _wire(
            session,
            [
                _response({"users": [{"userId": "u1"}, {"userId": "u2"}]}),
                _response({"usersAuthHistory": [{"userId": "u1", "loginTime": 1700000000}]}),
                _response({"users": []}),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(endpoint="UserHistory", manager=manager))

        assert bodies[0]["page"] == 0
        assert bodies[1] == {"userIds": ["u1", "u2"]}
        assert bodies[2]["page"] == 1
        assert len(rows) == 1
        assert len(rows[0]["id"]) == 64
        # Saved only once the page's history rows were yielded, so a resume cannot skip them.
        assert manager.save_state.call_args_list == [
            mock.call(DescopeResumeConfig(page=1)),
            mock.call(DescopeResumeConfig(page=2)),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_the_saved_user_page(self, MockSession):
        session = MockSession.return_value
        bodies = _wire(session, [_response({"users": []})])

        manager = _make_manager(DescopeResumeConfig(page=4))
        _rows(_source(endpoint="UserHistory", manager=manager))

        assert bodies[0]["page"] == 4

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_user_page_without_ids_skips_the_history_request(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"users": [{"loginIds": ["a@example.com"]}]}), _response({"users": []})])

        assert _rows(_source(endpoint="UserHistory")) == []
        assert session.send.call_count == 2


class TestAnalyticsFetch:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_synthesizes_a_row_id_per_grouping_bucket(self, MockSession):
        session = MockSession.return_value
        _wire(
            session,
            [
                _response(
                    {
                        "analytics": [
                            {"created": "2026-09-01", "action": "login", "method": "otp", "cnt": "12"},
                            {"created": "2026-09-01", "action": "login", "method": "oauth", "cnt": "3"},
                        ]
                    }
                )
            ],
        )

        rows = _rows(_source(endpoint="Analytics"))

        assert session.send.call_count == 1
        assert rows[0]["id"] != rows[1]["id"]
