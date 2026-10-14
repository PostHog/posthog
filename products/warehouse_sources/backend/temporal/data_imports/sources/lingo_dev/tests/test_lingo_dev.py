import dataclasses
from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized
from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lingodev import (
    LingoDevSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lingo_dev.lingo_dev import (
    LingoDevPaginator,
    LingoDevResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lingo_dev.source import LingoDevSource


class TestLingoDevPaginator:
    @parameterized.expand(
        [
            ("more_pages", {"items": [{"id": "ljb_1"}], "nextCursor": "cur_2"}, True),
            ("last_page_null_cursor", {"items": [{"id": "ljb_1"}], "nextCursor": None}, False),
            ("missing_cursor_key", {"items": []}, False),
        ]
    )
    def test_update_state(self, label: str, response_body: Any, has_next: bool) -> None:
        paginator = LingoDevPaginator()
        response = MagicMock()
        response.json.return_value = response_body

        paginator.update_state(response)

        assert paginator.has_next_page is has_next

    @parameterized.expand(
        [
            ("fresh_run_omits_cursor", None, None),
            ("resumed_sets_cursor", "cur_42", "cur_42"),
        ]
    )
    def test_init_request(self, label: str, seeded_cursor: str | None, expected_cursor_param: str | None) -> None:
        paginator = LingoDevPaginator()
        if seeded_cursor is not None:
            paginator.set_resume_state({"cursor": seeded_cursor})

        request = Request(method="GET", url="https://api.lingo.dev/jobs/localization", params={"limit": 100})
        paginator.init_request(request)

        if expected_cursor_param is None:
            assert "cursor" not in (request.params or {})
        else:
            assert request.params["cursor"] == expected_cursor_param

    def test_set_resume_state_ignores_missing_cursor(self) -> None:
        paginator = LingoDevPaginator()
        paginator.set_resume_state({})

        assert paginator.get_resume_state() is None


def _page(ids: list[str], next_cursor: str | None) -> dict[str, Any]:
    return {
        "items": [
            {"id": i, "groupId": "ljg_1", "targetLocale": "ja", "status": "completed", "createdAt": "2026-01-01"}
            for i in ids
        ],
        "nextCursor": next_cursor,
    }


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid_key", ScriptedResponse(json=_page(["ljb_1"], None)), True, None),
            (
                "invalid_key_json_message",
                ScriptedResponse(status=401, json={"_tag": "UnauthorizedError", "message": "Invalid API key"}),
                False,
                "Invalid API key",
            ),
        ]
    )
    def test_status_mapping(
        self,
        label: str,
        response: ScriptedResponse,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network([response]) as network:
            is_valid, message = validate_credentials("test-key")

        assert is_valid is expected_valid
        assert message == expected_message
        assert network.requests_log[0].path == "/jobs/localization"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["x-api-key"] == "test-key"

    def test_network_error_returns_error_message(self) -> None:
        with scripted_network(always(ConnectionResetError("connection refused"))) as network:
            is_valid, message = validate_credentials("test-key")

        assert is_valid is False
        assert message is not None and "connection refused" in message
        assert {request.path for request in network.requests_log} == {"/jobs/localization"}


class TestLingoDevSourceResumeBehavior:
    """End-to-end resume behaviour through the shared ``rest_api_resource`` path."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(LingoDevSource(), LingoDevSourceConfig(api_key="test-key"))

    def test_fresh_run_saves_cursor_after_each_non_terminal_page(self) -> None:
        result = self._driver().run(
            "jobs",
            [
                ScriptedResponse(json=_page(["ljb_1", "ljb_2"], "cur_2")),
                ScriptedResponse(json=_page(["ljb_3"], "cur_3")),
                ScriptedResponse(json=_page(["ljb_4"], None)),
            ],
        )

        # First request omits the cursor (fresh run); subsequent requests carry the
        # cursor from the previous response — a paginator that re-sends the same
        # cursor would loop on one page forever.
        assert result.raised is None
        assert result.params("cursor") == [None, "cur_2", "cur_3"]
        assert [row["id"] for row in result.rows] == ["ljb_1", "ljb_2", "ljb_3", "ljb_4"]
        assert result.saved_states == [
            LingoDevResumeConfig(cursor="cur_2"),
            LingoDevResumeConfig(cursor="cur_3"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._driver().run(
            "jobs",
            [ScriptedResponse(json=_page(["ljb_4"], None))],
            resume_state=LingoDevResumeConfig(cursor="cur_3"),
        )

        # The very first request goes out at the resumed cursor — no cursor-less
        # call that would re-fetch the already-synced pages.
        assert result.raised is None
        assert result.params("cursor") == ["cur_3"]

    def test_resume_config_serialization_round_trip(self) -> None:
        cfg = LingoDevResumeConfig(cursor="cur_42")

        as_dict = dataclasses.asdict(cfg)
        restored = LingoDevResumeConfig(**as_dict)

        assert restored == cfg
