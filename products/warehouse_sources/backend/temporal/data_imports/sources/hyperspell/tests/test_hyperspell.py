import json
from typing import Any, Optional

import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.hyperspell import (
    HyperspellResumeConfig,
    get_rows,
    hyperspell_source,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.hyperspell"


def _response(status: int = 200, body: Optional[dict[str, Any]] = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    return resp


class _StubManager:
    """Minimal stand-in for ResumableSourceManager that records saved state."""

    def __init__(self, resume_state: Optional[HyperspellResumeConfig] = None) -> None:
        self._resume_state = resume_state
        self.saved: list[HyperspellResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_state is not None

    def load_state(self) -> Optional[HyperspellResumeConfig]:
        return self._resume_state

    def save_state(self, data: HyperspellResumeConfig) -> None:
        self.saved.append(data)

    def safe_point(self) -> None:
        pass


def _run(
    manager: _StubManager,
    pages: list[dict[str, Any]],
    endpoint: str = "memories",
    user_ids: str | None = None,
    region: str | None = "us",
) -> tuple[list[list[dict[str, Any]]], mock.MagicMock]:
    with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
        mock_session.return_value.get.side_effect = [_response(200, page) for page in pages]
        batches = list(
            get_rows(
                api_key="hs_test",
                region=region,
                user_ids=user_ids,
                endpoint=endpoint,
                logger=structlog.get_logger(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
        )
        return batches, mock_session.return_value.get


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
    def test_status_mapping(self, status, expected_valid) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(status)

            is_valid, _ = validate_credentials("hs_test", "us")

        assert is_valid is expected_valid

    def test_network_error_is_invalid(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")

            is_valid, message = validate_credentials("hs_test", "us")

        assert is_valid is False
        assert message is not None


class TestGetRows:
    def test_paginates_and_yields_each_page(self) -> None:
        manager = _StubManager()
        pages: list[dict[str, Any]] = [
            {"items": [{"resource_id": "r1", "source": "slack"}], "next_cursor": "c1"},
            {"items": [{"resource_id": "r2", "source": "slack"}], "next_cursor": None},
        ]

        batches, mock_get = _run(manager, pages)

        assert [[row["resource_id"] for row in batch] for batch in batches] == [["r1"], ["r2"]]
        second_url = mock_get.call_args_list[1][0][0]
        assert "cursor=c1" in second_url

    def test_bookmarked_user_removed_from_config_restarts_from_first_user(self) -> None:
        manager = _StubManager(resume_state=HyperspellResumeConfig(cursor="c5", user_id="user-gone"))
        pages: list[dict[str, Any]] = [
            {"items": [], "next_cursor": None},
            {"items": [], "next_cursor": None},
        ]

        _, mock_get = _run(manager, pages, user_ids="user-1, user-2")

        assert mock_get.call_count == 2
        first_url = mock_get.call_args_list[0][0][0]
        assert "cursor" not in first_url

    def test_app_level_endpoint_does_not_fan_out_or_stamp_user_id(self) -> None:
        manager = _StubManager()
        pages: list[dict[str, Any]] = [{"integrations": [{"id": "int-1"}]}]

        batches, mock_get = _run(manager, pages, endpoint="integrations", user_ids="user-1, user-2")

        assert mock_get.call_count == 1
        assert "X-As-User" not in mock_get.call_args[1]["headers"]
        assert "user_id" not in batches[0][0]

    def test_vaults_null_collection_becomes_empty_string(self) -> None:
        manager = _StubManager()
        pages: list[dict[str, Any]] = [{"items": [{"collection": None, "document_count": 3}], "next_cursor": None}]

        batches, _ = _run(manager, pages, endpoint="vaults")

        assert batches[0][0]["collection"] == ""

    def test_users_offset_pagination_stops_at_total(self) -> None:
        manager = _StubManager()
        pages: list[dict[str, Any]] = [
            {"users": [{"user_id": "u1"}, {"user_id": "u2"}], "total": 3, "limit": 2, "offset": 0},
            {"users": [{"user_id": "u3"}], "total": 3, "limit": 2, "offset": 2},
        ]

        batches, mock_get = _run(manager, pages, endpoint="users", user_ids="user-1, user-2")

        assert [[row["user_id"] for row in batch] for batch in batches] == [["u1", "u2"], ["u3"]]
        urls = [call[0][0] for call in mock_get.call_args_list]
        assert "offset=0" in urls[0]
        assert "offset=2" in urls[1]
        # Listing users needs an app-scoped credential, so configured user IDs must not fan it out.
        assert all("X-As-User" not in call[1]["headers"] for call in mock_get.call_args_list)
        assert manager.saved == [HyperspellResumeConfig(cursor="2", user_id=None)]

    def test_resumes_users_from_saved_offset(self) -> None:
        manager = _StubManager(resume_state=HyperspellResumeConfig(cursor="400", user_id=None))
        pages: list[dict[str, Any]] = [{"users": [{"user_id": "u401"}], "total": 401}]

        _, mock_get = _run(manager, pages, endpoint="users")

        assert mock_get.call_count == 1
        assert "offset=400" in mock_get.call_args[0][0]

    def test_integration_channels_fan_out_over_channel_capable_connections(self) -> None:
        manager = _StubManager()
        pages: list[dict[str, Any]] = [
            {
                "integrations": [
                    {"id": "int-slack", "supports_channel_selection": True},
                    {"id": "int-drive", "supports_channel_selection": False},
                    {"id": "int-teams", "requires_channel_selection": True},
                ]
            },
            {
                "connections": [
                    {"id": "conn-1", "integration_id": "int-slack"},
                    {"id": "conn-2", "integration_id": "int-drive"},
                    {"id": "conn-3", "integration_id": "int-teams"},
                ]
            },
            {
                "channels": [{"id": "C1", "name": "general", "type": "channel"}, {"id": "C2", "name": "random"}],
                "selected": ["C2"],
            },
            {"channels": [], "selected": [], "pending": True},
        ]

        batches, mock_get = _run(manager, pages, endpoint="integration_channels", user_ids="user-1")

        urls = [call[0][0] for call in mock_get.call_args_list]
        assert urls[2].endswith("/integrations/int-slack/channels?connection_id=conn-1")
        assert urls[3].endswith("/integrations/int-teams/channels?connection_id=conn-3")
        assert "X-As-User" not in mock_get.call_args_list[0][1]["headers"]
        assert mock_get.call_args_list[2][1]["headers"]["X-As-User"] == "user-1"
        assert batches == [
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


class TestHyperspellSource:
    def test_entities_response_has_datetime_partition(self) -> None:
        response = hyperspell_source(
            api_key="hs_test",
            region="us",
            user_ids=None,
            endpoint="entities",
            logger=structlog.get_logger(),
            resumable_source_manager=mock.MagicMock(),
        )

        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
