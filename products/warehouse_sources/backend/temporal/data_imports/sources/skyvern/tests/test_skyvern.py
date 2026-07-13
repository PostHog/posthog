from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern import skyvern
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.settings import SKYVERN_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.skyvern import (
    SkyvernResumeConfig,
    _created_at_start,
    _extract_items,
    get_rows,
    skyvern_source,
    validate_credentials,
)

RUNS_CONFIG = SKYVERN_ENDPOINTS["runs"]


class FakeResumableManager:
    """In-memory stand-in for ResumableSourceManager that records saved states."""

    def __init__(self, state: Any = None):
        self._state = state
        self.saved: list[Any] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> Any:
        return self._state

    def save_state(self, data: Any) -> None:
        self.saved.append(data)


class TestCreatedAtStart:
    def test_none_when_not_incremental(self):
        # A full-refresh run (should_use_incremental_field False) must not send a created_at_start,
        # otherwise the first sync would silently window out history.
        assert _created_at_start(RUNS_CONFIG, False, datetime(2026, 1, 10, tzinfo=UTC)) is None

    def test_none_when_no_value(self):
        assert _created_at_start(RUNS_CONFIG, True, None) is None

    def test_applies_lookback(self):
        # The 3-day lookback is what lets a run whose status mutated after creation get re-pulled;
        # dropping it would freeze recently-created runs at their first-seen status.
        result = _created_at_start(RUNS_CONFIG, True, datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC))
        assert result is not None
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert parsed == datetime(2026, 1, 7, 12, 0, 0, tzinfo=UTC)

    def test_clamps_future_value_to_now(self):
        # A future-dated watermark would filter out every existing run; clamping keeps the sync valid.
        result = _created_at_start(RUNS_CONFIG, True, datetime(2999, 1, 1, tzinfo=UTC))
        assert result is not None
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert parsed <= datetime.now(UTC) + timedelta(seconds=1)


class TestExtractItems:
    @pytest.mark.parametrize(
        "data,data_key,expected",
        [
            ([{"a": 1}, {"a": 2}], None, [{"a": 1}, {"a": 2}]),
            # /v1/schedules wraps rows under "schedules"; without the unwrap the table syncs zero rows.
            ({"schedules": [{"s": 1}], "total_count": 1}, "schedules", [{"s": 1}]),
            ({"schedules": None}, "schedules", []),
            ({"unexpected": []}, None, []),
            ([], None, []),
        ],
    )
    def test_extract(self, data, data_key, expected):
        assert _extract_items(data, data_key) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_valid",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    def test_status_mapping(self, status_code, expected_valid):
        response = mock.MagicMock()
        response.status_code = status_code
        session = mock.MagicMock()
        session.get.return_value = response
        with mock.patch.object(skyvern, "make_tracked_session", return_value=session):
            valid, _ = validate_credentials("key", None)
        assert valid is expected_valid

    def test_uses_configured_base_url(self):
        response = mock.MagicMock()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response
        with mock.patch.object(skyvern, "make_tracked_session", return_value=session):
            validate_credentials("key", "http://localhost:8000/")
        called_url = session.get.call_args[0][0]
        assert called_url == "http://localhost:8000/v1/agents"


class TestSimplePagination:
    def test_paginates_until_short_page_and_saves_resume_state(self):
        # Guards the termination condition and resume checkpoint: a full page must continue, a short
        # page must stop, and the next page must be saved after each yield so a crash re-fetches it.
        manager = FakeResumableManager()
        pages = [
            [{"id": "1"}, {"id": "2"}],  # full page (PAGE_SIZE patched to 2) -> continue
            [{"id": "3"}],  # short page -> stop
        ]
        with (
            mock.patch.object(skyvern, "PAGE_SIZE", 2),
            mock.patch.object(skyvern, "make_tracked_session", return_value=mock.MagicMock()),
            mock.patch.object(skyvern, "_fetch_page", side_effect=pages),
        ):
            batches = list(
                get_rows("key", None, "browser_profiles", mock.MagicMock(), manager)  # type: ignore[arg-type]
            )

        assert [row["id"] for batch in batches for row in batch] == ["1", "2", "3"]
        assert manager.saved == [SkyvernResumeConfig(page=2)]

    def test_resumes_from_saved_page(self):
        manager = FakeResumableManager(state=SkyvernResumeConfig(page=5))
        captured: list[dict] = []

        def fetch(session, url, params, headers, logger):
            captured.append(params)
            return [{"id": "x"}]

        with (
            mock.patch.object(skyvern, "PAGE_SIZE", 100),
            mock.patch.object(skyvern, "make_tracked_session", return_value=mock.MagicMock()),
            mock.patch.object(skyvern, "_fetch_page", side_effect=fetch),
        ):
            list(get_rows("key", None, "browser_profiles", mock.MagicMock(), manager))  # type: ignore[arg-type]

        assert captured[0]["page"] == 5


class TestFanOutRuns:
    def test_fans_out_over_workflows_with_incremental_filter(self):
        # Guards the whole runs strategy: enumerate workflows, then hit each workflow's runs endpoint
        # with created_at_start. A regression that stopped passing created_at_start would turn every
        # incremental sync into a full-history refetch; one that dropped a workflow would lose its runs.
        manager = FakeResumableManager()
        run_params: list[tuple[str, dict]] = []

        def fetch(session, url, params, headers, logger):
            if url.endswith("/v1/agents"):
                return [{"workflow_permanent_id": "wpid_1"}, {"workflow_permanent_id": "wpid_2"}]
            run_params.append((url, dict(params)))
            return [{"workflow_run_id": f"wr_{url.split('/')[-2]}", "created_at": "2026-01-10T00:00:00Z"}]

        with (
            mock.patch.object(skyvern, "make_tracked_session", return_value=mock.MagicMock()),
            mock.patch.object(skyvern, "_fetch_page", side_effect=fetch),
        ):
            batches = list(
                get_rows(
                    "key",
                    None,
                    "runs",
                    mock.MagicMock(),
                    manager,  # type: ignore[arg-type]
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 1, 9, tzinfo=UTC),
                )
            )

        run_ids = {row["workflow_run_id"] for batch in batches for row in batch}
        assert run_ids == {"wr_wpid_1", "wr_wpid_2"}
        assert all("created_at_start" in params for _, params in run_params)

    def test_resumes_from_bookmarked_workflow(self):
        # A saved bookmark must skip already-completed workflows, not restart from the first one.
        manager = FakeResumableManager(state=SkyvernResumeConfig(page=1, workflow_permanent_id="wpid_2"))
        hit_run_urls: list[str] = []

        def fetch(session, url, params, headers, logger):
            if url.endswith("/v1/agents"):
                return [{"workflow_permanent_id": "wpid_1"}, {"workflow_permanent_id": "wpid_2"}]
            hit_run_urls.append(url)
            return [{"workflow_run_id": "wr_1", "created_at": "2026-01-10T00:00:00Z"}]

        with (
            mock.patch.object(skyvern, "make_tracked_session", return_value=mock.MagicMock()),
            mock.patch.object(skyvern, "_fetch_page", side_effect=fetch),
        ):
            list(get_rows("key", None, "runs", mock.MagicMock(), manager))  # type: ignore[arg-type]

        assert all("wpid_2" in url for url in hit_run_urls)
        assert not any("wpid_1" in url for url in hit_run_urls)


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
    def test_response_shape(self, endpoint, expected_primary_keys, expected_partition):
        response = skyvern_source("key", None, endpoint, mock.MagicMock(), mock.MagicMock())
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
