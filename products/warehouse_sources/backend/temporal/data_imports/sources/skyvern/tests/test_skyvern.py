import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern import skyvern
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.skyvern import (
    SkyvernResumeConfig,
    skyvern_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the skyvern module.
SKYVERN_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.skyvern.make_tracked_session"
)


def _resp(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: SkyvernResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, handler: Callable[[str, dict[str, list[str]]], Response]) -> list[dict[str, Any]]:
    """Wire a mock session to dispatch on the prepared request URL.

    Returns a list of per-request ``{"path", "query"}`` snapshots (query values are single-valued),
    captured at send time. A real ``requests.Session`` builds the prepared URL so path params, page
    params, and the incremental filter are all reflected exactly as they go on the wire.
    """
    session.headers = {}
    real = requests.Session()
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> Any:
        return real.prepare_request(request)

    def _send(prepared: Any, **kwargs: Any) -> Response:
        split = urlsplit(prepared.url)
        query = parse_qs(split.query)
        snapshots.append({"path": split.path, "query": {k: v[0] for k, v in query.items()}})
        return handler(split.path, query)

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestSimplePagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value

        def handler(path: str, query: dict[str, list[str]]) -> Response:
            return _resp([{"id": "x"}] if query["page"][0] == "5" else [])

        snapshots = _wire(session, handler)
        manager = _make_manager(SkyvernResumeConfig(page=5))

        _rows(skyvern_source("key", None, "browser_profiles", team_id=1, job_id="j", resumable_source_manager=manager))

        assert snapshots[0]["query"]["page"] == "5"


class TestFanOutRuns:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_clamps_future_watermark_to_now(self, MockSession) -> None:
        # A future-dated watermark would filter out every existing run; clamping keeps the sync valid.
        session = MockSession.return_value

        def handler(path: str, query: dict[str, list[str]]) -> Response:
            if path == "/v1/agents":
                return _resp([{"workflow_permanent_id": "wpid_1"}] if query["page"][0] == "1" else [])
            return _resp([{"workflow_run_id": "wr_1"}] if query["page"][0] == "1" else [])

        snapshots = _wire(session, handler)

        _rows(
            skyvern_source(
                "key",
                None,
                "runs",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2999, 1, 1, tzinfo=UTC),
            )
        )

        run_requests = [s for s in snapshots if s["path"].endswith("/runs")]
        sent = run_requests[0]["query"]["created_at_start"]
        parsed = datetime.fromisoformat(sent.replace("Z", "+00:00"))
        assert parsed <= datetime.now(UTC) + timedelta(seconds=1)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_skipping_completed_workflow(self, MockSession) -> None:
        # A saved fan-out checkpoint must skip already-completed workflows, not restart from the first.
        session = MockSession.return_value

        def handler(path: str, query: dict[str, list[str]]) -> Response:
            if path == "/v1/agents":
                return _resp(
                    [{"workflow_permanent_id": "wpid_1"}, {"workflow_permanent_id": "wpid_2"}]
                    if query["page"][0] == "1"
                    else []
                )
            return _resp([{"workflow_run_id": "wr_1"}] if query["page"][0] == "1" else [])

        snapshots = _wire(
            session,
            handler,
        )
        manager = _make_manager(
            SkyvernResumeConfig(
                fanout_state={"completed": ["/v1/agents/wpid_1/runs"], "current": None, "child_state": None}
            )
        )

        _rows(skyvern_source("key", None, "runs", team_id=1, job_id="j", resumable_source_manager=manager))

        run_paths = [s["path"] for s in snapshots if s["path"].endswith("/runs")]
        assert all("wpid_2" in p for p in run_paths)
        assert not any("wpid_1" in p for p in run_paths)

    def test_legacy_resume_state_still_deserializes(self) -> None:
        # State persisted by the pre-migration fan-out carried page + workflow_permanent_id; it must
        # still parse (ResumableSourceManager does dataclass(**saved)) after adding fanout_state.
        restored = SkyvernResumeConfig(**cast("dict[str, Any]", {"page": 3, "workflow_permanent_id": "wpid_9"}))
        assert restored.page == 3
        assert restored.fanout_state is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_valid",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(SKYVERN_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected_valid) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        valid, _ = validate_credentials("key", None)
        assert valid is expected_valid

    @mock.patch(SKYVERN_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        valid, message = validate_credentials("key", None)
        assert valid is False
        assert message


class TestSourceResponse:
    @pytest.mark.parametrize(
        "endpoint,expected_primary_keys,expected_partition",
        [
            ("workflows", ["workflow_permanent_id"], "created_at"),
            ("runs", ["workflow_run_id"], "created_at"),
            ("schedules", ["workflow_schedule_id"], "created_at"),
            ("browser_profiles", ["browser_profile_id"], "created_at"),
            ("credentials", ["credential_id"], None),
        ],
    )
    def test_response_shape(self, endpoint, expected_primary_keys, expected_partition) -> None:
        response = skyvern_source(
            "key", None, endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        # Skyvern lists return newest-first, so the pipeline must checkpoint in desc mode.
        assert response.sort_mode == "desc"
        if expected_partition is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [expected_partition]
            assert response.partition_mode == "datetime"


def test_skyvern_module_exposes_page_constants() -> None:
    # The per-workflow page cap only guards incremental runs; a full refresh must page unbounded.
    assert skyvern.PAGE_SIZE == 100
    assert skyvern.MAX_PAGES_PER_WORKFLOW == 100
