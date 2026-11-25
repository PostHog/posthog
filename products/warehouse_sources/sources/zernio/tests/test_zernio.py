from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network
from products.warehouse_sources.sources.zernio._config import ZernioSourceConfig
from products.warehouse_sources.sources.zernio.source import ZernioSource
from products.warehouse_sources.sources.zernio.zernio import ZernioResumeConfig, validate_credentials


def _driver() -> SourceDriver:
    return SourceDriver(ZernioSource(), ZernioSourceConfig(api_key="sk_test"))


def _cursor_page(key: str, rows: list[dict[str, Any]], next_cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(
        json={key: rows, "pagination": {"hasMore": next_cursor is not None, "nextCursor": next_cursor}}
    )


class TestZernioPagination:
    @pytest.mark.parametrize(
        "endpoint,key,id_field",
        [
            ("accounts", "accounts", "_id"),
            ("posts", "posts", "_id"),
            ("inbox_conversations", "data", "id"),
        ],
    )
    def test_cursor_tables_follow_next_cursor_and_save_it_before_each_next_page(
        self, endpoint: str, key: str, id_field: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _cursor_page(key, [{id_field: "a"}], "c1"),
                _cursor_page(key, [{id_field: "b"}], "c2"),
                _cursor_page(key, [{id_field: "c"}], None),
            ],
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert result.paths[0].startswith("/api/v1/")
        assert result.params("cursor") == [None, "c1", "c2"]
        assert result.params("limit") == ["100", "100", "100"]
        assert [row[id_field] for row in result.rows] == ["a", "b", "c"]
        assert result.saved_states == [
            ZernioResumeConfig(paginator_state={"cursor": "c1"}),
            ZernioResumeConfig(paginator_state={"cursor": "c2"}),
        ]

    @pytest.mark.parametrize(
        "endpoint,page_size,body",
        [
            ("profiles", 100, lambda rows, total: {"profiles": rows, "total": total, "skip": 0}),
            ("contacts", 100, lambda rows, total: {"contacts": rows, "pagination": {"total": total}}),
            ("broadcasts", 50, lambda rows, total: {"broadcasts": rows, "pagination": {"total": total}}),
        ],
    )
    def test_skip_tables_step_by_the_page_size_and_stop_at_the_total(
        self, endpoint: str, page_size: int, body: Callable[[list[dict[str, Any]], int], dict[str, Any]]
    ) -> None:
        id_field = "_id" if endpoint == "profiles" else "id"
        first = [{id_field: str(index)} for index in range(page_size)]
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json=body(first, page_size + 1)),
                ScriptedResponse(json=body([{id_field: "last"}], page_size + 1)),
            ],
        )

        assert result.raised is None
        assert result.params("skip") == ["0", str(page_size)]
        assert result.params("limit") == [str(page_size), str(page_size)]
        assert len(result.rows) == page_size + 1
        assert result.rows[-1][id_field] == "last"

    def test_ads_read_every_page_up_to_the_page_count(self) -> None:
        result = _driver().run(
            "ads",
            [
                ScriptedResponse(json={"ads": [{"_id": "a"}], "pagination": {"page": 1, "pages": 2}}),
                ScriptedResponse(json={"ads": [{"_id": "b"}], "pagination": {"page": 2, "pages": 2}}),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2"]
        assert result.params("source") == ["all", "all"]
        assert [row["_id"] for row in result.rows] == ["a", "b"]

    def test_a_body_without_the_row_key_fails_instead_of_syncing_nothing(self) -> None:
        result = _driver().run("users", [ScriptedResponse(json={"error": "unexpected"})])

        assert result.raised is not None
        assert result.rows == []


class TestZernioIncremental:
    @pytest.mark.parametrize(
        "endpoint,key,should_use_incremental_field,last_value,expected",
        [
            ("posts", "posts", True, datetime(2026, 11, 1, 8, 30, 15, 123456, tzinfo=UTC), "2026-11-01T08:30:15.123Z"),
            ("posts", "posts", True, None, None),
            ("posts", "posts", False, None, None),
            (
                "inbox_conversations",
                "data",
                True,
                datetime(2026, 11, 1, 8, 30, tzinfo=UTC),
                "2026-11-01T08:30:00.000Z",
            ),
            # The conversation change feed always reads from Zernio's store, from the epoch on a full read.
            ("inbox_conversations", "data", True, None, "1970-01-01T00:00:00Z"),
            ("inbox_conversations", "data", False, None, "1970-01-01T00:00:00Z"),
        ],
    )
    def test_updated_since_carries_the_watermark_only_on_an_incremental_read(
        self,
        endpoint: str,
        key: str,
        should_use_incremental_field: bool,
        last_value: datetime | None,
        expected: str | None,
    ) -> None:
        result = _driver().run(
            endpoint,
            [_cursor_page(key, [{"_id": "a", "id": "a"}], None)],
            incremental_field="updatedAt",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.params("updatedSince") == [expected]

    def test_posts_walk_in_creation_order_so_the_cursor_stays_stable(self) -> None:
        result = _driver().run(
            "posts",
            [_cursor_page("posts", [{"_id": "a"}], None)],
            incremental_field="updatedAt",
            db_incremental_field_last_value=datetime(2026, 11, 1, tzinfo=UTC),
        )

        assert result.params("sortBy") == ["created-asc"]
        assert result.response is not None
        assert result.response.sort_mode is None


class TestZernioResume:
    @pytest.mark.parametrize(
        "endpoint,state,param,expected",
        [
            ("posts", {"cursor": "saved"}, "cursor", "saved"),
            ("contacts", {"offset": 200}, "skip", "200"),
            ("ads", {"page": 3}, "page", "3"),
        ],
    )
    def test_resume_starts_from_the_saved_paginator_state(
        self, endpoint: str, state: dict[str, Any], param: str, expected: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={endpoint: [{"_id": "z", "id": "z"}], "pagination": {"total": 0, "pages": 3}})],
            resume_state=ZernioResumeConfig(paginator_state=state),
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert result.params(param) == [expected]
        assert len(result.rows) == 1


class TestZernioValidateCredentials:
    @pytest.mark.parametrize(
        "status,body,expected",
        [
            (200, {"valid": True}, (True, None)),
            (
                401,
                {"error": "Invalid API key", "type": "authentication_error", "code": "invalid_credentials"},
                (
                    False,
                    "Zernio didn't accept this API key. Create a new key on the API keys page of the Zernio dashboard.",
                ),
            ),
            (
                503,
                {"error": "Service unavailable", "type": "api_error"},
                (False, "The Zernio API returned an unexpected status code (503). Try again in a few minutes."),
            ),
        ],
    )
    def test_maps_the_verify_response_to_a_message(
        self, status: int, body: dict[str, Any], expected: tuple[bool, str | None]
    ) -> None:
        answer = ScriptedResponse(status=status, json=body)
        # The tracked session retries a 5xx, so a server error answers every attempt.
        with scripted_network(always(answer) if status >= 500 else [answer]) as network:
            assert validate_credentials("sk_test", "v1") == expected

        request = network.requests_log[0]
        assert request.url == "https://zernio.com/api/v1/auth/verify"
        assert request.headers["authorization"] == "Bearer sk_test"
