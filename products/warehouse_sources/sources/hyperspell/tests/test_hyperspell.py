from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hyperspell import (
    HyperspellSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell import hyperspell
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.hyperspell import (
    HyperspellResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.source import HyperspellSource


def _driver(user_ids: str | None = None) -> SourceDriver:
    return SourceDriver(HyperspellSource(), HyperspellSourceConfig(api_key="hs_test", region="us", user_ids=user_ids))


def _page(body: dict[str, Any] | list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json=body)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected_valid",
        [
            (200, True),
            (401, False),  # invalid key ("InvalidAPIKey")
            (403, False),  # missing/unaccepted auth ("Not authenticated")
            (500, False),
        ],
    )
    def test_status_mapping(self, status: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            is_valid, _ = validate_credentials("hs_test", "us")

        assert is_valid is expected_valid
        assert {request.path for request in network.requests_log} == {"/integrations/list"}

    def test_network_error_is_invalid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials("hs_test", "us")

        assert is_valid is False
        assert message is not None
        assert {request.path for request in network.requests_log} == {"/integrations/list"}


class TestGetRows:
    def test_paginates_and_yields_each_page(self) -> None:
        result = _driver().run(
            "memories",
            [
                _page({"items": [{"resource_id": "r1", "source": "slack"}], "next_cursor": "c1"}),
                _page({"items": [{"resource_id": "r2", "source": "slack"}], "next_cursor": None}),
            ],
        )

        assert result.raised is None
        assert [[row["resource_id"] for row in batch] for batch in result.items] == [["r1"], ["r2"]]
        assert result.requests[1].param("cursor") == "c1"

    def test_bookmarked_user_removed_from_config_restarts_from_first_user(self) -> None:
        result = _driver(user_ids="user-1, user-2").run(
            "memories",
            [_page({"items": [], "next_cursor": None}), _page({"items": [], "next_cursor": None})],
            resume_state=HyperspellResumeConfig(cursor="c5", user_id="user-gone"),
        )

        assert result.raised is None
        assert len(result.requests) == 2
        assert result.requests[0].param("cursor") is None

    def test_app_level_endpoint_does_not_fan_out_or_stamp_user_id(self) -> None:
        result = _driver(user_ids="user-1, user-2").run("integrations", [_page({"integrations": [{"id": "int-1"}]})])

        assert result.raised is None
        assert len(result.requests) == 1
        assert "x-as-user" not in result.requests[0].headers
        assert "user_id" not in result.items[0][0]

    def test_vaults_null_collection_becomes_empty_string(self) -> None:
        result = _driver().run(
            "vaults", [_page({"items": [{"collection": None, "document_count": 3}], "next_cursor": None})]
        )

        assert result.raised is None
        assert result.items[0][0]["collection"] == ""

    def test_users_offset_pagination_stops_at_total(self) -> None:
        result = _driver(user_ids="user-1, user-2").run(
            "users",
            [
                _page({"users": [{"user_id": "u1"}, {"user_id": "u2"}], "total": 3, "limit": 2, "offset": 0}),
                _page({"users": [{"user_id": "u3"}], "total": 3, "limit": 2, "offset": 2}),
            ],
        )

        assert result.raised is None
        assert [[row["user_id"] for row in batch] for batch in result.items] == [["u1", "u2"], ["u3"]]
        assert result.params("offset") == ["0", "2"]
        # Listing users needs an app-scoped credential, so configured user IDs must not fan it out.
        assert all("x-as-user" not in request.headers for request in result.requests)
        assert result.saved_states == [HyperspellResumeConfig(cursor="2", user_id=None)]

    def test_resumes_users_from_saved_offset(self) -> None:
        result = _driver().run(
            "users",
            [_page({"users": [{"user_id": "u401"}], "total": 401})],
            resume_state=HyperspellResumeConfig(cursor="400", user_id=None),
        )

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.requests[0].param("offset") == "400"

    def test_integration_channels_fan_out_over_channel_capable_connections(self) -> None:
        result = _driver(user_ids="user-1").run(
            "integration_channels",
            [
                _page(
                    {
                        "integrations": [
                            {"id": "int-slack", "supports_channel_selection": True},
                            {"id": "int-drive", "supports_channel_selection": False},
                            {"id": "int-teams", "requires_channel_selection": True},
                        ]
                    }
                ),
                _page(
                    {
                        "connections": [
                            {"id": "conn-1", "integration_id": "int-slack"},
                            {"id": "conn-2", "integration_id": "int-drive"},
                            {"id": "conn-3", "integration_id": "int-teams"},
                        ]
                    }
                ),
                _page(
                    {
                        "channels": [
                            {"id": "C1", "name": "general", "type": "channel"},
                            {"id": "C2", "name": "random"},
                        ],
                        "selected": ["C2"],
                    }
                ),
                _page({"channels": [], "selected": [], "pending": True}),
            ],
        )

        assert result.raised is None
        assert result.requests[2].url.endswith("/integrations/int-slack/channels?connection_id=conn-1")
        assert result.requests[3].url.endswith("/integrations/int-teams/channels?connection_id=conn-3")
        assert "x-as-user" not in result.requests[0].headers
        assert result.requests[2].headers["x-as-user"] == "user-1"
        assert result.items == [
            [
                {
                    "id": "C1",
                    "name": "general",
                    "type": "channel",
                    "user_id": "user-1",
                    "connection_id": "conn-1",
                    "integration_id": "int-slack",
                    "selected": False,
                },
                {
                    "id": "C2",
                    "name": "random",
                    "user_id": "user-1",
                    "connection_id": "conn-1",
                    "integration_id": "int-slack",
                    "selected": True,
                },
            ]
        ]

    def test_connection_folders_walk_tree_of_folder_capable_connections(self) -> None:
        result = _driver(user_ids="user-1").run(
            "connection_folders",
            [
                _page(
                    {
                        "integrations": [
                            {"id": "int-drive", "supports_folder_selection": True},
                            {"id": "int-slack", "supports_folder_selection": False},
                        ]
                    }
                ),
                _page(
                    {
                        "connections": [
                            {"id": "conn-slack", "integration_id": "int-slack"},
                            {"id": "conn-drive", "integration_id": "int-drive"},
                        ]
                    }
                ),
                _page(
                    {
                        "folders": [
                            {"provider_folder_id": "F1", "name": "Projects", "has_children": True},
                            {"provider_folder_id": "F2", "name": "Archive", "has_children": False},
                        ]
                    }
                ),
                _page(
                    {
                        "folders": [
                            {
                                "provider_folder_id": "F3",
                                "name": "Alpha",
                                "parent_folder_id": "F1",
                                "has_children": False,
                                "policy": {"id": "pol-1", "sync_mode": "skip"},
                            },
                            # Already listed under the root; a second parent must not duplicate the row.
                            {"provider_folder_id": "F2", "name": "Archive", "has_children": False},
                        ]
                    }
                ),
            ],
        )

        assert result.raised is None
        assert len(result.requests) == 4
        assert result.requests[2].url.endswith("/connections/conn-drive/folders")
        assert result.requests[3].url.endswith("/connections/conn-drive/folders?parent_id=F1")
        assert result.requests[3].headers["x-as-user"] == "user-1"
        assert [[row["provider_folder_id"] for row in batch] for batch in result.items] == [["F1", "F2"], ["F3"]]
        assert result.items[1][0] == {
            "provider_folder_id": "F3",
            "name": "Alpha",
            "parent_folder_id": "F1",
            "has_children": False,
            "policy": {"id": "pol-1", "sync_mode": "skip"},
            "user_id": "user-1",
            "connection_id": "conn-drive",
            "integration_id": "int-drive",
        }

    def test_connection_folders_walk_stops_at_request_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hyperspell, "MAX_FOLDER_REQUESTS_PER_CONNECTION", 2)

        result = _driver().run(
            "connection_folders",
            [
                _page({"integrations": [{"id": "int-drive", "folder_selection_required": True}]}),
                _page({"connections": [{"id": "conn-drive", "integration_id": "int-drive"}]}),
                _page({"folders": [{"provider_folder_id": "F1", "has_children": True}]}),
                _page({"folders": [{"provider_folder_id": "F2", "has_children": True}]}),
            ],
        )

        assert result.raised is None
        assert len(result.requests) == 4
        assert [[row["provider_folder_id"] for row in batch] for batch in result.items] == [["F1"], ["F2"]]

    def test_emotional_states_reads_bare_array_per_user(self) -> None:
        result = _driver(user_ids="user-1, user-2").run(
            "emotional_states",
            [
                _page(
                    [
                        {
                            "resource_id": "es-2",
                            "summary": "calm",
                            "extracted_at": "2026-01-02T00:00:00Z",
                            "session_id": None,
                            "relationship_id": None,
                        }
                    ]
                ),
                _page([]),
            ],
        )

        assert result.raised is None
        assert [request.headers["x-as-user"] for request in result.requests] == ["user-1", "user-2"]
        assert result.params("limit") == ["20", "20"]
        assert result.items == [
            [
                {
                    "resource_id": "es-2",
                    "summary": "calm",
                    "extracted_at": "2026-01-02T00:00:00Z",
                    "session_id": None,
                    "relationship_id": None,
                    "user_id": "user-1",
                }
            ]
        ]


class TestHyperspellSource:
    def test_entities_response_has_datetime_partition(self) -> None:
        result = _driver().run("entities", [_page({"items": []})])

        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["created_at"]
