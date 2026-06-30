from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh import codefresh
from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.codefresh import (
    CodefreshResumeConfig,
    _extract_items,
    _flatten,
    _iter_offset,
    _iter_page,
    _transform_row,
    codefresh_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.settings import (
    CODEFRESH_ENDPOINTS,
    CodefreshEndpointConfig,
)


class _FakeResumableManager:
    def __init__(self, state: CodefreshResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[CodefreshResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> CodefreshResumeConfig | None:
        return self._state

    def save_state(self, data: CodefreshResumeConfig) -> None:
        self.saved.append(data)


def _fetch_stub(pages: dict[str, Any], captured_headers: list[dict[str, str]] | None = None):
    """Build a `_fetch_page` replacement that returns canned bodies keyed by URL."""

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
        if captured_headers is not None:
            captured_headers.append(dict(headers))
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    return fake_fetch


class TestExtractItems:
    @parameterized.expand(
        [
            ("bare_array", [{"id": "1"}, {"id": "2"}], None, [{"id": "1"}, {"id": "2"}]),
            ("docs_envelope", {"docs": [{"id": "1"}], "count": 1}, ["docs"], [{"id": "1"}]),
            (
                "nested_workflows_docs",
                {"workflows": {"docs": [{"id": "b1"}]}, "pagination": {}},
                ["workflows", "docs"],
                [{"id": "b1"}],
            ),
            ("missing_key_returns_empty", {"other": []}, ["docs"], []),
            ("non_list_value_returns_empty", {"docs": {"not": "a list"}}, ["docs"], []),
            ("bare_array_on_non_list_returns_empty", {"docs": []}, None, []),
        ]
    )
    def test_extract_items(self, _name: str, data: Any, data_key: list[str] | None, expected: list) -> None:
        assert _extract_items(data, data_key) == expected


class TestFlatten:
    def test_lifts_nested_object_to_top_level(self) -> None:
        item = {"metadata": {"id": "p1", "name": "build-and-test"}, "spec": {"steps": {}}}
        result = _flatten(item, "metadata")
        assert result["id"] == "p1"
        assert result["name"] == "build-and-test"
        assert result["spec"] == {"steps": {}}
        assert "metadata" not in result

    def test_top_level_field_wins_on_clash(self) -> None:
        item = {"metadata": {"id": "from_metadata"}, "id": "top_level"}
        assert _flatten(item, "metadata")["id"] == "top_level"

    def test_no_flatten_key_is_passthrough(self) -> None:
        item = {"id": "1", "created": "2026-01-01"}
        assert _flatten(item, None) == item

    def test_flatten_key_absent_is_passthrough(self) -> None:
        item = {"id": "1"}
        assert _flatten(item, "metadata") == item


class TestTransformRow:
    @parameterized.expand(
        [
            (
                "top_level_key",
                ["variables"],
                {"id": "p1", "variables": [{"key": "TOKEN", "value": "secret"}]},
                {"id": "p1"},
            ),
            (
                "nested_dotted_key",
                ["spec.variables"],
                {"id": "p1", "spec": {"steps": {}, "variables": [{"key": "TOKEN", "value": "secret"}]}},
                {"id": "p1", "spec": {"steps": {}}},
            ),
            (
                "nested_path_absent_is_noop",
                ["spec.variables"],
                {"id": "p1", "spec": {"steps": {}}},
                {"id": "p1", "spec": {"steps": {}}},
            ),
            (
                "nested_parent_not_a_dict_is_noop",
                ["spec.variables"],
                {"id": "p1", "spec": None},
                {"id": "p1", "spec": None},
            ),
        ]
    )
    def test_redacts_configured_keys(
        self, _name: str, redact_keys: list[str], item: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        config = CodefreshEndpointConfig(
            name="projects", path="/projects", pagination="offset", redact_keys=redact_keys
        )
        assert _transform_row(item, config) == expected

    def test_redaction_does_not_mutate_source_item(self) -> None:
        config = CodefreshEndpointConfig(
            name="pipelines", path="/pipelines", pagination="offset", redact_keys=["spec.variables"]
        )
        item = {"id": "p1", "spec": {"variables": [{"key": "TOKEN", "value": "secret"}]}}
        _transform_row(item, config)
        assert item["spec"] == {"variables": [{"key": "TOKEN", "value": "secret"}]}

    def test_no_redact_keys_is_passthrough(self) -> None:
        config = CodefreshEndpointConfig(name="builds", path="/workflow", pagination="page")
        row = _transform_row({"id": "b1", "variables": ["x"]}, config)
        assert row == {"id": "b1", "variables": ["x"]}

    @parameterized.expand(
        [
            ("projects", "variables"),
            ("pipelines", "spec.variables"),
            ("triggers", "event-data.endpoint"),
            ("triggers", "event-data.secret"),
        ]
    )
    def test_endpoint_redacts_secret_bearing_variables(self, endpoint: str, redacted_key: str) -> None:
        # These endpoints expose plaintext config/CI variables or webhook secrets; the configured
        # source must strip them.
        assert redacted_key in CODEFRESH_ENDPOINTS[endpoint].redact_keys


def _offset_config(page_size: int = 2) -> CodefreshEndpointConfig:
    return CodefreshEndpointConfig(
        name="projects", path="/projects", pagination="offset", data_key=None, page_size=page_size
    )


class TestOffsetPagination:
    def test_short_first_page_stops_without_saving(self, monkeypatch: Any) -> None:
        config = _offset_config(page_size=2)
        pages = {"https://g.codefresh.io/api/projects?limit=2&offset=0": [{"id": "1"}]}
        monkeypatch.setattr(codefresh, "_fetch_page", _fetch_stub(pages))
        manager = _FakeResumableManager()

        batches = list(_iter_offset(MagicMock(), config, {}, MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"id": "1"}]]
        # A short page is the last page — nothing left to resume to, so no state is saved.
        assert manager.saved == []

    def test_full_page_then_short_page_paginates_and_saves(self, monkeypatch: Any) -> None:
        config = _offset_config(page_size=2)
        pages = {
            "https://g.codefresh.io/api/projects?limit=2&offset=0": [{"id": "1"}, {"id": "2"}],
            "https://g.codefresh.io/api/projects?limit=2&offset=2": [{"id": "3"}],
        }
        monkeypatch.setattr(codefresh, "_fetch_page", _fetch_stub(pages))
        manager = _FakeResumableManager()

        batches = list(_iter_offset(MagicMock(), config, {}, MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"id": "1"}, {"id": "2"}], [{"id": "3"}]]
        # State saved exactly once, after the first (full) page is yielded, pointing at the next offset.
        assert manager.saved == [CodefreshResumeConfig(offset=2)]

    def test_resume_starts_from_saved_offset(self, monkeypatch: Any) -> None:
        config = _offset_config(page_size=2)
        pages = {"https://g.codefresh.io/api/projects?limit=2&offset=4": [{"id": "5"}]}
        monkeypatch.setattr(codefresh, "_fetch_page", _fetch_stub(pages))
        manager = _FakeResumableManager(CodefreshResumeConfig(offset=4))

        batches = list(_iter_offset(MagicMock(), config, {}, MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"id": "5"}]]


def _page_config(page_size: int = 2) -> CodefreshEndpointConfig:
    return CodefreshEndpointConfig(
        name="builds",
        path="/workflow",
        pagination="page",
        data_key=["workflows", "docs"],
        page_size=page_size,
    )


class TestPagePagination:
    def test_follows_next_page_and_forwards_session_id(self, monkeypatch: Any) -> None:
        config = _page_config(page_size=2)
        pages = {
            "https://g.codefresh.io/api/workflow?limit=2&page=1": {
                "workflows": {"docs": [{"id": "b1"}, {"id": "b2"}]},
                "pagination": {"sessionId": "sess-1", "nextPage": True},
            },
            "https://g.codefresh.io/api/workflow?limit=2&page=2": {
                "workflows": {"docs": [{"id": "b3"}]},
                "pagination": {"sessionId": "sess-1", "nextPage": False},
            },
        }
        captured: list[dict[str, str]] = []
        monkeypatch.setattr(codefresh, "_fetch_page", _fetch_stub(pages, captured))
        manager = _FakeResumableManager()

        batches = list(_iter_page(MagicMock(), config, {}, MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"id": "b1"}, {"id": "b2"}], [{"id": "b3"}]]
        # The session cursor opened by page 1 must be pinned on page 2 so the snapshot is stable.
        assert "X-Pagination-Session-Id" not in captured[0]
        assert captured[1]["X-Pagination-Session-Id"] == "sess-1"
        assert manager.saved == [CodefreshResumeConfig(page=2, session_id="sess-1")]

    def test_single_page_no_next(self, monkeypatch: Any) -> None:
        config = _page_config(page_size=2)
        pages = {
            "https://g.codefresh.io/api/workflow?limit=2&page=1": {
                "workflows": {"docs": [{"id": "b1"}]},
                "pagination": {"nextPage": False},
            },
        }
        monkeypatch.setattr(codefresh, "_fetch_page", _fetch_stub(pages))
        manager = _FakeResumableManager()

        batches = list(_iter_page(MagicMock(), config, {}, MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"id": "b1"}]]
        assert manager.saved == []

    def test_empty_page_stops_even_when_next_page_advertised(self, monkeypatch: Any) -> None:
        # A misbehaving API that streams empty pages with nextPage=True must not loop forever.
        config = _page_config(page_size=2)
        pages = {
            "https://g.codefresh.io/api/workflow?limit=2&page=1": {
                "workflows": {"docs": []},
                "pagination": {"nextPage": True},
            },
        }
        monkeypatch.setattr(codefresh, "_fetch_page", _fetch_stub(pages))
        manager = _FakeResumableManager()

        batches = list(_iter_page(MagicMock(), config, {}, MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == []
        assert manager.saved == []

    def test_resume_starts_from_saved_page_and_session(self, monkeypatch: Any) -> None:
        config = _page_config(page_size=2)
        pages = {
            "https://g.codefresh.io/api/workflow?limit=2&page=3": {
                "workflows": {"docs": [{"id": "b9"}]},
                "pagination": {"nextPage": False},
            },
        }
        captured: list[dict[str, str]] = []
        monkeypatch.setattr(codefresh, "_fetch_page", _fetch_stub(pages, captured))
        manager = _FakeResumableManager(CodefreshResumeConfig(page=3, session_id="sess-resume"))

        batches = list(_iter_page(MagicMock(), config, {}, MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"id": "b9"}]]
        assert captured[0]["X-Pagination-Session-Id"] == "sess-resume"


class TestUnpaginatedEndpoint:
    def test_triggers_single_fetch_yields_one_list(self, monkeypatch: Any) -> None:
        pages = {
            "https://g.codefresh.io/api/hermes/triggers": [
                {"event": "e1", "pipeline": "p1"},
                {"event": "e2", "pipeline": "p1"},
            ]
        }
        monkeypatch.setattr(codefresh, "_fetch_page", _fetch_stub(pages))
        manager = _FakeResumableManager()

        batches = list(get_rows("token", "triggers", MagicMock(), manager))  # type: ignore[arg-type]

        assert batches == [[{"event": "e1", "pipeline": "p1"}, {"event": "e2", "pipeline": "p1"}]]
        assert manager.saved == []

    def test_empty_response_yields_nothing(self, monkeypatch: Any) -> None:
        pages: dict[str, Any] = {"https://g.codefresh.io/api/hermes/triggers": []}
        monkeypatch.setattr(codefresh, "_fetch_page", _fetch_stub(pages))

        batches = list(get_rows("token", "triggers", MagicMock(), _FakeResumableManager()))  # type: ignore[arg-type]

        assert batches == []


class TestGetRowsFlattensPipelines:
    def test_pipeline_metadata_lifted_to_top_level(self, monkeypatch: Any) -> None:
        pages = {
            "https://g.codefresh.io/api/pipelines?limit=100&offset=0": {
                "docs": [{"metadata": {"id": "p1", "name": "deploy"}, "spec": {"steps": {}}}],
                "count": 1,
            }
        }
        monkeypatch.setattr(codefresh, "_fetch_page", _fetch_stub(pages))

        batches = list(get_rows("token", "pipelines", MagicMock(), _FakeResumableManager()))  # type: ignore[arg-type]

        assert batches == [[{"id": "p1", "name": "deploy", "spec": {"steps": {}}}]]


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_specific_schema_is_rejected", 403, "projects", False),
            ("rate_limited", 429, None, False),
            ("server_error", 500, None, False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, schema_name: str | None, expected_valid: bool) -> None:
        session = MagicMock()
        session.get.return_value = _FakeResponse(status)
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(codefresh, "make_tracked_session", lambda *a, **k: session)
            valid, _error = validate_credentials("token", schema_name=schema_name)
        assert valid is expected_valid

    def test_connection_error_is_invalid(self) -> None:
        session = MagicMock()
        session.get.side_effect = ConnectionError("boom")
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(codefresh, "make_tracked_session", lambda *a, **k: session)
            valid, error = validate_credentials("token")
        assert valid is False
        assert error is not None


class TestCodefreshSourceResponse:
    @parameterized.expand(
        [
            ("projects", ["id"], None),
            ("pipelines", ["id"], None),
            ("builds", ["id"], "created"),
            ("images", ["id"], "created"),
            ("triggers", ["event", "pipeline"], None),
            ("step_types", ["id"], None),
        ]
    )
    def test_source_response_primary_keys_and_partition(
        self, endpoint: str, expected_keys: list[str], partition_key: str | None
    ) -> None:
        response = codefresh_source("token", endpoint, MagicMock(), _FakeResumableManager())  # type: ignore[arg-type]
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]

    def test_every_endpoint_has_a_source_response(self) -> None:
        # Guards against an endpoint added to settings without transport wiring.
        for endpoint in CODEFRESH_ENDPOINTS:
            response = codefresh_source("token", endpoint, MagicMock(), _FakeResumableManager())  # type: ignore[arg-type]
            assert response.primary_keys
