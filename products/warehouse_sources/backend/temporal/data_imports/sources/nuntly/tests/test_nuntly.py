from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nuntly import NuntlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.nuntly import (
    NuntlyResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.source import NuntlySource


class TestNuntlySourceResumeBehavior:
    """End-to-end cursor pagination + resume behaviour of ``NuntlySource``."""

    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(NuntlySource(), NuntlySourceConfig(api_key="apk_test"))

    @staticmethod
    def _page(rows: list[dict[str, Any]], next_cursor: str | None) -> ScriptedResponse:
        return ScriptedResponse(json={"data": rows, "nextCursor": next_cursor})

    @parameterized.expand(
        [("Emails",), ("Messages",), ("Inboxes",), ("Domains",), ("Webhooks",), ("Namespaces",), ("Contacts",)]
    )
    def test_fresh_run_walks_pages_and_saves_cursor_after_each_non_terminal_page(self, endpoint: str) -> None:
        result = self._driver().run(
            endpoint,
            [
                self._page([{"id": "1"}], "cursor-1"),
                self._page([{"id": "2"}], "cursor-2"),
                self._page([{"id": "3"}], None),
            ],
        )

        assert result.raised is None
        assert result.params("cursor") == [None, "cursor-1", "cursor-2"]
        assert result.params("limit") == ["30", "30", "30"]
        assert all(url.startswith(f"https://api.nuntly.com{ENDPOINTS[endpoint].path}") for url in result.urls)
        assert result.saved_states == [
            NuntlyResumeConfig(cursor="cursor-1"),
            NuntlyResumeConfig(cursor="cursor-2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        result = self._driver().run(
            "Emails",
            [self._page([{"id": "4"}], None)],
            resume_state=NuntlyResumeConfig(cursor="cursor-resumed"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["cursor-resumed"]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        result = self._driver().run("Emails", [self._page([{"id": "a"}], None)])

        assert result.raised is None
        assert result.params("cursor") == [None]

    @parameterized.expand([("Emails",), ("Messages",), ("Inboxes",), ("Domains",), ("Webhooks",)])
    def test_source_response_uses_declared_primary_keys_and_partitioning(self, endpoint: str) -> None:
        result = self._driver().run(endpoint, [self._page([], None)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_mode == "datetime"
        assert result.response.partition_keys == ["createdAt"]


class TestNuntlyFanout:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(NuntlySource(), NuntlySourceConfig(api_key="apk_test"))

    @staticmethod
    def _page(rows: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
        return ScriptedResponse(json={"data": rows, "nextCursor": next_cursor})

    def test_threads_walk_every_inbox_page_and_thread_page(self) -> None:
        result = self._driver().run(
            "Threads",
            [
                self._page([{"id": "ibx_1"}], "inbox-cursor"),
                self._page([{"id": "thr_1", "inboxId": "ibx_1"}], "thread-cursor"),
                self._page([{"id": "thr_2", "inboxId": "ibx_1"}]),
                self._page([{"id": "ibx_2"}]),
                self._page([{"id": "thr_3", "inboxId": "ibx_2"}]),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/inboxes",
            "/inboxes/ibx_1/threads",
            "/inboxes/ibx_1/threads",
            "/inboxes",
            "/inboxes/ibx_2/threads",
        ]
        assert result.params("cursor") == [None, None, "thread-cursor", "inbox-cursor", None]
        assert result.params("limit") == ["30"] * 5
        assert [(row["inboxId"], row["id"]) for row in result.rows] == [
            ("ibx_1", "thr_1"),
            ("ibx_1", "thr_2"),
            ("ibx_2", "thr_3"),
        ]
        assert result.saved_states and all(
            state.fanout_state is not None and state.cursor is None for state in result.saved_states
        )
        assert result.response is not None and result.response.supports_resume is True

    def test_email_events_fetch_one_unpaginated_page_per_email_and_skip_missing_emails(self) -> None:
        result = self._driver().run(
            "EmailEvents",
            [
                self._page([{"id": "em_1"}, {"id": "em_gone"}, {"id": "em_2"}]),
                # Not paginated: a stray `nextCursor` must not trigger a second request.
                self._page([{"id": "evt_1", "emailId": "em_1"}], "ignored"),
                ScriptedResponse(status=404, json={"error": {"status": 404, "code": "not_found", "title": "x"}}),
                ScriptedResponse(json={"data": [{"id": "evt_2", "emailId": "em_2"}]}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/emails", "/emails/em_1/events", "/emails/em_gone/events", "/emails/em_2/events"]
        assert result.params("limit") == ["30", None, None, None]
        assert [(row["emailId"], row["id"]) for row in result.rows] == [("em_1", "evt_1"), ("em_2", "evt_2")]
        assert result.saved_states == []
        assert result.response is not None and result.response.supports_resume is False

    def test_fanout_resume_skips_inboxes_whose_threads_already_synced(self) -> None:
        first = self._driver().run(
            "Threads",
            [
                self._page([{"id": "ibx_1"}, {"id": "ibx_2"}]),
                self._page([{"id": "thr_1", "inboxId": "ibx_1"}]),
                self._page([{"id": "thr_2", "inboxId": "ibx_2"}]),
            ],
        )

        resumed = self._driver().run(
            "Threads",
            [
                self._page([{"id": "ibx_1"}, {"id": "ibx_2"}]),
                self._page([{"id": "thr_2", "inboxId": "ibx_2"}]),
            ],
            resume_state=first.saved_states[0],
        )

        assert resumed.raised is None
        assert resumed.paths == ["/inboxes", "/inboxes/ibx_2/threads"]
        assert [row["id"] for row in resumed.rows] == ["thr_2"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
        ]
    )
    def test_status_mapping(self, status_code: int, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            is_valid, code = validate_credentials("apk_test")

        assert (is_valid, code) == (expected_valid, status_code)
        assert network.requests_log[0].path == "/emails"
