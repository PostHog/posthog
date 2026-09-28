import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.doppler import doppler
from products.warehouse_sources.backend.temporal.data_imports.sources.doppler.doppler import (
    DopplerResumeConfig,
    _coerce_watermark,
    doppler_source,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.doppler.settings import DEFAULT_PER_PAGE

_BASE = "https://api.doppler.com/v3"


class _FakeResumableManager:
    def __init__(self, state: DopplerResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[DopplerResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> DopplerResumeConfig | None:
        return self._state

    def save_state(self, data: DopplerResumeConfig) -> None:
        self.saved.append(data)


def _patch_fetch(monkeypatch: Any, pages: dict[str, Any]) -> list[str]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        fetched.append(url)
        return pages[url]

    monkeypatch.setattr(doppler, "_fetch_page", fake_fetch)
    return fetched


def _collect(manager: _FakeResumableManager, **kwargs: Any) -> list[dict]:
    rows: list[dict] = []
    for batch in get_rows(
        api_token="token",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(batch)
    return rows


def _items(key: str, ids: list[str]) -> dict[str, Any]:
    return {key: [{"id": item_id, "created_at": "2024-01-05T00:00:00.000Z"} for item_id in ids], "page": 1}


def _full_page(key: str, prefix: str) -> dict[str, Any]:
    return _items(key, [f"{prefix}{i}" for i in range(DEFAULT_PER_PAGE)])


class TestCoerceWatermark:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2024, 1, 2, tzinfo=UTC), datetime(2024, 1, 2, tzinfo=UTC)),
            ("naive_datetime", datetime(2024, 1, 2), datetime(2024, 1, 2, tzinfo=UTC)),
            ("date_value", date(2024, 1, 2), datetime(2024, 1, 2, tzinfo=UTC)),
            ("z_string", "2024-01-02T00:00:00.000Z", datetime(2024, 1, 2, tzinfo=UTC)),
            ("offset_string", "2024-01-02T00:00:00+00:00", datetime(2024, 1, 2, tzinfo=UTC)),
            ("bad_string", "not-a-date", None),
            ("none", None, None),
        ]
    )
    def test_coerce(self, _name: str, value: Any, expected: datetime | None) -> None:
        result = _coerce_watermark(value)
        assert result == expected
        # Doppler rows carry aware timestamps; a naive watermark would raise on comparison.
        if result is not None:
            assert result.tzinfo is not None


class TestGetRows:
    def test_paginates_until_short_page(self, monkeypatch: Any) -> None:
        pages = {
            f"{_BASE}/projects?page=1&per_page=20": _full_page("projects", "a"),
            f"{_BASE}/projects?page=2&per_page=20": _items("projects", ["last"]),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()

        rows = _collect(manager, endpoint="projects")

        assert len(rows) == DEFAULT_PER_PAGE + 1
        assert fetched == list(pages)
        # State is saved only while more pages remain, never on the last page.
        assert manager.saved == [DopplerResumeConfig(next_page=2)]

    def test_stops_on_empty_page(self, monkeypatch: Any) -> None:
        pages = {f"{_BASE}/projects?page=1&per_page=20": _items("projects", [])}
        fetched = _patch_fetch(monkeypatch, pages)

        rows = _collect(_FakeResumableManager(), endpoint="projects")

        assert rows == []
        assert fetched == [f"{_BASE}/projects?page=1&per_page=20"]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        pages = {f"{_BASE}/projects?page=3&per_page=20": _items("projects", ["p1"])}
        fetched = _patch_fetch(monkeypatch, pages)

        rows = _collect(_FakeResumableManager(DopplerResumeConfig(next_page=3)), endpoint="projects")

        assert [r["id"] for r in rows] == ["p1"]
        assert fetched == [f"{_BASE}/projects?page=3&per_page=20"]

    @pytest.mark.parametrize(
        "endpoint, url",
        [
            ("project_roles", f"{_BASE}/projects/roles"),
            ("workplace_roles", f"{_BASE}/workplace/roles"),
        ],
    )
    def test_unpaginated_endpoint_makes_one_unparameterised_request(
        self, monkeypatch: Any, endpoint: str, url: str
    ) -> None:
        # The roles endpoints take no pagination params, so a full-looking page must not send the
        # loop round again — there is no short or empty page coming to stop it.
        pages = {url: _items("roles", [f"r{i}" for i in range(DEFAULT_PER_PAGE)])}
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()

        rows = _collect(manager, endpoint=endpoint)

        assert len(rows) == DEFAULT_PER_PAGE
        assert fetched == [url]
        assert manager.saved == []

    def test_endpoint_without_per_page_terminates_on_empty_page(self, monkeypatch: Any) -> None:
        # workplace users documents no `per_page`, so a short page must NOT stop pagination —
        # only an empty page does.
        pages = {
            f"{_BASE}/workplace/users?page=1": _items("workplace_users", ["u1", "u2"]),
            f"{_BASE}/workplace/users?page=2": _items("workplace_users", []),
        }
        fetched = _patch_fetch(monkeypatch, pages)

        rows = _collect(_FakeResumableManager(), endpoint="workplace_users")

        assert [r["id"] for r in rows] == ["u1", "u2"]
        assert fetched == list(pages)


class TestGetRowsIncremental:
    def _log(self, log_id: str, created_at: str | None) -> dict[str, Any]:
        return {"id": log_id, "created_at": created_at}

    def test_stops_paging_at_watermark_and_drops_synced_rows(self, monkeypatch: Any) -> None:
        watermark = datetime(2024, 1, 2, tzinfo=UTC)
        fresh_page = {
            "logs": [self._log(f"l{i}", "2024-01-05T00:00:00.000Z") for i in range(DEFAULT_PER_PAGE)],
        }
        boundary_page = {
            "logs": [
                self._log("new", "2024-01-03T00:00:00.000Z"),
                self._log("unparseable", None),  # kept — merge dedupes on the primary key
                self._log("at_watermark", "2024-01-02T00:00:00.000Z"),  # already synced
                self._log("old", "2024-01-01T00:00:00.000Z"),
            ],
        }
        pages = {
            f"{_BASE}/logs?page=1&per_page=20": fresh_page,
            f"{_BASE}/logs?page=2&per_page=20": boundary_page,
        }
        fetched = _patch_fetch(monkeypatch, pages)

        rows = _collect(
            _FakeResumableManager(),
            endpoint="activity_logs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        # Rows at/before the watermark are dropped, and paging stops at the boundary page even
        # though it isn't the last one — no page 3 request.
        assert [r["id"] for r in rows] == [f"l{i}" for i in range(DEFAULT_PER_PAGE)] + ["new", "unparseable"]
        assert fetched == list(pages)

    def test_first_sync_without_watermark_walks_all_pages(self, monkeypatch: Any) -> None:
        pages = {
            f"{_BASE}/logs?page=1&per_page=20": _full_page("logs", "l"),
            f"{_BASE}/logs?page=2&per_page=20": _items("logs", ["last"]),
        }
        fetched = _patch_fetch(monkeypatch, pages)

        rows = _collect(
            _FakeResumableManager(),
            endpoint="activity_logs",
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert len(rows) == DEFAULT_PER_PAGE + 1
        assert fetched == list(pages)


class TestGetRowsFanOut:
    _PROJECTS_URL = f"{_BASE}/projects?page=1&per_page=20"

    def _projects_page(self, slugs: list[str]) -> dict[str, Any]:
        return {"projects": [{"id": f"id-{slug}", "slug": slug} for slug in slugs]}

    def test_fans_out_over_every_project_and_bookmarks_progress(self, monkeypatch: Any) -> None:
        pages = {
            self._PROJECTS_URL: self._projects_page(["proj-a", "proj-b"]),
            f"{_BASE}/configs?project=proj-a&page=1&per_page=20": _full_page("configs", "a"),
            f"{_BASE}/configs?project=proj-a&page=2&per_page=20": _items("configs", ["a-last"]),
            f"{_BASE}/configs?project=proj-b&page=1&per_page=20": _items("configs", ["b0"]),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()

        rows = _collect(manager, endpoint="configs")

        assert len(rows) == DEFAULT_PER_PAGE + 2
        assert fetched == list(pages)
        assert manager.saved == [
            DopplerResumeConfig(next_page=2, project="proj-a"),
            DopplerResumeConfig(next_page=1, project="proj-b"),
        ]

    def test_resumes_from_bookmarked_project_and_page(self, monkeypatch: Any) -> None:
        pages = {
            self._PROJECTS_URL: self._projects_page(["proj-a", "proj-b"]),
            f"{_BASE}/configs?project=proj-b&page=2&per_page=20": _items("configs", ["b-page2"]),
        }
        fetched = _patch_fetch(monkeypatch, pages)

        rows = _collect(_FakeResumableManager(DopplerResumeConfig(next_page=2, project="proj-b")), endpoint="configs")

        # proj-a is skipped entirely; proj-b picks up at its saved page.
        assert [r["id"] for r in rows] == ["b-page2"]
        assert fetched == list(pages)

    def test_restarts_when_bookmarked_project_no_longer_exists(self, monkeypatch: Any) -> None:
        pages = {
            self._PROJECTS_URL: self._projects_page(["proj-a"]),
            f"{_BASE}/configs?project=proj-a&page=1&per_page=20": _items("configs", ["a0"]),
        }
        fetched = _patch_fetch(monkeypatch, pages)

        rows = _collect(
            _FakeResumableManager(DopplerResumeConfig(next_page=4, project="deleted-project")), endpoint="configs"
        )

        assert [r["id"] for r in rows] == ["a0"]
        assert fetched == list(pages)

    def test_unpaginated_fan_out_makes_one_request_per_project(self, monkeypatch: Any) -> None:
        # /v3/environments takes no pagination params; one request per project, no page loop.
        pages = {
            self._PROJECTS_URL: self._projects_page(["proj-a", "proj-b"]),
            f"{_BASE}/environments?project=proj-a": _items("environments", ["dev", "prd"]),
            f"{_BASE}/environments?project=proj-b": _items("environments", ["dev"]),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()

        rows = _collect(manager, endpoint="environments")

        assert [r["id"] for r in rows] == ["dev", "prd", "dev"]
        assert fetched == list(pages)
        assert manager.saved == [DopplerResumeConfig(next_page=1, project="proj-b")]


class TestGetRowsProjectMemberFanOut:
    def test_stamps_the_project_onto_rows_that_omit_it(self, monkeypatch: Any) -> None:
        # Member rows carry no project of their own, and `project` leads the primary key — an
        # unstamped row would collide with the same member in every other project.
        pages = {
            f"{_BASE}/projects?page=1&per_page=20": {"projects": [{"slug": "proj-a"}, {"slug": "proj-b"}]},
            f"{_BASE}/projects/project/members?project=proj-a&page=1&per_page=20": {
                "members": [{"type": "workplace_user", "slug": "user-1"}]
            },
            f"{_BASE}/projects/project/members?project=proj-b&page=1&per_page=20": {
                "members": [{"type": "workplace_user", "slug": "user-1"}]
            },
        }
        fetched = _patch_fetch(monkeypatch, pages)

        rows = _collect(_FakeResumableManager(), endpoint="project_members")

        assert [(row["project"], row["slug"]) for row in rows] == [("proj-a", "user-1"), ("proj-b", "user-1")]
        assert fetched == list(pages)


class TestGetRowsConfigFanOut:
    _PROJECTS_URL = f"{_BASE}/projects?page=1&per_page=20"

    def _logs_url(self, project: str, config: str, page: int = 1) -> str:
        return f"{_BASE}/configs/config/logs?project={project}&config={config}&page={page}&per_page=20"

    def test_fans_out_over_every_config_of_every_project(self, monkeypatch: Any) -> None:
        pages = {
            self._PROJECTS_URL: {"projects": [{"slug": "proj-a"}, {"slug": "proj-b"}]},
            f"{_BASE}/configs?project=proj-a&page=1&per_page=20": {"configs": [{"name": "dev"}, {"name": "prd"}]},
            f"{_BASE}/configs?project=proj-b&page=1&per_page=20": {"configs": [{"name": "dev"}]},
            self._logs_url("proj-a", "dev"): _items("logs", ["a-dev"]),
            self._logs_url("proj-a", "prd"): _items("logs", ["a-prd"]),
            self._logs_url("proj-b", "dev"): _items("logs", ["b-dev"]),
        }
        fetched = _patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()

        rows = _collect(manager, endpoint="config_logs")

        assert [row["id"] for row in rows] == ["a-dev", "a-prd", "b-dev"]
        # Both fan-out levels are resolved up front, so every parent listing precedes the logs.
        assert fetched == list(pages)
        # The bookmark carries the config too; a project-only bookmark would restart the project.
        assert manager.saved == [
            DopplerResumeConfig(next_page=1, project="proj-a", config="prd"),
            DopplerResumeConfig(next_page=1, project="proj-b", config="dev"),
        ]

    def test_drops_secret_values_from_the_diff(self, monkeypatch: Any) -> None:
        # Doppler puts the plaintext before and after value of every changed secret in `diff`.
        # Yielding the field as returned would write live credentials into the warehouse.
        log = {
            "id": "log-1",
            "created_at": "2024-01-05T00:00:00.000Z",
            "diff": [
                {"name": "STRIPE", "added": "sk_test_notarealkey"},
                {"name": "OLD_TOKEN", "removed": "tok_notarealtoken"},
                {"name": "ROTATED", "added": "new_value", "removed": "old_value"},
            ],
        }
        pages = {
            self._PROJECTS_URL: {"projects": [{"slug": "proj-a"}]},
            f"{_BASE}/configs?project=proj-a&page=1&per_page=20": {"configs": [{"name": "dev"}]},
            self._logs_url("proj-a", "dev"): {"logs": [log]},
        }
        _patch_fetch(monkeypatch, pages)

        rows = _collect(_FakeResumableManager(), endpoint="config_logs")

        assert [row["diff"] for row in rows] == [
            [
                {"name": "STRIPE", "added": True, "removed": False},
                {"name": "OLD_TOKEN", "added": False, "removed": True},
                {"name": "ROTATED", "added": True, "removed": True},
            ]
        ]
        assert "sk_test_notarealkey" not in json.dumps(rows)

    def test_resumes_from_the_bookmarked_config(self, monkeypatch: Any) -> None:
        pages = {
            self._PROJECTS_URL: {"projects": [{"slug": "proj-a"}, {"slug": "proj-b"}]},
            f"{_BASE}/configs?project=proj-a&page=1&per_page=20": {"configs": [{"name": "dev"}, {"name": "prd"}]},
            f"{_BASE}/configs?project=proj-b&page=1&per_page=20": {"configs": [{"name": "dev"}]},
            self._logs_url("proj-a", "prd", page=2): _items("logs", ["a-prd-page2"]),
            self._logs_url("proj-b", "dev"): _items("logs", ["b-dev"]),
        }
        fetched = _patch_fetch(monkeypatch, pages)

        rows = _collect(
            _FakeResumableManager(DopplerResumeConfig(next_page=2, project="proj-a", config="prd")),
            endpoint="config_logs",
        )

        # proj-a/dev is skipped entirely; proj-a/prd picks up at its saved page.
        assert [row["id"] for row in rows] == ["a-prd-page2", "b-dev"]
        assert fetched == list(pages)


class TestDopplerSourceResponse:
    @parameterized.expand(
        [
            ("projects", ["id"], "asc", None),
            ("environments", ["project", "id"], "asc", None),
            ("configs", ["project", "name"], "asc", None),
            ("activity_logs", ["id"], "desc", ["created_at"]),
            ("workplace_users", ["id"], "asc", None),
            ("groups", ["slug"], "asc", None),
            ("service_accounts", ["slug"], "asc", None),
            ("invites", ["slug"], "asc", None),
            ("project_members", ["project", "type", "slug"], "asc", None),
            ("project_roles", ["identifier"], "asc", None),
            ("workplace_roles", ["identifier"], "asc", None),
            ("config_logs", ["project", "config", "id"], "asc", ["created_at"]),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], sort_mode: str, partition_keys: list[str] | None
    ) -> None:
        response = doppler_source(
            api_token="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_keys == partition_keys
