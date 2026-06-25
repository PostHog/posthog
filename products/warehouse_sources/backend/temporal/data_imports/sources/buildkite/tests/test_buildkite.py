from datetime import UTC, date, datetime
from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite import buildkite
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.buildkite import (
    CHUNK_SIZE,
    PAGE_SIZE,
    BuildkiteResumeConfig,
    _build_initial_params,
    _build_initial_url,
    _format_incremental_value,
    _parse_next_url,
    buildkite_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.settings import BUILDKITE_ENDPOINTS


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestParseNextUrl:
    def test_returns_next_url(self) -> None:
        header = (
            '<https://api.buildkite.com/v2/organizations/o/builds?page=2&per_page=100>; rel="next", '
            '<https://api.buildkite.com/v2/organizations/o/builds?page=5&per_page=100>; rel="last"'
        )
        assert _parse_next_url(header) == "https://api.buildkite.com/v2/organizations/o/builds?page=2&per_page=100"

    def test_last_page_has_no_next(self) -> None:
        header = '<https://api.buildkite.com/v2/organizations/o/builds?page=1&per_page=100>; rel="prev"'
        assert _parse_next_url(header) is None

    def test_empty_header(self) -> None:
        assert _parse_next_url("") is None


class TestBuildInitialParams:
    def test_builds_incremental_maps_to_created_from(self) -> None:
        params = _build_initial_params(
            BUILDKITE_ENDPOINTS["builds"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert params["per_page"] == buildkite.PAGE_SIZE
        assert params["created_from"] == "2026-03-04T02:58:14+00:00"

    def test_builds_full_refresh_has_no_filter(self) -> None:
        params = _build_initial_params(
            BUILDKITE_ENDPOINTS["builds"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {"per_page": buildkite.PAGE_SIZE}

    @parameterized.expand([("organizations",), ("pipelines",), ("agents",)])
    def test_full_refresh_endpoints_never_get_a_time_filter(self, endpoint: str) -> None:
        # These endpoints expose no server-side timestamp filter, so an incremental request must
        # not silently add one (it would be ignored by the API and misrepresent the sync).
        params = _build_initial_params(
            BUILDKITE_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert params == {"per_page": buildkite.PAGE_SIZE}


class TestBuildInitialUrl:
    def test_org_scoped_path_is_formatted(self) -> None:
        url = _build_initial_url(BUILDKITE_ENDPOINTS["builds"], "my-org", {"per_page": 100})
        assert url == "https://api.buildkite.com/v2/organizations/my-org/builds?per_page=100"

    def test_non_org_scoped_path_ignores_placeholder(self) -> None:
        url = _build_initial_url(BUILDKITE_ENDPOINTS["organizations"], "my-org", {"per_page": 100})
        assert url == "https://api.buildkite.com/v2/organizations?per_page=100"


class _FakeResponse:
    def __init__(self, status_code: int, body: Any, link: str = "") -> None:
        self.status_code = status_code
        self._body = body
        self.headers = {"Link": link} if link else {}
        self.text = ""

    def json(self) -> Any:
        return self._body


class TestValidateCredentials:
    @staticmethod
    def _patch_get(monkeypatch: Any, response: _FakeResponse) -> dict[str, str]:
        captured: dict[str, str] = {}

        def fake_get(url: str, headers: dict[str, str], timeout: int) -> _FakeResponse:
            captured["url"] = url
            return response

        session = MagicMock()
        session.get = fake_get
        monkeypatch.setattr(buildkite, "make_tracked_session", lambda *a, **k: session)
        return captured

    def test_success(self, monkeypatch: Any) -> None:
        self._patch_get(monkeypatch, _FakeResponse(200, {"slug": "my-org"}))
        assert validate_credentials("bkua", "my-org") == (True, None)

    def test_invalid_token(self, monkeypatch: Any) -> None:
        self._patch_get(monkeypatch, _FakeResponse(401, {"message": "Authentication required"}))
        ok, error = validate_credentials("bkua", "my-org")
        assert ok is False
        assert error is not None and "invalid" in error.lower()

    def test_forbidden_accepted_at_source_create(self, monkeypatch: Any) -> None:
        # A valid token may lack read_organizations while still holding the per-endpoint scopes the
        # user wants — so a 403 at source-create (schema_name=None) must not block connecting.
        self._patch_get(monkeypatch, _FakeResponse(403, {"message": "Forbidden"}))
        assert validate_credentials("bkua", "my-org") == (True, None)

    def test_forbidden_rejected_for_specific_schema(self, monkeypatch: Any) -> None:
        self._patch_get(monkeypatch, _FakeResponse(403, {"message": "Forbidden"}))
        ok, error = validate_credentials("bkua", "my-org", schema_name="builds")
        assert ok is False
        assert error is not None and "builds" in error

    def test_org_not_found(self, monkeypatch: Any) -> None:
        self._patch_get(monkeypatch, _FakeResponse(404, {"message": "Not Found"}))
        ok, error = validate_credentials("bkua", "missing-org")
        assert ok is False
        assert error is not None and "missing-org" in error

    def test_schema_probe_targets_endpoint_path(self, monkeypatch: Any) -> None:
        captured = self._patch_get(monkeypatch, _FakeResponse(200, []))
        validate_credentials("bkua", "my-org", schema_name="agents")
        assert captured["url"] == "https://api.buildkite.com/v2/organizations/my-org/agents?per_page=1"


class _FakeResumableManager:
    def __init__(self, state: BuildkiteResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[BuildkiteResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> BuildkiteResumeConfig | None:
        return self._state

    def save_state(self, data: BuildkiteResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    monkeypatch: Any, manager: _FakeResumableManager, pages: dict[str, _FakeResponse], **kwargs: Any
) -> tuple[list[dict], list[str]]:
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> _FakeResponse:
        fetched.append(url)
        return pages[url]

    monkeypatch.setattr(buildkite, "make_tracked_session", lambda *a, **k: MagicMock())
    monkeypatch.setattr(buildkite, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for table in get_rows(
        api_access_token="bkua",
        organization="my-org",
        endpoint=kwargs.pop("endpoint", "pipelines"),
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(table.to_pylist())
    return rows, fetched


class TestGetRows:
    def test_follows_link_header_pagination(self, monkeypatch: Any) -> None:
        page1 = "https://api.buildkite.com/v2/organizations/my-org/pipelines?per_page=100"
        page2 = "https://api.buildkite.com/v2/organizations/my-org/pipelines?page=2&per_page=100"
        pages = {
            page1: _FakeResponse(200, [{"id": "p1"}, {"id": "p2"}], link=f'<{page2}>; rel="next"'),
            page2: _FakeResponse(200, [{"id": "p3"}]),
        }
        rows, fetched = _collect(monkeypatch, _FakeResumableManager(), pages, endpoint="pipelines")
        assert [r["id"] for r in rows] == ["p1", "p2", "p3"]
        assert fetched == [page1, page2]

    def test_stops_on_empty_page(self, monkeypatch: Any) -> None:
        page1 = "https://api.buildkite.com/v2/organizations/my-org/agents?per_page=100"
        pages = {page1: _FakeResponse(200, [])}
        rows, fetched = _collect(monkeypatch, _FakeResumableManager(), pages, endpoint="agents")
        assert rows == []
        assert fetched == [page1]

    def test_resumes_from_saved_state(self, monkeypatch: Any) -> None:
        resume_url = "https://api.buildkite.com/v2/organizations/my-org/pipelines?page=3&per_page=100"
        pages = {resume_url: _FakeResponse(200, [{"id": "p9"}])}
        manager = _FakeResumableManager(BuildkiteResumeConfig(next_url=resume_url))
        rows, fetched = _collect(monkeypatch, manager, pages, endpoint="pipelines")
        # Resume must start at the saved URL, not the freshly-built first-page URL.
        assert fetched == [resume_url]
        assert [r["id"] for r in rows] == ["p9"]

    def test_saves_state_after_yielding_a_batch(self, monkeypatch: Any) -> None:
        # Mirror the real API contract: Buildkite caps per_page at PAGE_SIZE, so the batcher only
        # reaches its CHUNK_SIZE buffer after CHUNK_SIZE / PAGE_SIZE consecutive full pages. State is
        # saved at that page boundary, pointing at the NEXT page, so a crash re-yields the last page
        # rather than skipping it. CHUNK_SIZE must be a multiple of PAGE_SIZE for this to hold.
        assert CHUNK_SIZE % PAGE_SIZE == 0
        full_pages = CHUNK_SIZE // PAGE_SIZE

        base = "https://api.buildkite.com/v2/organizations/my-org/builds?per_page=100"

        def page_url(n: int) -> str:
            return base if n == 1 else f"{base}&page={n}"

        # full_pages pages of PAGE_SIZE items each fill exactly one chunk; the boundary page after
        # them holds the final straggler row.
        boundary_page = page_url(full_pages + 1)
        pages = {
            page_url(n): _FakeResponse(
                200,
                [{"id": f"b{(n - 1) * PAGE_SIZE + i}"} for i in range(PAGE_SIZE)],
                link=f'<{page_url(n + 1)}>; rel="next"',
            )
            for n in range(1, full_pages + 1)
        }
        pages[boundary_page] = _FakeResponse(200, [{"id": "b-last"}])

        manager = _FakeResumableManager()
        rows, _fetched = _collect(monkeypatch, manager, pages, endpoint="builds")
        assert len(rows) == CHUNK_SIZE + 1
        assert manager.saved == [BuildkiteResumeConfig(next_url=boundary_page)]


class TestBuildkiteSourceResponse:
    @parameterized.expand(
        [
            ("organizations", ["id"], "asc", "created_at"),
            ("pipelines", ["id"], "asc", "created_at"),
            ("builds", ["id"], "desc", "created_at"),
            ("agents", ["id"], "asc", "created_at"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], sort_mode: str, partition_key: str
    ) -> None:
        response = buildkite_source(
            api_access_token="bkua",
            organization="my-org",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
