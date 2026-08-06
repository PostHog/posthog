import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.crunchbase import (
    PAGE_SIZE,
    CrunchbaseResumeConfig,
    _build_body,
    _flatten_entity,
    _format_updated_at,
    crunchbase_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.settings import (
    CRUNCHBASE_ENDPOINTS,
    ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the crunchbase module.
CRUNCHBASE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.crunchbase.make_tracked_session"
)


def _response(entities: list[dict[str, Any]] | None, *, drop_entities: bool = False) -> Response:
    body: dict[str, Any] = {"count": len(entities or [])}
    if not drop_entities:
        body["entities"] = entities or []
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: CrunchbaseResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's JSON body AT SEND TIME.

    ``request.json`` is a single dict mutated in place across pages (the paginator injects
    ``after_id`` into it), so inspecting it after the run shows only the final state — snapshot
    a copy when each request is prepared instead.
    """
    session.headers = {}
    body_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        body_snapshots.append(dict(request.json or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return body_snapshots


def _pages(source_response) -> list[list[dict[str, Any]]]:
    return list(source_response.items())


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str = "organizations", manager: mock.MagicMock | None = None, **kwargs: Any):
    return crunchbase_source(
        "key",
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        **kwargs,
    )


class TestFormatUpdatedAt:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_updated_at(value) == expected


class TestBuildBody:
    def test_full_scan_body(self):
        body = _build_body(
            CRUNCHBASE_ENDPOINTS["organizations"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

        assert body["field_ids"] == CRUNCHBASE_ENDPOINTS["organizations"].field_ids
        assert body["limit"] == PAGE_SIZE
        assert body["order"] == [{"field_id": "updated_at", "sort": "asc"}]
        assert "query" not in body
        # The keyset cursor is injected by the paginator, never baked into the base body.
        assert "after_id" not in body

    def test_incremental_body_has_gte_predicate(self):
        body = _build_body(
            CRUNCHBASE_ENDPOINTS["organizations"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert body["query"] == [
            {
                "type": "predicate",
                "field_id": "updated_at",
                "operator_id": "gte",
                "values": ["2024-01-02T00:00:00Z"],
            }
        ]


class TestFlattenEntity:
    def test_hoists_properties_and_uuid(self):
        entity = {"uuid": "u1", "properties": {"name": "Acme", "updated_at": "2024-01-02T00:00:00Z"}}
        assert _flatten_entity(entity) == {"name": "Acme", "updated_at": "2024-01-02T00:00:00Z", "uuid": "u1"}

    def test_handles_missing_properties(self):
        assert _flatten_entity({"uuid": "u1"}) == {"uuid": "u1"}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            # Basic-plan keys without the Search API license 403 — syncs would
            # fail everywhere, so validation must fail too.
            (403, False),
            (401, False),
        ],
    )
    @mock.patch(CRUNCHBASE_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.post.return_value = response

        assert validate_credentials("key") is expected

    @mock.patch(CRUNCHBASE_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.post.side_effect = Exception("boom")
        assert validate_credentials("key") is False


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_after_id_keyset(self, MockSession):
        session = MockSession.return_value
        full_page = [{"uuid": f"u{i}", "properties": {"updated_at": "2024-01-01T00:00:00Z"}} for i in range(PAGE_SIZE)]
        bodies = _wire(session, [_response(full_page), _response([{"uuid": "last", "properties": {}}])])

        manager = _make_manager()
        pages = _pages(_source(manager=manager))

        assert len(pages) == 2
        # A short second page ends pagination without an extra empty request.
        assert session.send.call_count == 2
        # Checkpoint saved once after the first full page, pointing at the keyset cursor.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == CrunchbaseResumeConfig(after_id=f"u{PAGE_SIZE - 1}")
        # First page carries no cursor; the second requests entities after the last full-page uuid.
        assert "after_id" not in bodies[0]
        assert bodies[1]["after_id"] == f"u{PAGE_SIZE - 1}"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rows_are_flattened(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"uuid": "u1", "properties": {"name": "Acme"}}])])

        rows = _rows(_source())
        assert rows == [{"name": "Acme", "uuid": "u1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_after_id(self, MockSession):
        session = MockSession.return_value
        bodies = _wire(session, [_response([])])

        manager = _make_manager(CrunchbaseResumeConfig(after_id="uuid-resume"))
        _rows(_source(manager=manager))

        assert bodies[0]["after_id"] == "uuid-resume"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_body_built_from_watermark(self, MockSession):
        session = MockSession.return_value
        bodies = _wire(session, [_response([])])

        _rows(
            _source(
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        query = bodies[0]["query"]
        assert query[0]["operator_id"] == "gte"
        assert query[0]["values"] == ["2024-01-02T00:00:00Z"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_entity_without_uuid_raises(self, MockSession):
        # uuid is the primary key; a missing one must surface immediately rather
        # than producing a null-keyed row that corrupts downstream merge/dedup.
        session = MockSession.return_value
        _wire(session, [_response([{"properties": {}}])])

        with pytest.raises(KeyError):
            _rows(_source())

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_stops_without_saving_state(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        pages = _pages(_source(manager=manager))

        assert pages == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_entities_key_is_empty_page_not_error(self, MockSession):
        # The old source used `data.get("entities", [])`; a 200 body without the key
        # is a legit empty page, not a fail-loud shape change.
        session = MockSession.return_value
        _wire(session, [_response(None, drop_entities=True)])

        manager = _make_manager()
        assert _pages(_source(manager=manager)) == []
        manager.save_state.assert_not_called()


class TestCrunchbaseSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CRUNCHBASE_ENDPOINTS[endpoint]
        response = _source(endpoint=endpoint)

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    @pytest.mark.parametrize("config", list(CRUNCHBASE_ENDPOINTS.values()))
    def test_field_ids_always_include_watermark_fields(self, config):
        # updated_at must be requested or the incremental watermark can't track.
        assert "updated_at" in config.field_ids
        assert "created_at" in config.field_ids
