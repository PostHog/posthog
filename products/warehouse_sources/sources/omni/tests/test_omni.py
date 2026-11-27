import json
from typing import Any

import pytest
from unittest import mock

from requests import Request, Response

from products.warehouse_sources.sources.omni import omni as omni_module
from products.warehouse_sources.sources.omni._config import OmniSourceConfig
from products.warehouse_sources.sources.omni.omni import (
    OmniDocumentsPaginator,
    OmniResumeConfig,
    OmniScimPaginator,
    _format_watermark,
    get_endpoint_permissions,
    get_key_scope,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.sources.omni.settings import FANOUT_ENDPOINTS, PARTITION_KEYS, PRIMARY_KEYS
from products.warehouse_sources.sources.omni.source import OmniSource
from products.warehouse_sources.sources.sdk.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)


def _make_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://acme.omniapp.co", "https://acme.omniapp.co"),
            ("acme.omniapp.co", "https://acme.omniapp.co"),
            ("https://acme.omniapp.co/api", "https://acme.omniapp.co"),
            ("http://acme.omniapp.co", "https://acme.omniapp.co"),
            ("http://localhost:8080", "http://localhost:8080"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestFormatWatermark:
    def test_formats_datetime_with_millisecond_precision(self):
        import datetime

        value = datetime.datetime(2026, 6, 1, 14, 30, 0, 500000, tzinfo=datetime.UTC)
        assert _format_watermark(value) == "2026-06-01T14:30:00.500Z"

    def test_string_value_passed_through(self):
        assert _format_watermark("2026-06-01T14:30:00.000Z") == "2026-06-01T14:30:00.000Z"

    @pytest.mark.parametrize("value", [None, "", 123])
    def test_unsupported_values_return_none(self, value):
        assert _format_watermark(value) is None


class TestOmniDocumentsPaginator:
    def test_full_sync_never_stops_early(self):
        paginator = OmniDocumentsPaginator(stop_when_older_than=None)
        response = _make_response({"pageInfo": {"hasNextPage": True, "nextCursor": "c1"}, "records": []})
        data = [{"updatedAt": "2020-01-01T00:00:00.000Z"}]
        paginator.update_state(response, data)

        assert paginator.has_next_page is True

    def test_incremental_stops_once_page_predates_watermark(self):
        paginator = OmniDocumentsPaginator(stop_when_older_than="2026-01-01T00:00:00.000Z")
        response = _make_response({"pageInfo": {"hasNextPage": True, "nextCursor": "c1"}, "records": []})
        data = [
            {"updatedAt": "2025-06-01T00:00:00.000Z"},
            {"updatedAt": "2025-05-01T00:00:00.000Z"},
        ]
        paginator.update_state(response, data)

        assert paginator.has_next_page is False


class TestOmniScimPaginator:
    def test_set_resume_state_seeds_start_index(self):
        paginator = OmniScimPaginator()
        paginator.set_resume_state({"start_index": 201})

        request = Request(method="GET", url="https://acme.omniapp.co/api/scim/v2/users")
        paginator.init_request(request)
        assert request.params["startIndex"] == 201


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, schema_name, expected_valid",
        [
            (200, None, True),
            (200, "Documents", True),
            (401, None, False),
            (401, "Documents", False),
            (403, None, True),
            (403, "Documents", False),
            (500, None, False),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, status_code: int, schema_name: str | None, expected_valid: bool
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, error = validate_credentials("acme.omniapp.co", "test-key", team_id=1, schema_name=schema_name)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error
        assert network.requests_log
        assert {request.path for request in network.requests_log} == {"/api/v1/whoami"}
        assert all(request.headers["authorization"] == "Bearer test-key" for request in network.requests_log)
        assert network.session_options[0]["allow_redirects"] is False

    @mock.patch.object(omni_module, "_is_host_safe", return_value=(False, "internal address"))
    def test_validate_credentials_blocks_unsafe_host(self, _mock_host_safe):
        is_valid, error = validate_credentials("169.254.169.254", "test-key", team_id=1)

        assert is_valid is False
        assert error == "internal address"

    def test_validate_credentials_rejects_invalid_hostname(self):
        is_valid, error = validate_credentials("not a host!!", "test-key", team_id=1)
        assert is_valid is False
        assert error


class TestGetKeyScope:
    def test_returns_key_scope_on_success(self) -> None:
        with scripted_network([ScriptedResponse(json={"keyScope": "organization"})]) as network:
            assert get_key_scope("acme.omniapp.co", "test-key") == "organization"
        assert [request.path for request in network.requests_log] == ["/api/v1/whoami"]

    def test_returns_none_on_error_status(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]):
            assert get_key_scope("acme.omniapp.co", "test-key") is None

    def test_returns_none_on_request_exception(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))):
            assert get_key_scope("acme.omniapp.co", "test-key") is None


class TestGetEndpointPermissions:
    def test_no_scim_endpoints_requested_returns_all_reachable(self):
        result = get_endpoint_permissions("acme.omniapp.co", "test-key", ["Documents", "Folders"])
        assert result == {"Documents": None, "Folders": None}

    @mock.patch.object(omni_module, "get_key_scope", return_value="user")
    def test_pat_scope_blocks_scim_endpoints(self, _mock_scope):
        result = get_endpoint_permissions("acme.omniapp.co", "test-key", ["Documents", "Users", "UserGroups"])

        assert result["Documents"] is None
        assert result["Users"] is not None
        assert result["UserGroups"] is not None


class TestOmniSourceEndToEnd:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(OmniSource(), OmniSourceConfig(host="acme.omniapp.co", api_key="test-key"))

    def test_documents_pagination_and_checkpointing(self) -> None:
        result = self._driver().run(
            "Documents",
            [
                ScriptedResponse(
                    json={
                        "pageInfo": {"hasNextPage": True, "nextCursor": "cursor-1"},
                        "records": [{"identifier": "d1", "updatedAt": "2026-01-02T00:00:00.000Z"}],
                    }
                ),
                ScriptedResponse(
                    json={
                        "pageInfo": {"hasNextPage": False, "nextCursor": None},
                        "records": [{"identifier": "d2", "updatedAt": "2026-01-01T00:00:00.000Z"}],
                    }
                ),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 2
        assert result.params("sortField") == ["updatedAt", "updatedAt"]
        assert result.params("sortDirection") == ["desc", "desc"]
        assert result.params("cursor") == [None, "cursor-1"]
        assert result.saved_states == [OmniResumeConfig(cursor="cursor-1")]
        assert result.committed_states == [OmniResumeConfig(cursor="cursor-1")]

    def test_documents_resumes_from_saved_cursor(self) -> None:
        result = self._driver().run(
            "Documents",
            [ScriptedResponse(json={"pageInfo": {"hasNextPage": False, "nextCursor": None}, "records": []})],
            resume_state=OmniResumeConfig(cursor="resumed-cursor"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["resumed-cursor"]

    @pytest.mark.parametrize(
        "endpoint, path, selector, rows",
        [
            ("Connections", "/api/v1/connections", "connections", [{"id": "c1"}, {"id": "c2"}]),
            ("Labels", "/api/v1/labels", "labels", [{"name": "Production"}, {"name": "Draft"}]),
        ],
    )
    def test_single_page_endpoints_never_checkpoint(
        self, endpoint: str, path: str, selector: str, rows: list[dict[str, Any]]
    ) -> None:
        result = self._driver().run(endpoint, [ScriptedResponse(json={selector: rows})])

        assert result.raised is None
        assert result.paths == [path]
        assert result.rows == rows
        assert result.saved_states == []

    def test_ai_conversations_paginates_by_cursor(self) -> None:
        result = self._driver().run(
            "AiConversations",
            [
                ScriptedResponse(
                    json={
                        "pageInfo": {"hasNextPage": True, "nextCursor": "conv-cursor"},
                        "records": [{"id": "a1", "userId": "u1"}],
                    }
                ),
                ScriptedResponse(
                    json={"pageInfo": {"hasNextPage": False, "nextCursor": None}, "records": [{"id": "a2"}]}
                ),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/ai/conversations", "/api/v1/ai/conversations"]
        assert [row["id"] for row in result.rows] == ["a1", "a2"]
        assert result.params("cursor") == [None, "conv-cursor"]
        assert result.saved_states == [OmniResumeConfig(cursor="conv-cursor")]

    def test_users_scim_pagination_checkpoints_start_index(self) -> None:
        result = self._driver().run(
            "Users",
            [
                ScriptedResponse(
                    json={"Resources": [{"id": "u1"}], "itemsPerPage": 1, "totalResults": 2, "startIndex": 1}
                ),
                ScriptedResponse(
                    json={"Resources": [{"id": "u2"}], "itemsPerPage": 1, "totalResults": 2, "startIndex": 2}
                ),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": "u1"}, {"id": "u2"}]
        assert result.params("startIndex") == ["1", "2"]
        assert result.saved_states == [OmniResumeConfig(start_index=2)]

    def test_schedule_recipients_fans_out_per_schedule(self) -> None:
        result = self._driver().run(
            "ScheduleRecipients",
            route(
                {
                    "/api/v1/schedules": [
                        ScriptedResponse(
                            json={
                                "pageInfo": {"hasNextPage": False, "nextCursor": None},
                                "records": [{"id": "s1"}, {"id": "s2"}],
                            }
                        )
                    ],
                    "/api/v1/schedules/s1/recipients": [
                        ScriptedResponse(json={"type": "email", "recipients": [{"id": "u1", "email": "a@example.com"}]})
                    ],
                    # A schedule deleted between the listing and its recipients fetch is skipped.
                    "/api/v1/schedules/s2/recipients": [ScriptedResponse(status=404, json={"detail": "not found"})],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"type": "email", "recipients": [{"id": "u1", "email": "a@example.com"}], "scheduleId": "s1"}
        ]
        assert result.response is not None
        assert result.response.primary_keys == ["scheduleId"]

    def test_document_permissions_paginates_per_document_and_keys_principals(self) -> None:
        result = self._driver().run(
            "DocumentPermissions",
            route(
                {
                    "/api/v1/documents": [
                        ScriptedResponse(
                            json={
                                "pageInfo": {"hasNextPage": False, "nextCursor": None},
                                "records": [{"identifier": "d1"}, {"identifier": "d2"}],
                            }
                        )
                    ],
                    "/api/v1/documents/d1/access-list": [
                        ScriptedResponse(
                            json={
                                "pageInfo": {"hasNextPage": True, "nextCursor": "p2"},
                                "principals": [{"userId": "u1", "type": "user", "accessSource": "direct"}],
                            }
                        ),
                        ScriptedResponse(
                            json={
                                "pageInfo": {"hasNextPage": False, "nextCursor": None},
                                "principals": [{"userGroupId": "g1", "type": "userGroup", "accessSource": "folder"}],
                            }
                        ),
                    ],
                    # The key lacks Manager permission on this document; it's skipped, not fatal.
                    "/api/v1/documents/d2/access-list": [ScriptedResponse(status=403, json={"status": 403})],
                }
            ),
        )

        assert result.raised is None
        assert [(row["documentId"], row["principalId"], row["accessSource"]) for row in result.rows] == [
            ("d1", "u1", "direct"),
            ("d1", "g1", "folder"),
        ]
        # The parent listing sorts on a field that edits don't move, unlike the Documents table's `updatedAt`.
        assert result.requests[0].path == "/api/v1/documents"
        assert result.requests[0].param("sortField") == "name"
        assert result.params("cursor") == [None, None, "p2", None]

    def test_document_permissions_resume_skips_completed_documents(self) -> None:
        result = self._driver().run(
            "DocumentPermissions",
            route(
                {
                    "/api/v1/documents": [
                        ScriptedResponse(
                            json={
                                "pageInfo": {"hasNextPage": False, "nextCursor": None},
                                "records": [{"identifier": "d1"}, {"identifier": "d2"}],
                            }
                        )
                    ],
                    "/api/v1/documents/d2/access-list": [
                        ScriptedResponse(
                            json={
                                "pageInfo": {"hasNextPage": False, "nextCursor": None},
                                "principals": [{"userId": "u2", "type": "user", "accessSource": "direct"}],
                            }
                        )
                    ],
                }
            ),
            resume_state=OmniResumeConfig(
                fanout_state={"completed": ["/v1/documents/d1/access-list"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/documents", "/api/v1/documents/d2/access-list"]
        assert [row["documentId"] for row in result.rows] == ["d2"]
        assert result.final_state.fanout_state["completed"] == [
            "/v1/documents/d1/access-list",
            "/v1/documents/d2/access-list",
        ]

    @pytest.mark.parametrize(
        "endpoint, parent_path, parent_body, children, expected_keys",
        [
            (
                "UserModelRoles",
                "/api/scim/v2/users",
                {"Resources": [{"id": "u1"}, {"id": "u2"}], "itemsPerPage": 2, "totalResults": 2, "startIndex": 1},
                {
                    "/api/v1/users/u1/model-roles": ScriptedResponse(
                        json={
                            "membershipId": "m1",
                            "results": [
                                {"modelId": "mod1", "connectionId": "con1", "from": {"type": "User Role"}},
                                {
                                    "modelId": "mod1",
                                    "connectionId": "con1",
                                    "from": {"type": "Group Role", "miniUuid": "g1", "name": "Analysts", "depth": 0},
                                },
                                {"modelId": "mod1", "connectionId": "con1", "from": {"type": "Connection Base Role"}},
                            ],
                        }
                    ),
                    # A user removed between the listing and the roles fetch is skipped.
                    "/api/v1/users/u2/model-roles": ScriptedResponse(status=404, json={"detail": "not found"}),
                },
                [
                    ("u1", "mod1", "con1", "User Role", ""),
                    ("u1", "mod1", "con1", "Group Role", "g1"),
                    ("u1", "mod1", "con1", "Connection Base Role", ""),
                ],
            ),
            (
                "UserGroupModelRoles",
                "/api/scim/v2/groups",
                {"Resources": [{"id": "g1"}, {"id": "g2"}], "itemsPerPage": 2, "totalResults": 2, "startIndex": 1},
                {
                    "/api/v1/user-groups/g1/model-roles": ScriptedResponse(
                        json={"userGroupId": "g1", "results": [{"modelId": "mod1", "connectionId": "con1"}]}
                    ),
                    "/api/v1/user-groups/g2/model-roles": ScriptedResponse(status=404, json={"detail": "not found"}),
                },
                [("g1", "mod1", "con1")],
            ),
            (
                "FolderPermissions",
                "/api/v1/folders",
                {"pageInfo": {"hasNextPage": False, "nextCursor": None}, "records": [{"id": "f1"}, {"id": "f2"}]},
                {
                    "/api/v1/folders/f1/permissions": ScriptedResponse(
                        json={
                            "permits": [
                                {"id": "u1", "userId": "u1", "type": "user"},
                                {"id": "g1", "userGroupId": "g1", "type": "userGroup"},
                                # An organization-wide permission carries only the deprecated `id`.
                                {"id": "org1", "type": "user"},
                            ]
                        }
                    ),
                    # The key lacks Manager permission on this folder; it's skipped, not fatal.
                    "/api/v1/folders/f2/permissions": ScriptedResponse(status=403, json={"status": 403}),
                },
                [("f1", "u1"), ("f1", "g1"), ("f1", "org1")],
            ),
        ],
    )
    def test_fanout_tables_key_rows_by_parent(
        self,
        endpoint: str,
        parent_path: str,
        parent_body: dict[str, Any],
        children: dict[str, ScriptedResponse],
        expected_keys: list[tuple[str, ...]],
    ) -> None:
        result = self._driver().run(
            endpoint,
            route({parent_path: [ScriptedResponse(json=parent_body)], **{path: [r] for path, r in children.items()}}),
        )

        assert result.raised is None
        assert result.response is not None
        primary_keys = result.response.primary_keys
        assert primary_keys == PRIMARY_KEYS[endpoint]
        assert [tuple(row[key] for key in primary_keys) for row in result.rows] == expected_keys

    @pytest.mark.parametrize("endpoint", [name for name in PRIMARY_KEYS if name not in FANOUT_ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        selector = {
            "Documents": "records",
            "Folders": "records",
            "Connections": "connections",
            "Schedules": "records",
            "Users": "Resources",
            "UserGroups": "Resources",
            "Models": "records",
            "UserAttributes": "records",
            "AiConversations": "records",
            "Labels": "labels",
        }[endpoint]
        body = {"pageInfo": {"hasNextPage": False, "nextCursor": None}, selector: []}
        result = self._driver().run(endpoint, [ScriptedResponse(json=body)])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.primary_keys == PRIMARY_KEYS[endpoint]
        assert response.sort_mode == ("desc" if endpoint == "Documents" else "asc")
        partition_key = PARTITION_KEYS[endpoint]
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestOmniSourceSsrfGuards:
    @mock.patch.object(omni_module, "_is_host_safe", return_value=(False, "internal address"))
    def test_sync_rejects_unsafe_host(self, _mock_host_safe: mock.MagicMock) -> None:
        # A hostname that validated publicly can be DNS-rebound to a private address before a
        # scheduled import runs; the sync must re-check rather than trust the stored host.
        result = TestOmniSourceEndToEnd._driver().run("Connections", [])

        assert isinstance(result.raised, ValueError)
        assert "internal address" in str(result.raised)
        assert result.requests == []

    def test_sync_pins_host_and_disables_redirects(self) -> None:
        result = TestOmniSourceEndToEnd._driver().run(
            "Connections",
            [
                ScriptedResponse(
                    status=302,
                    headers={"Location": "https://other.example.com/steal"},
                )
            ],
        )

        # Redirects are never followed, so a 3xx can't bounce the bearer token off-host.
        assert isinstance(result.raised, ValueError)
        assert "refusing to follow" in str(result.raised)
        assert len(result.requests) == 1
        assert result.requests[0].origin == "https://acme.omniapp.co"
        assert result.requests[0].headers["authorization"] == "Bearer test-key"
