from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur import mailosaur
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.mailosaur import (
    MailosaurResumeConfig,
    _extract_items,
    _format_received_after,
    get_rows,
    mailosaur_source,
    validate_credentials,
)


class _FakeManager:
    """In-memory stand-in for ResumableSourceManager so we can assert save/resume behavior."""

    def __init__(self, state: MailosaurResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[MailosaurResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> MailosaurResumeConfig | None:
        return self._state

    def save_state(self, data: MailosaurResumeConfig) -> None:
        self.saved.append(data)
        self._state = data


def _drain(iterator: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch in iterator:
        rows.extend(batch)
    return rows


class TestExtractItems:
    @parameterized.expand(
        [
            ("wrapped", {"items": [{"id": "a"}, {"id": "b"}]}, [{"id": "a"}, {"id": "b"}]),
            ("bare_list", [{"id": "a"}], [{"id": "a"}]),
            ("empty_wrapped", {"items": []}, []),
            ("missing_items", {"foo": 1}, []),
            ("none", None, []),
        ]
    )
    def test_extract_items(self, _name: str, payload: Any, expected: list[dict[str, Any]]) -> None:
        # Mailosaur wraps list results as {"items": [...]}; the bare-list branch guards an
        # unwrapped response so a shape change doesn't silently sync zero rows.
        assert _extract_items(payload) == expected


class TestFormatReceivedAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("none", None, None),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_received_after(value) == expected

    @parameterized.expand([("int_epoch", 1234567890), ("string", "not-a-date")])
    def test_unexpected_type_raises(self, _name: str, value: Any) -> None:
        # The messages cursor is a DateTime; an int/str would produce a receivedAfter Mailosaur
        # silently ignores (a full re-fetch), so we fail loud instead.
        with pytest.raises(TypeError):
            _format_received_after(value)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.mailosaur.make_tracked_session"
        ) as session_factory:
            session_factory.return_value.get.return_value = response
            ok, error = validate_credentials("key")
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestMessagesFanOut:
    def _run(
        self,
        fetch_side_effect: Any,
        manager: _FakeManager,
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict[str, Any]], MagicMock]:
        with (
            patch.object(mailosaur, "make_tracked_session"),
            patch.object(mailosaur, "_fetch", side_effect=fetch_side_effect) as fetch,
        ):
            rows = _drain(
                get_rows(
                    api_key="key",
                    endpoint="messages",
                    logger=MagicMock(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                    should_use_incremental_field=should_use_incremental_field,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
            )
        return rows, fetch

    def test_injects_server_and_fans_out_over_servers(self) -> None:
        def fetch(session: Any, api_key: str, path: str, logger: Any, params: Any = None) -> Any:
            if path == "/api/servers":
                return {"items": [{"id": "s1"}, {"id": "s2"}]}
            return {"items": [{"id": f"m-{params['server']}"}]}

        rows, _ = self._run(fetch, _FakeManager())
        # Every message row must carry its parent server id — that's half of the (server, id)
        # primary key, and the summary payload omits it.
        assert rows == [
            {"id": "m-s1", "server": "s1"},
            {"id": "m-s2", "server": "s2"},
        ]

    def test_paginates_until_short_page_and_saves_state_after_each_page(self) -> None:
        # One server, two pages: a full page continues, a short page terminates.
        with patch.object(mailosaur, "MESSAGES_PAGE_SIZE", 2):

            def fetch(session: Any, api_key: str, path: str, logger: Any, params: Any = None) -> Any:
                if path == "/api/servers":
                    return {"items": [{"id": "s1"}]}
                if params["page"] == 0:
                    return {"items": [{"id": "a"}, {"id": "b"}]}
                return {"items": [{"id": "c"}]}

            manager = _FakeManager()
            rows, _ = self._run(fetch, manager)

        assert [r["id"] for r in rows] == ["a", "b", "c"]
        # State is saved AFTER yielding the first (full) page, bookmarking the next page to fetch,
        # so a crash re-yields rather than skips (merge dedupes on the primary key).
        assert MailosaurResumeConfig(server_id="s1", page=1) in manager.saved

    def test_resumes_from_saved_server_bookmark(self) -> None:
        seen_servers: list[str] = []

        def fetch(session: Any, api_key: str, path: str, logger: Any, params: Any = None) -> Any:
            if path == "/api/servers":
                return {"items": [{"id": "s1"}, {"id": "s2"}]}
            seen_servers.append(params["server"])
            return {"items": [{"id": f"m-{params['server']}"}]}

        # Bookmarked at s2 — s1 was already synced, so the resumed run must skip it.
        manager = _FakeManager(MailosaurResumeConfig(server_id="s2", page=0))
        rows, _ = self._run(fetch, manager)
        assert seen_servers == ["s2"]
        assert [r["id"] for r in rows] == ["m-s2"]

    def test_incremental_passes_received_after(self) -> None:
        captured: dict[str, Any] = {}

        def fetch(session: Any, api_key: str, path: str, logger: Any, params: Any = None) -> Any:
            if path == "/api/servers":
                return {"items": [{"id": "s1"}]}
            captured.update(params)
            return {"items": []}

        self._run(
            fetch,
            _FakeManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
        assert captured.get("receivedAfter") == "2026-01-02T03:04:05Z"

    def test_no_received_after_on_full_refresh(self) -> None:
        captured: dict[str, Any] = {}

        def fetch(session: Any, api_key: str, path: str, logger: Any, params: Any = None) -> Any:
            if path == "/api/servers":
                return {"items": [{"id": "s1"}]}
            captured.update(params)
            return {"items": []}

        self._run(fetch, _FakeManager(), should_use_incremental_field=False)
        assert "receivedAfter" not in captured


class TestSimpleEndpoints:
    @parameterized.expand([("servers", "/api/servers"), ("usage_transactions", "/api/usage/transactions")])
    def test_single_request_yields_items(self, endpoint: str, expected_path: str) -> None:
        def fetch(session: Any, api_key: str, path: str, logger: Any, params: Any = None) -> Any:
            assert path == expected_path
            return {"items": [{"id": "x"}]}

        with (
            patch.object(mailosaur, "make_tracked_session"),
            patch.object(mailosaur, "_fetch", side_effect=fetch),
        ):
            rows = _drain(
                get_rows(
                    api_key="key",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=_FakeManager(),  # type: ignore[arg-type]
                )
            )
        assert rows == [{"id": "x"}]


class TestMailosaurSourceResponse:
    @parameterized.expand(
        [
            ("messages", ["server", "id"], "desc", ["received"]),
            ("servers", ["id"], "asc", None),
            ("usage_transactions", ["timestamp"], "asc", None),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], sort_mode: str, partition_keys: list[str] | None
    ) -> None:
        response = mailosaur_source(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeManager(),  # type: ignore[arg-type]
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        # sort_mode must match the real arrival order — messages come newest-first (desc), and a
        # wrong value corrupts the incremental watermark checkpoint.
        assert response.sort_mode == sort_mode
        assert response.partition_keys == partition_keys
