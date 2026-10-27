import functools
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.langsmith import (
    LangSmithSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith import langsmith as langsmith_module
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith import (
    MAX_CURSOR_BYTES,
    LangSmithHostNotAllowedError,
    LangSmithPageLimitError,
    LangSmithPaginationTooLargeError,
    LangSmithRepeatedCursorError,
    LangSmithResponseTooLargeError,
    LangSmithResumeConfig,
    LangSmithRunsPageTooLargeError,
    _fetch_page,
    _read_capped_body,
    _resolve_window_start,
    get_rows,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.settings import (
    LANGSMITH_ENDPOINTS,
    RUNS_HEAVY_SELECT_FIELDS,
    RUNS_SELECT_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.source import LangSmithSource

logger = structlog.get_logger()

BASE_URL = "https://api.smith.langchain.com"

_FETCH_PAGE = "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith._fetch_page"
_IS_HOST_SAFE = "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith._is_host_safe"
_IS_CLOUD = "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith.is_cloud"
_MAX_PAGES = "products.warehouse_sources.backend.temporal.data_imports.sources.langsmith.langsmith.MAX_PAGES_PER_RUN"


class FakeManager:
    """Stand-in for ResumableSourceManager that records saved state and can replay a resume value."""

    def __init__(self, resume: LangSmithResumeConfig | None = None):
        self._resume = resume
        self.saved: list[LangSmithResumeConfig] = []
        self.safe_points_after_save: list[int] = []

    def can_resume(self) -> bool:
        return self._resume is not None

    def load_state(self) -> LangSmithResumeConfig | None:
        return self._resume

    def save_state(self, data: LangSmithResumeConfig) -> None:
        self.saved.append(data)

    def safe_point(self) -> None:
        self.safe_points_after_save.append(len(self.saved))


def _driver(host: str | None = None) -> SourceDriver:
    return SourceDriver(LangSmithSource(), LangSmithSourceConfig(api_key="key", host=host))


def _rows(result: DriveResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in result.rows:
        rows.extend(table.to_pylist())
    return rows


def _collect(tables) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in tables:
        rows.extend(table.to_pylist())
    return rows


def _run(run_id: str) -> dict[str, Any]:
    return {"id": run_id, "start_time": "2026-06-01T00:00:00Z"}


SESSION_IDS_PAGE = [{"id": "session-1"}]


def _with_session_page(fake_fetch):
    """Wrap a runs/query-only fake_fetch so the preceding sessions-listing GET (json_body=None)
    is answered separately from the runs/query POSTs the wrapped function expects to see."""

    def wrapped(session, url, headers, log, json_body=None):
        if json_body is None:
            return SESSION_IDS_PAGE
        return fake_fetch(session, url, headers, log, json_body=json_body)

    return wrapped


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
            ("https://api.smith.langchain.com:8443", "https://api.smith.langchain.com:8443"),
            ("https://[::1]:8080", "https://[::1]:8080"),
            # Authority is rebuilt from the parsed hostname/port only — never the raw netloc — so a
            # backslash or userinfo can't make the validated host differ from the connected one. Keeping
            # netloc verbatim would let `https://127.0.0.1\@evil.com` pass the allowlist as `evil.com`
            # while requests connects to `127.0.0.1` (a parser-mismatch SSRF).
            ("https://127.0.0.1\\@evil.com", "https://evil.com"),
            ("https://user:pass@127.0.0.1@evil.com", "https://evil.com"),
        ],
    )
    def test_reduces_to_clean_origin(self, raw, expected):
        assert normalize_base_url(raw) == expected


class TestResolveWindowStart:
    def test_first_incremental_sync_floors_to_lookback_days(self):
        config = LANGSMITH_ENDPOINTS["runs"]

        start = _resolve_window_start(config, should_use_incremental_field=True, db_incremental_field_last_value=None)

        assert start is not None
        assert (datetime.now(UTC) - start).days == pytest.approx(config.default_lookback_days, abs=1)


class TestRunsPagination:
    def test_cursor_walk_keeps_window_on_every_page(self):
        # If the start_time window were dropped from cursor requests, every incremental sync would
        # walk back through the full run history — an API-cost and memory bug.
        watermark = datetime(2026, 6, 1, tzinfo=UTC)
        result = _driver().run(
            "runs",
            [
                ScriptedResponse(json=SESSION_IDS_PAGE),
                ScriptedResponse(json={"runs": [_run("a")], "cursors": {"next": "c2"}}),
                ScriptedResponse(json={"runs": [_run("b")], "cursors": {"next": None}}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        bodies = [request.json() for request in result.requests[1:]]
        assert result.raised is None
        assert [row["id"] for row in _rows(result)] == ["a", "b"]
        assert len(bodies) == 2
        assert "cursor" not in bodies[0]
        assert bodies[1]["cursor"] == "c2"
        for body in bodies:
            assert body["start_time"]  # the watermark window rides every page
            assert body["order"] == "asc"
            assert body["limit"] == 100
            assert body["select"] == RUNS_SELECT_FIELDS

    def test_terminates_on_empty_page_and_missing_cursors(self):
        result = _driver().run(
            "runs",
            [
                ScriptedResponse(json=SESSION_IDS_PAGE),
                ScriptedResponse(json={"runs": [], "cursors": {"next": "dangling"}}),
            ],
        )

        assert result.raised is None
        assert _rows(result) == []
        # One call to list sessions, one to runs/query.
        assert result.paths == ["/api/v1/sessions", "/api/v1/runs/query"]

    def test_no_tracing_projects_skips_runs_query(self):
        result = _driver().run("runs", [ScriptedResponse(json=[])])

        assert result.raised is None
        assert _rows(result) == []
        assert result.paths == ["/api/v1/sessions"]

    def test_resume_pins_cursor_and_window(self):
        result = _driver().run(
            "runs",
            [
                ScriptedResponse(json=SESSION_IDS_PAGE),
                ScriptedResponse(json={"runs": [_run("x")], "cursors": {"next": None}}),
            ],
            resume_state=LangSmithResumeConfig(cursor="c9", window_start="2026-01-01T00:00:00.000000Z"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now(UTC),
        )

        # The interrupted run's window is replayed, not recomputed from the new watermark — a
        # recomputed bound would shift what the saved cursor points at.
        assert result.raised is None
        assert result.requests[1].json()["cursor"] == "c9"
        assert result.requests[1].json()["start_time"] == "2026-01-01T00:00:00.000000Z"

    def test_state_saved_after_yield_with_current_page_cursor(self):
        # A crash after a yield must re-read the yielded page (merge dedupes), never skip past it —
        # so the checkpoint is the cursor of the page being read, saved only after a batch yields.
        big_page = {"runs": [_run(f"r{i}") for i in range(2500)], "cursors": {"next": "c2"}}
        last_page = {"runs": [_run("tail")], "cursors": {"next": None}}

        result = _driver().run(
            "runs",
            [
                ScriptedResponse(json=SESSION_IDS_PAGE),
                ScriptedResponse(json=big_page),
                ScriptedResponse(json=last_page),
            ],
        )

        assert result.raised is None
        assert len(_rows(result)) == 2501
        assert result.saved_states == [LangSmithResumeConfig(cursor=None, window_start=None)]


class TestRunsPageShrinking:
    OVERSIZED_PAGE = {"runs": [_run("huge")], "cursors": {"next": None}, "padding": "x" * 500}

    @staticmethod
    def _respond(oversized: Callable[[RecordedRequest], bool]) -> Callable[[RecordedRequest], ScriptedResponse]:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.method == "GET":
                return ScriptedResponse(json=SESSION_IDS_PAGE)
            if oversized(request):
                return ScriptedResponse(json=TestRunsPageShrinking.OVERSIZED_PAGE)
            return ScriptedResponse(json={"runs": [_run("huge")], "cursors": {"next": None}})

        return respond

    @pytest.fixture(autouse=True)
    def _small_response_cap(self) -> Iterator[None]:
        with mock.patch.object(langsmith_module, "_read_capped_body", functools.partial(_read_capped_body, cap=200)):
            yield

    def test_single_oversized_run_is_imported_without_its_heavy_fields(self):
        def has_heavy_fields(request: RecordedRequest) -> bool:
            return any(name in request.json()["select"] for name in RUNS_HEAVY_SELECT_FIELDS)

        result = _driver().run("runs", self._respond(has_heavy_fields))

        assert result.raised is None
        assert [r["id"] for r in _rows(result)] == ["huge"]
        selects = [request.json()["select"] for request in result.requests if request.method == "POST"]
        assert selects[-1] == [name for name in RUNS_SELECT_FIELDS if name not in RUNS_HEAVY_SELECT_FIELDS]

    def test_single_run_page_oversized_without_heavy_fields_raises(self):
        result = _driver().run("runs", self._respond(lambda request: True))

        assert isinstance(result.raised, LangSmithRunsPageTooLargeError)
        # 100 -> 50 -> 25 -> 12 -> 6 -> 3 -> 1, then one narrowed attempt.
        assert [request.method for request in result.requests].count("POST") == 8


class TestRunsColumnSelection:
    def test_enabled_columns_narrow_the_request_body(self):
        manager = FakeManager()
        bodies: list[dict[str, Any]] = []

        def fake_fetch(session, url, headers, log, json_body=None):
            bodies.append(json_body)
            return {"runs": [_run("a")], "cursors": {"next": None}}

        with mock.patch(_FETCH_PAGE, side_effect=_with_session_page(fake_fetch)):
            _collect(get_rows("key", BASE_URL, "runs", logger, manager, 1, enabled_columns=["name"]))  # type: ignore[arg-type]

        assert bodies[0]["select"] == ["id", "name", "start_time"]


class TestOffsetPagination:
    def test_feedback_incremental_sends_min_created_at(self):
        watermark = datetime(2026, 6, 1, tzinfo=UTC)
        result = _driver().run(
            "feedback",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert result.requests[0].param("min_created_at") is not None

    def test_resume_starts_from_saved_offset_and_pins_window(self):
        result = _driver().run(
            "feedback",
            [ScriptedResponse(json=[{"id": "x"}])],
            resume_state=LangSmithResumeConfig(offset=200, window_start="2026-01-01T00:00:00.000000Z"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now(UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("offset") == "200"
        assert result.requests[0].param("min_created_at") == "2026-01-01T00:00:00.000000Z"


class TestExamplesPagination:
    def test_no_datasets_in_workspace_skips_examples_entirely(self):
        # With no datasets there is nothing to scope to, so no examples request should be issued.
        result = _driver().run("examples", [ScriptedResponse(json=[])])

        assert result.raised is None
        assert _rows(result) == []
        assert result.paths == ["/api/v1/datasets"]

    def test_resume_continues_from_saved_dataset_and_offset(self):
        # A resumed run skips datasets already fully read, picks the interrupted dataset up at its
        # saved offset, and reads the remaining datasets from the start.
        result = _driver().run(
            "examples",
            [
                ScriptedResponse(json=[{"id": "ds-1"}, {"id": "ds-2"}, {"id": "ds-3"}]),
                ScriptedResponse(json=[{"id": "ex"}]),
                ScriptedResponse(json=[{"id": "ex"}]),
            ],
            resume_state=LangSmithResumeConfig(parent_id="ds-2", offset=100),
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/datasets", "/api/v1/examples", "/api/v1/examples"]
        assert result.params("dataset")[1:] == ["ds-2", "ds-3"]
        assert result.params("offset")[1:] == ["100", "0"]

    def test_many_short_pages_still_hit_the_page_limit(self):
        # A dataset whose examples fit on a single short page must still cost one request against
        # MAX_PAGES_PER_RUN. Otherwise a host serving many datasets (bounded only by
        # MAX_PARENT_IDS_BYTES), each with one short page, could page forever without ever
        # tripping the per-run limit.
        dataset_ids = [f"ds-{i}" for i in range(10)]

        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/api/v1/examples":
                # This short page has one item and cannot reach the full page branch.
                return ScriptedResponse(json=[{"id": "ex"}])
            return ScriptedResponse(json=[{"id": dataset_id} for dataset_id in dataset_ids])

        with mock.patch(_MAX_PAGES, 3):
            result = _driver().run("examples", answer)

        assert isinstance(result.raised, LangSmithPageLimitError)
        assert result.paths.count("/api/v1/examples") == 3
        assert result.saved_states[-1].parent_id == "ds-3"
        assert result.saved_states[-1].offset == 0


class TestAnnotationQueueRunsPagination:
    def test_pages_each_queue_and_tags_rows_with_the_queue(self):
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if "/runs" in request.path:
                return ScriptedResponse(
                    json=[{"id": "run-1", "queue_run_id": "qr-1", "name": "chain", "s3_urls": {"a": "signed"}}]
                )
            return ScriptedResponse(json=[{"id": "queue/1"}])

        result = _driver().run("annotation_queue_runs", answer)

        # The queue id comes from the host, so it must be encoded rather than extend the path.
        assert result.raised is None
        assert result.urls[1].startswith(f"{BASE_URL}/api/v1/annotation-queues/queue%2F1/runs?")
        assert _rows(result) == [{"id": "run-1", "queue_run_id": "qr-1", "name": "chain", "queue_id": "queue/1"}]


class TestThreadsPagination:
    def test_walks_every_project_with_cursor_and_fixed_window(self):
        pages = {
            ("p-1", None): {"items": [{"thread_id": "t-1"}], "next_cursor": "c-1"},
            # A page can be empty before the last one; only a missing cursor ends the project.
            ("p-1", "c-1"): {"items": [], "next_cursor": "c-2"},
            ("p-1", "c-2"): {"items": [{"thread_id": "t-2"}], "next_cursor": None},
            ("p-2", None): {"items": [{"thread_id": "t-1"}]},
        }

        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.method == "GET":
                return ScriptedResponse(json=[{"id": "p-1"}, {"id": "p-2"}])
            body = request.json()
            return ScriptedResponse(json=pages[(body["project_id"], body.get("cursor"))])

        result = _driver().run("threads", answer)
        bodies = [request.json() for request in result.requests[1:]]

        assert result.raised is None
        assert result.requests[0].param("reference_free") == "true"
        assert [(row["project_id"], row["thread_id"]) for row in _rows(result)] == [
            ("p-1", "t-1"),
            ("p-1", "t-2"),
            ("p-2", "t-1"),
        ]
        assert len(bodies) == 4
        window_start = bodies[0]["min_start_time"]
        assert all(body["min_start_time"] == window_start for body in bodies)
        lookback = datetime.now(UTC) - datetime.fromisoformat(window_start.replace("Z", "+00:00"))
        assert lookback.days == pytest.approx(LANGSMITH_ENDPOINTS["threads"].default_lookback_days, abs=1)

    def test_resume_continues_from_saved_project_cursor_and_window(self):
        window_start = "2026-01-01T00:00:00.000000Z"

        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.method == "GET":
                return ScriptedResponse(json=[{"id": "p-1"}, {"id": "p-2"}, {"id": "p-3"}])
            return ScriptedResponse(json={"items": [{"thread_id": "t"}]})

        result = _driver().run(
            "threads",
            answer,
            resume_state=LangSmithResumeConfig(parent_id="p-2", cursor="c-5", window_start=window_start),
        )

        assert result.raised is None
        assert [
            (body["project_id"], body.get("cursor"), body["min_start_time"])
            for body in (request.json() for request in result.requests[1:])
        ] == [("p-2", "c-5", window_start), ("p-3", None, window_start)]


class TestWorkspaces:
    def test_full_list_is_fetched_once(self):
        # GET /workspaces ignores limit/offset, so treating a full list as a full offset page would
        # fetch the same workspaces again and again.
        workspaces = [{"id": f"w{i}"} for i in range(LANGSMITH_ENDPOINTS["projects"].page_size)]
        result = _driver().run("workspaces", [ScriptedResponse(json=workspaces)])

        assert result.raised is None
        assert result.paths == ["/api/v1/workspaces"]
        assert len(_rows(result)) == len(workspaces)


class TestPaginationAbuseGuards:
    def test_oversized_session_id_accumulation_raises(self):
        # A host controls both the count and size of session ids returned while scoping the runs
        # query; without a cumulative cap, accumulating every id would let a hostile host exhaust a
        # shared worker's memory well before MAX_PAGES_PER_RUN ever trips.
        huge_id = "x" * 50_000
        page_size = LANGSMITH_ENDPOINTS["projects"].page_size
        result = _driver().run("runs", [ScriptedResponse(json=[{"id": huge_id} for _ in range(page_size)])])

        assert isinstance(result.raised, LangSmithPaginationTooLargeError)

    def test_repeated_runs_cursor_raises(self):
        # A host that hands back a cursor it already gave us would loop forever; the walk must bail
        # instead of spinning until the week-long activity timeout.
        result = _driver().run(
            "runs",
            [
                ScriptedResponse(json=SESSION_IDS_PAGE),
                ScriptedResponse(json={"runs": [_run("a")], "cursors": {"next": "loop"}}),
                ScriptedResponse(json={"runs": [_run("a")], "cursors": {"next": "loop"}}),
            ],
        )

        assert isinstance(result.raised, LangSmithRepeatedCursorError)

    def test_oversized_runs_cursor_raises(self):
        # An attacker-controlled cursor near the response-size limit must never be echoed back or
        # retained; a cursor beyond MAX_CURSOR_BYTES is rejected outright.
        big_cursor = "x" * (MAX_CURSOR_BYTES + 1)
        result = _driver().run(
            "runs",
            [
                ScriptedResponse(json=SESSION_IDS_PAGE),
                ScriptedResponse(json={"runs": [_run("a")], "cursors": {"next": big_cursor}}),
            ],
        )

        assert isinstance(result.raised, LangSmithPaginationTooLargeError)

    def test_runs_page_limit_checkpoints_and_raises(self):
        # A host returning an endless stream of full pages with fresh cursors must not monopolise a
        # worker: the attempt ends at the cap after checkpointing so the resume path continues it.
        # Rows read before the cap but never large enough to fill a batch must be flushed before
        # raising — the checkpoint points at the *next* page, so an unflushed partial batch is lost.
        counter = {"n": 0}

        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.method == "GET":
                return ScriptedResponse(json=SESSION_IDS_PAGE)
            counter["n"] += 1
            return ScriptedResponse(json={"runs": [_run(f"r{counter['n']}")], "cursors": {"next": f"c{counter['n']}"}})

        with mock.patch(_MAX_PAGES, 3):
            result = _driver().run("runs", answer)

        assert isinstance(result.raised, LangSmithPageLimitError)
        assert result.saved_states[-1].cursor is not None
        assert result.committed_states[-1] == result.saved_states[-1]
        assert [row["id"] for row in _rows(result)] == ["r1", "r2", "r3"]

    def test_offset_page_limit_checkpoints_and_raises(self):
        # Same guard on offset endpoints, where a host can return exactly page_size rows forever.
        # The rows read before the cap must be flushed rather than dropped on the way out.
        page_size = LANGSMITH_ENDPOINTS["projects"].page_size

        def answer(_request: RecordedRequest) -> ScriptedResponse:
            return ScriptedResponse(json=[{"id": f"x{i}"} for i in range(page_size)])

        with mock.patch(_MAX_PAGES, 3):
            result = _driver().run("projects", answer)

        assert isinstance(result.raised, LangSmithPageLimitError)
        assert result.saved_states[-1].offset is not None
        assert len(_rows(result)) == 3 * page_size


class TestResponseSizeCap:
    def test_read_capped_body_aborts_before_consuming_whole_body(self):
        # The body is streamed and rejected the moment the running total passes the cap, so a hostile
        # host can't inflate a small gzip bomb into memory before we notice. A one-shot decoded read
        # would pull (and decompress) everything first, so this asserts we stop mid-stream.
        consumed: list[int] = []

        def chunks():
            consumed.append(1)
            yield b"x" * 6
            consumed.append(2)
            yield b"x" * 6
            consumed.append(3)  # must never run — the cap is already blown after the second chunk
            yield b"x" * 6

        response = mock.MagicMock()
        response.iter_content.return_value = chunks()
        with pytest.raises(LangSmithResponseTooLargeError):
            _read_capped_body(response, cap=10)
        assert consumed == [1, 2]

    def test_fetch_page_streams_and_parses_body(self):
        # The body must be pulled through the streamed/capped reader, never buffered eagerly by
        # requests — dropping stream=True would reintroduce the unbounded-buffering vector.
        response = mock.MagicMock()
        response.status_code = 200
        response.ok = True
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.iter_content.return_value = [b'{"runs": [{"id": "a"}]}']
        session = mock.MagicMock()
        session.post.return_value = response

        result = _fetch_page(session, f"{BASE_URL}/api/v1/runs/query", {}, logger, json_body={"limit": 1})

        assert result == {"runs": [{"id": "a"}]}
        assert session.post.call_args.kwargs["stream"] is True


class TestHostSafety:
    def test_unsafe_host_raises_before_any_fetch(self):
        with mock.patch(_IS_HOST_SAFE, return_value=(False, "Hosts with internal IP addresses are not allowed")):
            result = _driver("https://10.0.0.1").run("runs", [], team_id=99)

        assert isinstance(result.raised, LangSmithHostNotAllowedError)
        assert result.requests == []

    def test_plaintext_http_host_raises_on_cloud(self):
        with (
            mock.patch(_IS_HOST_SAFE, return_value=(True, None)),
            mock.patch(_IS_CLOUD, return_value=True),
        ):
            result = _driver("http://langsmith.example").run("runs", [])

        assert isinstance(result.raised, LangSmithHostNotAllowedError)
        assert result.requests == []

    def test_session_disables_redirects_redacts_key_and_skips_capture(self):
        # The key goes to a user-controlled host, so the session must never follow a redirect off
        # it; run payloads are raw LLM prompts/outputs, so bodies must stay out of sample capture.
        result = _driver().run("runs", [ScriptedResponse(json=SESSION_IDS_PAGE), ScriptedResponse(json={"runs": []})])

        assert result.raised is None
        assert result.session_options[0]["allow_redirects"] is False
        assert result.session_options[0]["redact_values"] == ("key",)
        assert result.session_options[0]["capture"] is False


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_fragment",
        [
            (404, "no LangSmith API there"),
            # A rate limit and a LangSmith outage are not a bad key, so both ask for a retry
            # instead of sending the user to replace a key that works.
            (429, "Try again in a few minutes"),
            (418, "valid key from your LangSmith"),
        ],
    )
    def test_status_mapping(self, status_code, expected_fragment):
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            valid, message = validate_credentials("key", None)

        assert {request.path for request in network.requests_log} == {"/api/v1/sessions"}
        assert valid is (expected_fragment is None)
        if expected_fragment is None:
            assert message is None
        else:
            assert message is not None
            assert expected_fragment in message
            # The wizard shows this message verbatim, so no status code may reach it.
            assert str(status_code) not in message

    def test_unreachable_host_does_not_surface_the_raw_exception(self):
        error = requests.ConnectionError(
            "HTTPSConnectionPool(host='langsmith.example', port=443): Max retries exceeded"
        )
        with scripted_network(always(error)):
            valid, message = validate_credentials("key", None)

        assert valid is False
        assert message is not None
        assert "HTTPSConnectionPool" not in message
        assert "Try again in a few minutes" in message

    def test_unsafe_host_fails_before_network_call(self):
        with (
            mock.patch(_IS_HOST_SAFE, return_value=(False, "Hosts with internal IP addresses are not allowed")),
            scripted_network([]) as network,
        ):
            valid, message = validate_credentials("key", "https://10.0.0.1", team_id=99)

        assert valid is False
        assert message
        assert network.requests_log == []
