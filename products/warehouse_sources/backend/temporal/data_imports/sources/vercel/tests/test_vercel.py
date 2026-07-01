from typing import Any

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.vercel import vercel
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.settings import VERCEL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.vercel import (
    PAGE_SIZE,
    VercelResumeConfig,
    _build_params,
    _should_stop_desc,
    get_rows,
    validate_credentials,
    vercel_source,
)


class _FakeResumableManager:
    def __init__(self, state: VercelResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[VercelResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> VercelResumeConfig | None:
        return self._state

    def save_state(self, data: VercelResumeConfig) -> None:
        self.saved.append(data)


def _patch_fetch(monkeypatch: Any, responses: list[dict]) -> list[str]:
    """Replace _fetch_page with a queue that returns canned pages in order, recording each URL."""
    calls: list[str] = []
    queue = list(responses)

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        calls.append(url)
        return queue.pop(0)

    monkeypatch.setattr(vercel, "_fetch_page", fake_fetch)
    return calls


def _collect(endpoint: str, manager: _FakeResumableManager, monkeypatch: Any, responses: list[dict], **kwargs: Any):
    calls = _patch_fetch(monkeypatch, responses)
    rows: list[dict] = []
    for table in get_rows(
        access_token="t",
        endpoint=endpoint,
        team_id=kwargs.get("team_id"),
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        should_use_incremental_field=kwargs.get("should_use_incremental_field", False),
        db_incremental_field_last_value=kwargs.get("db_incremental_field_last_value"),
        incremental_field=kwargs.get("incremental_field"),
    ):
        rows.extend(table.to_pylist())
    return rows, calls


class TestBuildParams:
    @parameterized.expand(
        [
            ("default", "deployments", None, None, None, {"limit": PAGE_SIZE}),
            ("team_scoped_with_team", "deployments", "team_1", None, None, {"limit": PAGE_SIZE, "teamId": "team_1"}),
            # /v2/teams lists resources visible to the token itself, so teamId must not be appended.
            ("not_team_scoped_ignores_team", "teams", "team_1", None, None, {"limit": PAGE_SIZE}),
            ("since_and_until", "deployments", None, 123, 456, {"limit": PAGE_SIZE, "since": 123, "until": 456}),
            # projects has no since_param, so a cursor value must not become a query filter.
            ("no_since_param_drops_since", "projects", None, 123, None, {"limit": PAGE_SIZE}),
        ]
    )
    def test_build_params(
        self,
        _name: str,
        endpoint: str,
        team_id: str | None,
        since_value: Any,
        until: int | None,
        expected: dict[str, Any],
    ) -> None:
        assert _build_params(VERCEL_ENDPOINTS[endpoint], team_id, since_value, until) == expected


class TestShouldStopDesc:
    @parameterized.expand(
        [
            ("page_crosses_watermark", [{"created": 300}, {"created": 100}], "created", 150, True),
            ("equal_to_watermark_stops", [{"created": 150}], "created", 150, True),
            ("all_above_watermark", [{"created": 300}, {"created": 200}], "created", 150, False),
            ("no_cutoff", [{"created": 300}], "created", None, False),
            ("no_field", [{"created": 300}], None, 150, False),
            ("empty_items", [], "created", 150, False),
            ("missing_field_value_ignored", [{"other": 1}], "created", 150, False),
        ]
    )
    def test_should_stop_desc(
        self, _name: str, items: list[dict], field_name: str | None, cutoff: Any, expected: bool
    ) -> None:
        assert _should_stop_desc(items, field_name, cutoff) is expected


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False), (500, False)])
    def test_status_mapping(self, status: int, expected_ok: bool) -> None:
        response = requests.Response()
        response.status_code = status
        session = MagicMock()
        session.get.return_value = response
        with patch.object(vercel, "make_tracked_session", lambda *a, **k: session):
            ok, error = validate_credentials("token")

        assert ok is expected_ok, f"status={status}"
        assert (error is None) is expected_ok, f"status={status}"

    def test_request_exception_is_handled(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(vercel, "make_tracked_session", lambda *a, **k: session)

        ok, error = validate_credentials("token")
        assert ok is False
        assert error == "boom"


class TestGetRows:
    def test_full_refresh_follows_until_cursor_across_pages(self, monkeypatch: Any) -> None:
        responses = [
            {"deployments": [{"uid": "1", "created": 300}, {"uid": "2", "created": 200}], "pagination": {"next": 200}},
            {"deployments": [{"uid": "3", "created": 100}], "pagination": {"next": None}},
        ]
        rows, calls = _collect("deployments", _FakeResumableManager(), monkeypatch, responses)

        assert [r["uid"] for r in rows] == ["1", "2", "3"]
        assert "until=" not in calls[0]
        assert "until=200" in calls[1]

    def test_uses_response_data_key_per_endpoint(self, monkeypatch: Any) -> None:
        responses = [{"projects": [{"id": "p1"}, {"id": "p2"}], "pagination": {"next": None}}]
        rows, _ = _collect("projects", _FakeResumableManager(), monkeypatch, responses)
        assert [r["id"] for r in rows] == ["p1", "p2"]

    def test_incremental_sends_since_and_stops_at_watermark(self, monkeypatch: Any) -> None:
        responses = [
            {"deployments": [{"uid": "1", "created": 300}, {"uid": "2", "created": 200}], "pagination": {"next": 200}},
            # 120 <= watermark(150): stop after this page rather than walking older history.
            {"deployments": [{"uid": "3", "created": 120}], "pagination": {"next": 120}},
            {"deployments": [{"uid": "4", "created": 50}], "pagination": {"next": None}},
        ]
        rows, calls = _collect(
            "deployments",
            _FakeResumableManager(),
            monkeypatch,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=150,
        )

        assert [r["uid"] for r in rows] == ["1", "2", "3"]
        assert "since=150" in calls[0]
        assert len(calls) == 2

    def test_stops_when_cursor_does_not_advance(self, monkeypatch: Any) -> None:
        # An endpoint that ignores `until` re-serves the same cursor; stop instead of looping forever.
        responses = [
            {"deployments": [{"uid": "1", "created": 300}], "pagination": {"next": 300}},
            {"deployments": [{"uid": "9", "created": 300}], "pagination": {"next": 300}},
        ]
        rows, calls = _collect("deployments", _FakeResumableManager(), monkeypatch, responses)

        assert [r["uid"] for r in rows] == ["1", "9"]
        assert len(calls) == 2

    def test_resumes_from_saved_until_cursor(self, monkeypatch: Any) -> None:
        responses = [{"deployments": [{"uid": "1", "created": 400}], "pagination": {"next": None}}]
        manager = _FakeResumableManager(VercelResumeConfig(until=500))
        rows, calls = _collect("deployments", manager, monkeypatch, responses)

        assert [r["uid"] for r in rows] == ["1"]
        assert "until=500" in calls[0]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        responses = [{"deployments": [], "pagination": {"next": None}}]
        rows, calls = _collect("deployments", _FakeResumableManager(), monkeypatch, responses)
        assert rows == []
        assert len(calls) == 1

    def test_mid_page_yield_checkpoints_current_page_not_next(self, monkeypatch: Any) -> None:
        # Regression: a mid-page yield must checkpoint the cursor for the CURRENT page, not the
        # next one. Page two crosses the batcher's 2000-row chunk, so the batch yields while the
        # rest of page two is still unprocessed. Saving the next cursor (400) here would advance
        # the watermark past those rows and silently skip them after a crash/resume; the checkpoint
        # must stay at page two's own cursor (200) so resume re-fetches it (dedup handles the
        # already-yielded rows).
        responses: list[dict] = [
            {"deployments": [{"uid": "a", "created": 100}, {"uid": "b", "created": 99}], "pagination": {"next": 200}},
            {
                "deployments": [{"uid": str(i), "created": 100000 - i} for i in range(2500)],
                "pagination": {"next": 400},
            },
            {"deployments": [], "pagination": {"next": None}},
        ]
        manager = _FakeResumableManager()
        rows, _ = _collect("deployments", manager, monkeypatch, responses)

        assert len(rows) == 2502
        assert manager.saved == [VercelResumeConfig(until=200)]


class TestVercelSource:
    @parameterized.expand(
        [("deployments", "uid"), ("projects", "id"), ("teams", "id"), ("domains", "id"), ("aliases", "uid")]
    )
    def test_source_response_primary_key_and_sort(self, endpoint: str, expected_pk: str) -> None:
        response = vercel_source(
            access_token="t",
            endpoint=endpoint,
            team_id=None,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == [expected_pk]
        assert response.sort_mode == "desc"
