import json
from typing import Any, Optional

import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.hyperspell import (
    HYPERSPELL_BASE_URLS,
    HyperspellResumeConfig,
    get_base_url,
    get_rows,
    hyperspell_source,
    parse_user_ids,
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


class TestSessionPrivacy:
    def test_validate_credentials_disables_sample_capture(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200)

            validate_credentials("hs_test", "us")

        assert mock_session.call_args.kwargs["capture"] is False

    def test_get_rows_disables_sample_capture(self) -> None:
        manager = _StubManager()
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200, {"items": [], "next_cursor": None})

            list(
                get_rows(
                    api_key="hs_test",
                    region="us",
                    user_ids=None,
                    endpoint="memories",
                    logger=structlog.get_logger(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                )
            )

        # Imported memory content is user-authored (Gmail, Slack, Notion, ...) and lives outside
        # the warehouse tables' access controls, so it must never reach HTTP sample storage.
        assert mock_session.call_args.kwargs["capture"] is False


class TestGetBaseUrl:
    @pytest.mark.parametrize(
        "region, expected",
        [
            ("us", HYPERSPELL_BASE_URLS["us"]),
            ("eu", HYPERSPELL_BASE_URLS["eu"]),
            ("EU", HYPERSPELL_BASE_URLS["eu"]),
            (" eu ", HYPERSPELL_BASE_URLS["eu"]),
            (None, HYPERSPELL_BASE_URLS["us"]),
            ("", HYPERSPELL_BASE_URLS["us"]),
            ("unknown", HYPERSPELL_BASE_URLS["us"]),
        ],
    )
    def test_region_maps_to_base_url(self, region, expected) -> None:
        assert get_base_url(region) == expected


class TestParseUserIds:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, []),
            ("", []),
            ("  ,  ", []),
            ("user-1", ["user-1"]),
            ("user-1, user-2", ["user-1", "user-2"]),
            ("user-1,user-1,user-2", ["user-1", "user-2"]),
            ("user-1\nuser-2", ["user-1", "user-2"]),
        ],
    )
    def test_parses_and_dedupes(self, raw, expected) -> None:
        assert parse_user_ids(raw) == expected


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

    def test_probes_selected_region(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _response(200)

            validate_credentials("hs_test", "eu")

            called_url = mock_session.return_value.get.call_args[0][0]

        assert called_url.startswith(HYPERSPELL_BASE_URLS["eu"])


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

    def test_saves_state_after_yielding_only_when_more_pages(self) -> None:
        manager = _StubManager()
        pages: list[dict[str, Any]] = [
            {"items": [{"resource_id": "r1", "source": "slack"}], "next_cursor": "c1"},
            {"items": [{"resource_id": "r2", "source": "slack"}], "next_cursor": None},
        ]

        _run(manager, pages)

        assert len(manager.saved) == 1
        assert manager.saved[0].cursor == "c1"

    def test_resumes_from_saved_cursor(self) -> None:
        manager = _StubManager(resume_state=HyperspellResumeConfig(cursor="resume_token", user_id=None))
        pages: list[dict[str, Any]] = [{"items": [{"resource_id": "r9", "source": "slack"}], "next_cursor": None}]

        _, mock_get = _run(manager, pages)

        assert "cursor=resume_token" in mock_get.call_args[0][0]

    def test_app_scope_stamps_empty_user_id_and_sends_no_header(self) -> None:
        manager = _StubManager()
        pages: list[dict[str, Any]] = [{"items": [{"resource_id": "r1", "source": "slack"}], "next_cursor": None}]

        batches, mock_get = _run(manager, pages)

        assert batches[0][0]["user_id"] == ""
        headers = mock_get.call_args[1]["headers"]
        assert "X-As-User" not in headers

    def test_fans_out_over_users_with_as_user_header(self) -> None:
        manager = _StubManager()
        pages: list[dict[str, Any]] = [
            {"items": [{"resource_id": "r1", "source": "slack"}], "next_cursor": None},
            {"items": [{"resource_id": "r1", "source": "slack"}], "next_cursor": None},
        ]

        batches, mock_get = _run(manager, pages, user_ids="user-1, user-2")

        assert [batch[0]["user_id"] for batch in batches] == ["user-1", "user-2"]
        headers_per_call = [call[1]["headers"].get("X-As-User") for call in mock_get.call_args_list]
        assert headers_per_call == ["user-1", "user-2"]
        # The bookmark advanced to user-2 after user-1 completed, so a crash between users
        # resumes into user-2 instead of re-fetching user-1.
        assert manager.saved[-1] == HyperspellResumeConfig(cursor=None, user_id="user-2")

    def test_resumes_into_bookmarked_user_and_skips_prior_users(self) -> None:
        manager = _StubManager(resume_state=HyperspellResumeConfig(cursor="c5", user_id="user-2"))
        pages: list[dict[str, Any]] = [{"items": [{"resource_id": "r1", "source": "slack"}], "next_cursor": None}]

        batches, mock_get = _run(manager, pages, user_ids="user-1, user-2")

        assert mock_get.call_count == 1
        assert mock_get.call_args[1]["headers"]["X-As-User"] == "user-2"
        assert "cursor=c5" in mock_get.call_args[0][0]
        assert batches[0][0]["user_id"] == "user-2"

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

    def test_non_paginated_endpoint_makes_single_request_without_page_params(self) -> None:
        manager = _StubManager()
        pages: list[dict[str, Any]] = [{"connections": [{"id": "conn-1", "integration_id": "int-1"}]}]

        batches, mock_get = _run(manager, pages, endpoint="connections")

        assert mock_get.call_count == 1
        assert "?" not in mock_get.call_args[0][0]
        assert batches[0][0]["id"] == "conn-1"
        assert manager.saved == []

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

    def test_eu_region_hits_eu_base_url(self) -> None:
        manager = _StubManager()
        pages: list[dict[str, Any]] = [{"items": [], "next_cursor": None}]

        _, mock_get = _run(manager, pages, region="eu")

        assert mock_get.call_args[0][0].startswith(HYPERSPELL_BASE_URLS["eu"])

    @pytest.mark.parametrize(
        "endpoint, page_size_param",
        [
            ("memories", "size=100"),
            ("entities", "limit=500"),
            ("users", "limit=200"),
        ],
    )
    def test_page_size_param_varies_per_endpoint(self, endpoint, page_size_param) -> None:
        manager = _StubManager()
        pages: list[dict[str, Any]] = [{"items": [], "users": [], "total": 0, "next_cursor": None}]

        _, mock_get = _run(manager, pages, endpoint=endpoint)

        assert page_size_param in mock_get.call_args[0][0]

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
    @pytest.mark.parametrize(
        "endpoint, expected_primary_keys",
        [
            ("memories", ["user_id", "source", "resource_id"]),
            ("connections", ["user_id", "id"]),
            ("integrations", ["id"]),
            ("queries", ["query_id"]),
        ],
    )
    def test_primary_keys_per_endpoint(self, endpoint, expected_primary_keys) -> None:
        response = hyperspell_source(
            api_key="hs_test",
            region="us",
            user_ids=None,
            endpoint=endpoint,
            logger=structlog.get_logger(),
            resumable_source_manager=mock.MagicMock(),
        )

        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        # Row ordering is undefined (opaque cursor, no sort param) so "asc" must never be declared.
        assert response.sort_mode == "desc"

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

    def test_memories_response_has_no_partition(self) -> None:
        response = hyperspell_source(
            api_key="hs_test",
            region="us",
            user_ids=None,
            endpoint="memories",
            logger=structlog.get_logger(),
            resumable_source_manager=mock.MagicMock(),
        )

        assert response.partition_mode is None
        assert response.partition_keys is None
