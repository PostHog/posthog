from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork import teamwork
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.settings import TEAMWORK_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.teamwork import (
    PAGE_SIZE,
    TeamworkResumeConfig,
    _auth_header,
    _build_params,
    _fetch_page,
    _format_updated_after,
    base_url,
    get_rows,
    normalize_host,
    validate_credentials,
)


class TestNormalizeHost:
    @parameterized.expand(
        [
            ("bare_subdomain", "mycompany", "mycompany.teamwork.com"),
            ("full_host", "mycompany.teamwork.com", "mycompany.teamwork.com"),
            ("https_url", "https://mycompany.teamwork.com/", "mycompany.teamwork.com"),
            ("http_url_with_path", "http://mycompany.teamwork.com/projects", "mycompany.teamwork.com"),
            ("regional_host", "mycompany.eu.teamwork.com", "mycompany.eu.teamwork.com"),
            ("trims_whitespace_and_case", "  MyCompany  ", "mycompany.teamwork.com"),
            ("trailing_dot", "mycompany.teamwork.com.", "mycompany.teamwork.com"),
        ]
    )
    def test_normalize_host(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_host(raw) == expected

    def test_base_url(self) -> None:
        assert base_url("mycompany.teamwork.com") == "https://mycompany.teamwork.com/projects/api/v3"


class TestAuthHeader:
    def test_basic_auth_uses_api_key_as_username(self) -> None:
        import base64

        header = _auth_header("my-secret-key")
        assert header["Accept"] == "application/json"
        scheme, token = header["Authorization"].split(" ", 1)
        assert scheme == "Basic"
        assert base64.b64decode(token).decode() == "my-secret-key:x"


class TestFormatUpdatedAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_updated_after(self, _name: str, value: object, expected: str) -> None:
        assert _format_updated_after(value) == expected

    def test_no_offset_suffix(self) -> None:
        assert "+00:00" not in _format_updated_after(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestBuildParams:
    def test_incremental_endpoint_passes_updated_after_and_asc_sort(self) -> None:
        config = TEAMWORK_ENDPOINTS["tasks"]
        params = _build_params(config, page=1, updated_after="2026-03-04T02:58:14Z")
        assert params == {
            "page": 1,
            "pageSize": PAGE_SIZE,
            "orderBy": "updatedat",
            "orderMode": "asc",
            "updatedAfter": "2026-03-04T02:58:14Z",
        }

    def test_full_refresh_endpoint_has_stable_sort_no_updated_after(self) -> None:
        config = TEAMWORK_ENDPOINTS["projects"]
        params = _build_params(config, page=2, updated_after=None)
        assert params == {"page": 2, "pageSize": PAGE_SIZE, "orderBy": "datecreated", "orderMode": "asc"}

    def test_always_requests_ascending(self) -> None:
        # sort_mode="asc" in SourceResponse trusts the request to ascend; every endpoint must say so.
        for config in TEAMWORK_ENDPOINTS.values():
            params = _build_params(config, page=1, updated_after=None)
            assert params.get("orderMode") == "asc"


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        fake_response = MagicMock()
        fake_response.status_code = status_code
        fake_session = MagicMock()
        fake_session.get.return_value = fake_response
        with patch.object(teamwork, "make_tracked_session", lambda *a, **k: fake_session):
            assert validate_credentials("mycompany.teamwork.com", "key") is expected

    def test_network_error_is_false(self) -> None:
        fake_session = MagicMock()
        fake_session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(teamwork, "make_tracked_session", lambda *a, **k: fake_session):
            assert validate_credentials("mycompany.teamwork.com", "key") is False

    def test_uses_no_redirect_session(self) -> None:
        # The Basic auth header must never follow a redirect off the validated host.
        captured: dict[str, Any] = {}

        def fake_session_factory(*_a: Any, **kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            fake_session = MagicMock()
            fake_session.get.return_value = MagicMock(status_code=200)
            return fake_session

        with patch.object(teamwork, "make_tracked_session", fake_session_factory):
            validate_credentials("mycompany.teamwork.com", "key")
        assert captured["allow_redirects"] is False


class TestFetchPage:
    @staticmethod
    def _fetch(status_code: int) -> dict:
        response = MagicMock()
        response.status_code = status_code
        response.ok = 200 <= status_code < 300
        session = MagicMock()
        session.get.return_value = response
        return _fetch_page(session, "https://mycompany.teamwork.com/x", {}, MagicMock())

    @parameterized.expand([("moved", 301), ("found", 302), ("temporary", 307), ("permanent", 308)])
    def test_redirect_is_rejected(self, _name: str, status_code: int) -> None:
        # A 3xx means the host tried to bounce us elsewhere — refuse rather than forward credentials.
        with pytest.raises(ValueError, match="redirect"):
            self._fetch(status_code)

    def test_hits_me_endpoint(self) -> None:
        captured: dict[str, str] = {}

        def fake_get(url: str, **kwargs: Any) -> MagicMock:
            captured["url"] = url
            resp = MagicMock()
            resp.status_code = 200
            return resp

        fake_session = MagicMock()
        fake_session.get.side_effect = fake_get
        with patch.object(teamwork, "make_tracked_session", lambda *a, **k: fake_session):
            validate_credentials("mycompany.teamwork.com", "key")
        assert captured["url"] == "https://mycompany.teamwork.com/projects/api/v3/me.json"


class _FakeResumableManager:
    def __init__(self, state: TeamworkResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[TeamworkResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> TeamworkResumeConfig | None:
        return self._state

    def save_state(self, data: TeamworkResumeConfig) -> None:
        self.saved.append(data)


def _page(data_key: str, items: list[dict], has_more: bool) -> dict:
    return {data_key: items, "meta": {"page": {"hasMore": has_more}}}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        responses: list[dict],
        endpoint: str = "tasks",
        **kwargs: Any,
    ) -> tuple[list[dict], list[str]]:
        fetched_urls: list[str] = []
        iterator = iter(responses)

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            fetched_urls.append(url)
            return next(iterator)

        monkeypatch.setattr(teamwork, "_fetch_page", fake_fetch)

        rows: list[dict] = []
        for batch in get_rows(
            host="mycompany.teamwork.com",
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(batch)
        return rows, fetched_urls

    def test_single_page(self, monkeypatch: Any) -> None:
        responses = [_page("tasks", [{"id": 1}, {"id": 2}], has_more=False)]
        rows, urls = self._collect(_FakeResumableManager(), monkeypatch, responses)
        assert rows == [{"id": 1}, {"id": 2}]
        assert len(urls) == 1
        assert "page=1" in urls[0]

    def test_follows_pagination_until_has_more_false(self, monkeypatch: Any) -> None:
        responses = [
            _page("tasks", [{"id": 1}], has_more=True),
            _page("tasks", [{"id": 2}], has_more=True),
            _page("tasks", [{"id": 3}], has_more=False),
        ]
        rows, urls = self._collect(_FakeResumableManager(), monkeypatch, responses)
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert ["page=1" in urls[0], "page=2" in urls[1], "page=3" in urls[2]] == [True, True, True]

    def test_stops_on_empty_page(self, monkeypatch: Any) -> None:
        # hasMore lies and says there's more, but an empty page must terminate the loop.
        responses = [_page("tasks", [], has_more=True)]
        rows, urls = self._collect(_FakeResumableManager(), monkeypatch, responses)
        assert rows == []
        assert len(urls) == 1

    def test_saves_state_after_each_yielded_page(self, monkeypatch: Any) -> None:
        responses = [
            _page("tasks", [{"id": 1}], has_more=True),
            _page("tasks", [{"id": 2}], has_more=False),
        ]
        manager = _FakeResumableManager()
        self._collect(manager, monkeypatch, responses)
        # State points at the page just yielded so a crash re-yields it rather than skipping.
        assert manager.saved == [
            TeamworkResumeConfig(page=1, updated_after=None),
            TeamworkResumeConfig(page=2, updated_after=None),
        ]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        responses = [_page("tasks", [{"id": 7}], has_more=False)]
        manager = _FakeResumableManager(TeamworkResumeConfig(page=3, updated_after="2026-01-01T00:00:00Z"))
        rows, urls = self._collect(manager, monkeypatch, responses)
        assert rows == [{"id": 7}]
        assert "page=3" in urls[0]
        assert "updatedAfter=2026-01-01T00%3A00%3A00Z" in urls[0]

    def test_incremental_builds_updated_after_from_last_value(self, monkeypatch: Any) -> None:
        responses = [_page("tasks", [{"id": 1}], has_more=False)]
        rows, urls = self._collect(
            _FakeResumableManager(),
            monkeypatch,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert "updatedAfter=2026-03-04T02%3A58%3A14Z" in urls[0]
        assert "orderBy=updatedat" in urls[0]

    def test_full_refresh_endpoint_never_sends_updated_after(self, monkeypatch: Any) -> None:
        responses = [_page("projects", [{"id": 1}], has_more=False)]
        _, urls = self._collect(
            _FakeResumableManager(),
            monkeypatch,
            responses,
            endpoint="projects",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert "updatedAfter" not in urls[0]

    def test_reads_endpoint_specific_data_key(self, monkeypatch: Any) -> None:
        # `time.json` returns rows under "timelogs", not "time".
        responses = [_page("timelogs", [{"id": 99}], has_more=False)]
        rows, _ = self._collect(_FakeResumableManager(), monkeypatch, responses, endpoint="timelogs")
        assert rows == [{"id": 99}]

    def test_stops_at_page_cap(self, monkeypatch: Any) -> None:
        # Every page claims hasMore=True forever; the MAX_PAGES cap must break the loop.
        def always_more(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            return _page("tasks", [{"id": 1}], has_more=True)

        monkeypatch.setattr(teamwork, "_fetch_page", always_more)
        batches = list(
            get_rows(
                host="mycompany.teamwork.com",
                api_key="key",
                endpoint="tasks",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
        )
        assert len(batches) == teamwork.MAX_PAGES


class TestEndpointCatalog:
    def test_every_endpoint_has_id_primary_key(self) -> None:
        for config in TEAMWORK_ENDPOINTS.values():
            assert config.primary_keys == ["id"]

    def test_partition_keys_are_creation_fields_not_update_fields(self) -> None:
        # An update-timestamp partition key would rewrite partitions every sync.
        for config in TEAMWORK_ENDPOINTS.values():
            if config.partition_key is not None:
                assert "updated" not in config.partition_key.lower()
                assert "edited" not in config.partition_key.lower()

    def test_incremental_endpoints_sort_by_an_update_field(self) -> None:
        # If we filter by updatedAfter we must also sort by the update field, or sort_mode="asc" lies.
        for config in TEAMWORK_ENDPOINTS.values():
            if config.incremental_field is not None:
                assert config.order_by is not None
                assert "updated" in config.order_by.lower()

    @parameterized.expand(
        [
            ("projects", "projects", "/projects.json"),
            ("tasks", "tasks", "/tasks.json"),
            ("tasklists", "tasklists", "/tasklists.json"),
            ("milestones", "milestones", "/milestones.json"),
            ("timelogs", "timelogs", "/time.json"),
            ("people", "people", "/people.json"),
            ("companies", "companies", "/companies.json"),
            ("tags", "tags", "/tags.json"),
            ("comments", "comments", "/comments.json"),
        ]
    )
    def test_endpoint_paths_and_keys(self, name: str, data_key: str, path: str) -> None:
        config = TEAMWORK_ENDPOINTS[name]
        assert config.data_key == data_key
        assert config.path == path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
