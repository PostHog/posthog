from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.airbrake import airbrake
from products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.airbrake import (
    NOTICES_MAX_PAGES_PER_GROUP,
    PAGE_LIMIT,
    AirbrakeResumeConfig,
    _build_groups_params,
    _format_start_time,
    airbrake_source,
    get_rows,
    validate_credentials,
)


class _FakeResumableManager:
    def __init__(self, state: AirbrakeResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[AirbrakeResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> AirbrakeResumeConfig | None:
        return self._state

    def save_state(self, data: AirbrakeResumeConfig) -> None:
        self.saved.append(data)


def _response_with_status(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    return response


class _FakePages:
    """Fixture keyed by (path, page). Missing keys mean 'empty page' so pagination terminates."""

    def __init__(self, pages: dict[tuple[str, int], Any]) -> None:
        self.pages = pages
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, session: Any, url: str, params: dict[str, Any], logger: Any) -> dict[str, Any]:
        path = url.removeprefix("https://api.airbrake.io")
        self.requests.append((path, params))
        result = self.pages.get((path, params["page"]), {})
        if isinstance(result, Exception):
            raise result
        return result


def _collect(
    manager: _FakeResumableManager, monkeypatch: Any, pages: _FakePages, endpoint: str, **kwargs: Any
) -> list[dict]:
    monkeypatch.setattr(airbrake, "_fetch_page", pages)
    rows: list[dict] = []
    for batch in get_rows(
        api_key="user-key",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


class TestFormatStartTime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "2026-03-04T00:00:00Z", "2026-03-04T00:00:00Z"),
        ]
    )
    def test_format_start_time(self, _name: str, value: Any, expected: str) -> None:
        # Airbrake expects RFC 3339; a +00:00 offset or bare isoformat drifts from the documented shape.
        assert _format_start_time(value) == expected


class TestBuildGroupsParams:
    def test_incremental_run_sets_server_side_start_time(self) -> None:
        params = _build_groups_params(True, datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))
        assert params == {"order": "created", "start_time": "2026-03-04T02:58:14.000Z"}

    @parameterized.expand(
        [
            ("first_sync_no_watermark", True, None),
            ("full_refresh", False, datetime(2026, 3, 4, tzinfo=UTC)),
        ]
    )
    def test_no_start_time_without_incremental_watermark(
        self, _name: str, should_use_incremental_field: bool, last_value: Any
    ) -> None:
        # start_time=None (or a stale watermark on full refresh) must not leak into the query string.
        params = _build_groups_params(should_use_incremental_field, last_value)
        assert params == {"order": "created"}


class TestIterPages:
    def test_walks_pages_until_empty_page(self, monkeypatch: Any) -> None:
        pages = _FakePages(
            {
                ("/api/v4/projects", 1): {"count": 150, "projects": [{"id": 1}] * PAGE_LIMIT},
                ("/api/v4/projects", 2): {"count": 150, "projects": [{"id": 2}] * 50},
            }
        )
        monkeypatch.setattr(airbrake, "_fetch_page", pages)
        result = list(airbrake._iter_pages(MagicMock(), "user-key", "/api/v4/projects", "projects", MagicMock()))
        assert [(page, len(items)) for page, items in result] == [(1, PAGE_LIMIT), (2, 50)]
        # Page 2 was short of the limit but non-empty: only the empty page 3 may terminate the walk,
        # otherwise a server that clamps `limit` below PAGE_LIMIT truncates every collection to one page.
        assert [params["page"] for _path, params in pages.requests] == [1, 2, 3]

    def test_single_page_collection_skips_trailing_empty_request(self, monkeypatch: Any) -> None:
        pages = _FakePages({("/api/v4/projects", 1): {"count": 2, "projects": [{"id": 1}, {"id": 2}]}})
        monkeypatch.setattr(airbrake, "_fetch_page", pages)
        result = list(airbrake._iter_pages(MagicMock(), "user-key", "/api/v4/projects", "projects", MagicMock()))
        assert [(page, len(items)) for page, items in result] == [(1, 2)]
        assert len(pages.requests) == 1

    def test_max_pages_cap_truncates_collection(self, monkeypatch: Any) -> None:
        pages = _FakePages({("/p", page): {"count": 999, "notices": [{"id": page}]} for page in range(1, 10)})
        monkeypatch.setattr(airbrake, "_fetch_page", pages)
        result = list(airbrake._iter_pages(MagicMock(), "user-key", "/p", "notices", MagicMock(), max_pages=3))
        assert [page for page, _items in result] == [1, 2, 3]

    def test_key_and_limit_sent_on_every_page(self, monkeypatch: Any) -> None:
        pages = _FakePages({("/api/v4/projects", 1): {"count": 999, "projects": [{"id": 1}]}})
        monkeypatch.setattr(airbrake, "_fetch_page", pages)
        list(airbrake._iter_pages(MagicMock(), "user-key", "/api/v4/projects", "projects", MagicMock()))
        for _path, params in pages.requests:
            assert params["key"] == "user-key"
            assert params["limit"] == PAGE_LIMIT


class TestFetchPageRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500)])
    def test_retryable_statuses_are_retried(self, _name: str, status_code: int) -> None:
        bad = MagicMock()
        bad.status_code = status_code
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"projects": []}

        session = MagicMock()
        session.get.side_effect = [bad, good]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(airbrake._fetch_page.retry, "sleep", lambda *_: None)  # type: ignore[attr-defined]
            result = airbrake._fetch_page(session, "https://api.airbrake.io/api/v4/projects", {}, MagicMock())

        assert result == {"projects": []}
        assert session.get.call_count == 2

    def test_auth_error_raises_immediately(self) -> None:
        # 401 must surface as HTTPError on the first attempt so get_non_retryable_errors can stop the sync.
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError(
            "401 Client Error: Unauthorized for url: https://api.airbrake.io/api/v4/projects"
        )
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            airbrake._fetch_page(session, "https://api.airbrake.io/api/v4/projects", {}, MagicMock())

        assert session.get.call_count == 1


class TestGroupsFanOut:
    def test_fans_out_over_every_project(self, monkeypatch: Any) -> None:
        pages = _FakePages(
            {
                ("/api/v4/projects", 1): {"count": 2, "projects": [{"id": 1}, {"id": 2}]},
                ("/api/v4/projects/1/groups", 1): {"count": 1, "groups": [{"id": "g1", "projectId": 1}]},
                ("/api/v4/projects/2/groups", 1): {"count": 1, "groups": [{"id": "g2", "projectId": 2}]},
            }
        )
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "groups")
        assert rows == [{"id": "g1", "projectId": 1}, {"id": "g2", "projectId": 2}]

    def test_incremental_run_passes_start_time_to_every_project(self, monkeypatch: Any) -> None:
        pages = _FakePages(
            {
                ("/api/v4/projects", 1): {"count": 2, "projects": [{"id": 1}, {"id": 2}]},
                ("/api/v4/projects/1/groups", 1): {"count": 1, "groups": [{"id": "g1"}]},
                ("/api/v4/projects/2/groups", 1): {"count": 1, "groups": [{"id": "g2"}]},
            }
        )
        _collect(
            _FakeResumableManager(),
            monkeypatch,
            pages,
            "groups",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        groups_requests = [params for path, params in pages.requests if path.endswith("/groups")]
        assert len(groups_requests) == 2
        for params in groups_requests:
            assert params["start_time"] == "2026-03-04T02:58:14.000Z"
            assert params["order"] == "created"

    def test_resume_skips_projects_before_bookmark_and_reuses_saved_page(self, monkeypatch: Any) -> None:
        pages = _FakePages(
            {
                ("/api/v4/projects", 1): {"count": 3, "projects": [{"id": 1}, {"id": 2}, {"id": 3}]},
                # Project 1 must not be re-fetched; project 2 resumes at page 3.
                ("/api/v4/projects/2/groups", 3): {"count": 999, "groups": [{"id": "g2-p3"}]},
                ("/api/v4/projects/3/groups", 1): {"count": 1, "groups": [{"id": "g3"}]},
            }
        )
        manager = _FakeResumableManager(AirbrakeResumeConfig(page=3, project_id=2))
        rows = _collect(manager, monkeypatch, pages, "groups")
        assert rows == [{"id": "g2-p3"}, {"id": "g3"}]
        fetched_group_paths = [path for path, _params in pages.requests if path.endswith("/groups")]
        assert "/api/v4/projects/1/groups" not in fetched_group_paths

    def test_resume_from_deleted_project_restarts_from_first(self, monkeypatch: Any) -> None:
        pages = _FakePages(
            {
                ("/api/v4/projects", 1): {"count": 1, "projects": [{"id": 1}]},
                ("/api/v4/projects/1/groups", 1): {"count": 1, "groups": [{"id": "g1"}]},
            }
        )
        manager = _FakeResumableManager(AirbrakeResumeConfig(page=5, project_id=999))
        rows = _collect(manager, monkeypatch, pages, "groups")
        assert rows == [{"id": "g1"}]

    def test_state_saved_after_each_page_and_bookmark_advanced_between_projects(self, monkeypatch: Any) -> None:
        pages = _FakePages(
            {
                ("/api/v4/projects", 1): {"count": 2, "projects": [{"id": 1}, {"id": 2}]},
                ("/api/v4/projects/1/groups", 1): {"count": 1, "groups": [{"id": "g1"}]},
                ("/api/v4/projects/2/groups", 1): {"count": 1, "groups": [{"id": "g2"}]},
            }
        )
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, pages, "groups")
        assert manager.saved == [
            AirbrakeResumeConfig(page=2, project_id=1),
            AirbrakeResumeConfig(page=1, project_id=2),
            AirbrakeResumeConfig(page=2, project_id=2),
        ]

    def test_project_deleted_mid_fan_out_is_skipped(self, monkeypatch: Any) -> None:
        pages = _FakePages(
            {
                ("/api/v4/projects", 1): {"count": 2, "projects": [{"id": 1}, {"id": 2}]},
                ("/api/v4/projects/1/groups", 1): requests.HTTPError(response=_response_with_status(404)),
                ("/api/v4/projects/2/groups", 1): {"count": 1, "groups": [{"id": "g2"}]},
            }
        )
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "groups")
        assert rows == [{"id": "g2"}]

    def test_non_404_http_error_propagates(self, monkeypatch: Any) -> None:
        pages = _FakePages(
            {
                ("/api/v4/projects", 1): {"count": 1, "projects": [{"id": 1}]},
                ("/api/v4/projects/1/groups", 1): requests.HTTPError(response=_response_with_status(500)),
            }
        )
        with pytest.raises(requests.HTTPError):
            _collect(_FakeResumableManager(), monkeypatch, pages, "groups")


class TestDeploysFanOut:
    def test_project_id_is_injected_into_deploy_rows(self, monkeypatch: Any) -> None:
        # The Airbrake deploy payload carries no project reference; without injection the table
        # can't be joined back to projects.
        pages = _FakePages(
            {
                ("/api/v4/projects", 1): {"count": 1, "projects": [{"id": 7}]},
                ("/api/v4/projects/7/deploys", 1): {
                    "count": 1,
                    "deploys": [{"environment": "production", "revision": "abc123"}],
                },
            }
        )
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "deploys")
        assert rows == [{"environment": "production", "revision": "abc123", "projectId": 7}]


class TestNoticesFanOut:
    def test_fans_out_per_project_per_group(self, monkeypatch: Any) -> None:
        pages = _FakePages(
            {
                ("/api/v4/projects", 1): {"count": 1, "projects": [{"id": 1}]},
                ("/api/v4/projects/1/groups", 1): {"count": 2, "groups": [{"id": "g1"}, {"id": "g2"}]},
                ("/api/v4/projects/1/groups/g1/notices", 1): {"count": 1, "notices": [{"id": "n1", "groupId": "g1"}]},
                ("/api/v4/projects/1/groups/g2/notices", 1): {"count": 1, "notices": [{"id": "n2", "groupId": "g2"}]},
            }
        )
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "notices")
        assert rows == [{"id": "n1", "groupId": "g1"}, {"id": "n2", "groupId": "g2"}]

    def test_resume_skips_groups_before_bookmark(self, monkeypatch: Any) -> None:
        pages = _FakePages(
            {
                ("/api/v4/projects", 1): {"count": 1, "projects": [{"id": 1}]},
                ("/api/v4/projects/1/groups", 1): {"count": 2, "groups": [{"id": "g1"}, {"id": "g2"}]},
                ("/api/v4/projects/1/groups/g2/notices", 2): {"count": 999, "notices": [{"id": "n2-p2"}]},
            }
        )
        manager = _FakeResumableManager(AirbrakeResumeConfig(page=2, project_id=1, group_id="g2"))
        rows = _collect(manager, monkeypatch, pages, "notices")
        assert rows == [{"id": "n2-p2"}]
        fetched_notice_paths = [path for path, _params in pages.requests if "/notices" in path]
        assert "/api/v4/projects/1/groups/g1/notices" not in fetched_notice_paths

    def test_group_deleted_mid_fan_out_is_skipped(self, monkeypatch: Any) -> None:
        pages = _FakePages(
            {
                ("/api/v4/projects", 1): {"count": 1, "projects": [{"id": 1}]},
                ("/api/v4/projects/1/groups", 1): {"count": 2, "groups": [{"id": "gone"}, {"id": "g2"}]},
                ("/api/v4/projects/1/groups/gone/notices", 1): requests.HTTPError(response=_response_with_status(404)),
                ("/api/v4/projects/1/groups/g2/notices", 1): {"count": 1, "notices": [{"id": "n2"}]},
            }
        )
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "notices")
        assert rows == [{"id": "n2"}]

    def test_per_group_history_is_capped(self, monkeypatch: Any) -> None:
        # One noisy group with unbounded history must not dominate the sync.
        pages = _FakePages(
            {
                ("/api/v4/projects", 1): {"count": 1, "projects": [{"id": 1}]},
                ("/api/v4/projects/1/groups", 1): {"count": 1, "groups": [{"id": "g1"}]},
                **{
                    ("/api/v4/projects/1/groups/g1/notices", page): {"count": 99999, "notices": [{"id": f"n{page}"}]}
                    for page in range(1, NOTICES_MAX_PAGES_PER_GROUP + 50)
                },
            }
        )
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "notices")
        assert len(rows) == NOTICES_MAX_PAGES_PER_GROUP


class TestSourceResponse:
    @parameterized.expand(
        [
            ("projects", ["id"], None),
            ("groups", ["id"], ["createdAt"]),
            ("deploys", None, None),
            ("notices", ["groupId", "id"], ["createdAt"]),
        ]
    )
    def test_primary_and_partition_keys(
        self, endpoint: str, expected_pks: list[str] | None, expected_partition_keys: list[str] | None
    ) -> None:
        # Dropping groupId from the notices key multi-matches merges if notice ids repeat across
        # groups; partitioning on a mutable field rewrites partitions every sync.
        response = airbrake_source(
            api_key="user-key", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=MagicMock()
        )
        assert response.primary_keys == expected_pks
        assert response.partition_keys == expected_partition_keys
        # Watermark persistence must stay deferred to job end: fan-out batches arrive per project,
        # so per-batch asc checkpointing could advance the cursor past projects a crashed run never reached.
        assert response.sort_mode == "desc"


class TestValidateCredentials:
    @parameterized.expand([("valid", 200, True), ("invalid_key", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        with patch.object(airbrake, "make_tracked_session", return_value=session):
            assert validate_credentials("user-key") is expected

    def test_network_error_maps_to_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(airbrake, "make_tracked_session", return_value=session):
            assert validate_credentials("user-key") is False
