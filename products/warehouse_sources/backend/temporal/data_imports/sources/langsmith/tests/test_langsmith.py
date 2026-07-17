from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith import (
    LangSmithHostNotAllowedError,
    LangSmithResumeConfig,
    _resolve_window_start,
    get_rows,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.settings import (
    LANGSMITH_ENDPOINTS,
    RUNS_SELECT_FIELDS,
)

logger = structlog.get_logger()

BASE_URL = "https://api.smith.langchain.com"

_FETCH_PAGE = "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith._fetch_page"
_IS_HOST_SAFE = "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith._is_host_safe"
_IS_CLOUD = "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith.is_cloud"
_MAKE_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith.make_tracked_session"
)


class FakeManager:
    """Stand-in for ResumableSourceManager that records saved state and can replay a resume value."""

    def __init__(self, resume: LangSmithResumeConfig | None = None):
        self._resume = resume
        self.saved: list[LangSmithResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume is not None

    def load_state(self) -> LangSmithResumeConfig | None:
        return self._resume

    def save_state(self, data: LangSmithResumeConfig) -> None:
        self.saved.append(data)


def _collect(tables) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in tables:
        rows.extend(table.to_pylist())
    return rows


def _run(run_id: str) -> dict[str, Any]:
    return {"id": run_id, "start_time": "2026-06-01T00:00:00Z"}


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("api.smith.langchain.com", "https://api.smith.langchain.com"),
            ("https://eu.api.smith.langchain.com/", "https://eu.api.smith.langchain.com"),
            # A crafted path/query must not extend or retarget the fixed API paths.
            ("https://evil.example/api/v1/steal?x=1#f", "https://evil.example"),
            # Self-hosted instances may run plaintext on a private network; the scheme is preserved
            # (and separately blocked on cloud by _is_scheme_safe).
            ("http://langsmith.internal:1984", "http://langsmith.internal:1984"),
        ],
    )
    def test_reduces_to_clean_origin(self, raw, expected):
        assert normalize_base_url(raw) == expected


class TestResolveWindowStart:
    def test_incremental_with_watermark_subtracts_lookback(self):
        config = LANGSMITH_ENDPOINTS["runs"]
        watermark = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

        start = _resolve_window_start(
            config, should_use_incremental_field=True, db_incremental_field_last_value=watermark
        )

        lookback = config.incremental_lookback
        assert lookback is not None
        assert start == watermark - lookback

    def test_future_watermark_capped_to_now(self):
        config = LANGSMITH_ENDPOINTS["runs"]
        future = datetime.now(UTC) + timedelta(days=30)

        start = _resolve_window_start(config, should_use_incremental_field=True, db_incremental_field_last_value=future)

        # A future cursor would make the API return nothing forever; it's capped at ~now.
        assert start is not None and start <= datetime.now(UTC)

    def test_first_incremental_sync_floors_to_lookback_days(self):
        config = LANGSMITH_ENDPOINTS["runs"]

        start = _resolve_window_start(config, should_use_incremental_field=True, db_incremental_field_last_value=None)

        assert start is not None
        assert (datetime.now(UTC) - start).days == pytest.approx(config.default_lookback_days, abs=1)

    @pytest.mark.parametrize("endpoint", ["runs", "projects"])
    def test_full_refresh_sends_no_window(self, endpoint):
        config = LANGSMITH_ENDPOINTS[endpoint]

        start = _resolve_window_start(config, should_use_incremental_field=False, db_incremental_field_last_value=None)

        assert start is None


class TestRunsPagination:
    def test_cursor_walk_keeps_window_on_every_page(self):
        # If the start_time window were dropped from cursor requests, every incremental sync would
        # walk back through the full run history — an API-cost and memory bug.
        manager = FakeManager()
        watermark = datetime(2026, 6, 1, tzinfo=UTC)
        bodies: list[dict[str, Any]] = []
        pages = [
            {"runs": [_run("a")], "cursors": {"next": "c2"}},
            {"runs": [_run("b")], "cursors": {"next": None}},
        ]

        def fake_fetch(session, url, headers, log, json_body=None):
            bodies.append(json_body)
            return pages[len(bodies) - 1]

        with mock.patch(_FETCH_PAGE, side_effect=fake_fetch):
            rows = _collect(
                get_rows("key", BASE_URL, "runs", logger, manager, 1, True, watermark)  # type: ignore[arg-type]
            )

        assert [r["id"] for r in rows] == ["a", "b"]
        assert len(bodies) == 2
        assert "cursor" not in bodies[0]
        assert bodies[1]["cursor"] == "c2"
        for body in bodies:
            assert body["start_time"]  # the watermark window rides every page
            assert body["order"] == "asc"
            assert body["limit"] == 100
            assert body["select"] == RUNS_SELECT_FIELDS

    def test_terminates_on_empty_page_and_missing_cursors(self):
        manager = FakeManager()

        with mock.patch(_FETCH_PAGE, return_value={"runs": [], "cursors": {"next": "dangling"}}) as fetch:
            rows = _collect(get_rows("key", BASE_URL, "runs", logger, manager, 1))  # type: ignore[arg-type]

        assert rows == []
        assert fetch.call_count == 1

    def test_resume_pins_cursor_and_window(self):
        manager = FakeManager(resume=LangSmithResumeConfig(cursor="c9", window_start="2026-01-01T00:00:00.000000Z"))
        bodies: list[dict[str, Any]] = []

        def fake_fetch(session, url, headers, log, json_body=None):
            bodies.append(json_body)
            return {"runs": [_run("x")], "cursors": {"next": None}}

        with mock.patch(_FETCH_PAGE, side_effect=fake_fetch):
            _collect(get_rows("key", BASE_URL, "runs", logger, manager, 1, True, datetime.now(UTC)))  # type: ignore[arg-type]

        # The interrupted run's window is replayed, not recomputed from the new watermark — a
        # recomputed bound would shift what the saved cursor points at.
        assert bodies[0]["cursor"] == "c9"
        assert bodies[0]["start_time"] == "2026-01-01T00:00:00.000000Z"

    def test_state_saved_after_yield_with_current_page_cursor(self):
        # A crash after a yield must re-read the yielded page (merge dedupes), never skip past it —
        # so the checkpoint is the cursor of the page being read, saved only after a batch yields.
        manager = FakeManager()
        big_page = {"runs": [_run(f"r{i}") for i in range(2500)], "cursors": {"next": "c2"}}
        last_page = {"runs": [_run("tail")], "cursors": {"next": None}}

        with mock.patch(_FETCH_PAGE, side_effect=[big_page, last_page]):
            rows = _collect(get_rows("key", BASE_URL, "runs", logger, manager, 1))  # type: ignore[arg-type]

        assert len(rows) == 2501
        assert manager.saved == [LangSmithResumeConfig(cursor=None, window_start=None)]


class TestOffsetPagination:
    def test_walks_offsets_until_short_page(self):
        manager = FakeManager()
        pages = [[{"id": f"p1-{i}"} for i in range(100)], [{"id": "p2-0"}]]
        urls: list[str] = []

        def fake_fetch(session, url, headers, log, json_body=None):
            urls.append(url)
            return pages[len(urls) - 1]

        with mock.patch(_FETCH_PAGE, side_effect=fake_fetch):
            rows = _collect(get_rows("key", BASE_URL, "projects", logger, manager, 1))  # type: ignore[arg-type]

        assert len(rows) == 101
        assert "offset=0" in urls[0]
        assert "offset=100" in urls[1]
        assert manager.saved == []

    def test_feedback_incremental_sends_min_created_at(self):
        manager = FakeManager()
        watermark = datetime(2026, 6, 1, tzinfo=UTC)
        urls: list[str] = []

        def fake_fetch(session, url, headers, log, json_body=None):
            urls.append(url)
            return []

        with mock.patch(_FETCH_PAGE, side_effect=fake_fetch):
            _collect(get_rows("key", BASE_URL, "feedback", logger, manager, 1, True, watermark))  # type: ignore[arg-type]

        assert "min_created_at=" in urls[0]

    def test_resume_starts_from_saved_offset_and_pins_window(self):
        manager = FakeManager(resume=LangSmithResumeConfig(offset=200, window_start="2026-01-01T00:00:00.000000Z"))
        urls: list[str] = []

        def fake_fetch(session, url, headers, log, json_body=None):
            urls.append(url)
            return [{"id": "x"}]

        with mock.patch(_FETCH_PAGE, side_effect=fake_fetch):
            _collect(get_rows("key", BASE_URL, "feedback", logger, manager, 1, True, datetime.now(UTC)))  # type: ignore[arg-type]

        assert "offset=200" in urls[0]
        assert "min_created_at=2026-01-01T00%3A00%3A00.000000Z" in urls[0]


class TestHostSafety:
    def test_unsafe_host_raises_before_any_fetch(self):
        with (
            mock.patch(_IS_HOST_SAFE, return_value=(False, "Hosts with internal IP addresses are not allowed")),
            mock.patch(_FETCH_PAGE) as fetch,
        ):
            with pytest.raises(LangSmithHostNotAllowedError):
                _collect(get_rows("key", "https://10.0.0.1", "runs", logger, FakeManager(), 99))  # type: ignore[arg-type]

        fetch.assert_not_called()

    def test_plaintext_http_host_raises_on_cloud(self):
        with (
            mock.patch(_IS_HOST_SAFE, return_value=(True, None)),
            mock.patch(_IS_CLOUD, return_value=True),
            mock.patch(_FETCH_PAGE) as fetch,
        ):
            with pytest.raises(LangSmithHostNotAllowedError):
                _collect(get_rows("key", "http://langsmith.example", "runs", logger, FakeManager(), 1))  # type: ignore[arg-type]

        fetch.assert_not_called()

    def test_session_disables_redirects_redacts_key_and_skips_capture(self):
        # The key goes to a user-controlled host, so the session must never follow a redirect off
        # it; run payloads are raw LLM prompts/outputs, so bodies must stay out of sample capture.
        with (
            mock.patch(_MAKE_SESSION) as session,
            mock.patch(_FETCH_PAGE, return_value={"runs": [], "cursors": {}}),
        ):
            _collect(get_rows("key", BASE_URL, "runs", logger, FakeManager(), 1))  # type: ignore[arg-type]

        assert session.call_args.kwargs["allow_redirects"] is False
        assert session.call_args.kwargs["redact_values"] == ("key",)
        assert session.call_args.kwargs["capture"] is False


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_valid",
        [(200, True), (401, False), (403, False), (404, False), (500, False)],
    )
    def test_status_mapping(self, status_code, expected_valid):
        response = mock.MagicMock()
        response.status_code = status_code

        with mock.patch(_MAKE_SESSION) as session:
            session.return_value.get.return_value = response
            valid, message = validate_credentials("key", None)

        assert valid is expected_valid
        if not expected_valid:
            assert message

    def test_unsafe_host_fails_before_network_call(self):
        with (
            mock.patch(_IS_HOST_SAFE, return_value=(False, "Hosts with internal IP addresses are not allowed")),
            mock.patch(_MAKE_SESSION) as session,
        ):
            valid, message = validate_credentials("key", "https://10.0.0.1", team_id=99)

        assert valid is False
        assert message
        session.assert_not_called()
