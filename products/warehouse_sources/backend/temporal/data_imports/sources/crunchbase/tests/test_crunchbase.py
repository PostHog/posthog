from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.crunchbase import (
    PAGE_SIZE,
    CrunchbaseResumeConfig,
    _build_body,
    _flatten_entity,
    _format_updated_at,
    crunchbase_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.settings import (
    CRUNCHBASE_ENDPOINTS,
    ENDPOINTS,
)


def _make_manager(resume_state: CrunchbaseResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(entities: list[dict[str, Any]]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"count": len(entities), "entities": entities}
    resp.status_code = 200
    resp.ok = True
    return resp


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
            after_id=None,
        )

        assert body["field_ids"] == CRUNCHBASE_ENDPOINTS["organizations"].field_ids
        assert body["limit"] == PAGE_SIZE
        assert body["order"] == [{"field_id": "updated_at", "sort": "asc"}]
        assert "query" not in body
        assert "after_id" not in body

    def test_incremental_body_has_gte_predicate(self):
        body = _build_body(
            CRUNCHBASE_ENDPOINTS["organizations"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            after_id="uuid-1",
        )

        assert body["query"] == [
            {
                "type": "predicate",
                "field_id": "updated_at",
                "operator_id": "gte",
                "values": ["2024-01-02T00:00:00Z"],
            }
        ]
        assert body["after_id"] == "uuid-1"


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
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.crunchbase.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.post.return_value = response

        assert validate_credentials("key") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.crunchbase.make_tracked_session"
    )
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.post.side_effect = Exception("boom")
        assert validate_credentials("key") is False


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.crunchbase.make_tracked_session"
    )
    def test_paginates_via_after_id_keyset(self, mock_session):
        full_page = [{"uuid": f"u{i}", "properties": {"updated_at": "2024-01-01T00:00:00Z"}} for i in range(PAGE_SIZE)]
        mock_session.return_value.post.side_effect = [
            _response(full_page),
            _response([{"uuid": "last", "properties": {}}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", "organizations", mock.MagicMock(), manager))

        assert len(batches) == 2
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].after_id == f"u{PAGE_SIZE - 1}"
        second_body = mock_session.return_value.post.call_args_list[1].kwargs["json"]
        assert second_body["after_id"] == f"u{PAGE_SIZE - 1}"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.crunchbase.make_tracked_session"
    )
    def test_rows_are_flattened(self, mock_session):
        mock_session.return_value.post.return_value = _response([{"uuid": "u1", "properties": {"name": "Acme"}}])

        manager = _make_manager()
        batches = list(get_rows("key", "organizations", mock.MagicMock(), manager))

        assert batches == [[{"name": "Acme", "uuid": "u1"}]]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.crunchbase.make_tracked_session"
    )
    def test_resumes_from_saved_after_id(self, mock_session):
        mock_session.return_value.post.return_value = _response([])

        manager = _make_manager(CrunchbaseResumeConfig(after_id="uuid-resume"))
        list(get_rows("key", "organizations", mock.MagicMock(), manager))

        body = mock_session.return_value.post.call_args.kwargs["json"]
        assert body["after_id"] == "uuid-resume"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.crunchbase.make_tracked_session"
    )
    def test_incremental_body_built_from_watermark(self, mock_session):
        mock_session.return_value.post.return_value = _response([])

        manager = _make_manager()
        list(
            get_rows(
                "key",
                "organizations",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        body = mock_session.return_value.post.call_args.kwargs["json"]
        assert body["query"][0]["operator_id"] == "gte"
        assert body["query"][0]["values"] == ["2024-01-02T00:00:00Z"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.crunchbase.make_tracked_session"
    )
    def test_entity_without_uuid_raises(self, mock_session):
        # uuid is the primary key; a missing one must surface immediately rather
        # than producing a null-keyed row that corrupts downstream merge/dedup.
        mock_session.return_value.post.return_value = _response([{"properties": {}}])

        manager = _make_manager()
        with pytest.raises(KeyError):
            list(get_rows("key", "organizations", mock.MagicMock(), manager))

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.crunchbase.make_tracked_session"
    )
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.post.return_value = _response([])

        manager = _make_manager()
        batches = list(get_rows("key", "organizations", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestCrunchbaseSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CRUNCHBASE_ENDPOINTS[endpoint]
        response = crunchbase_source("key", endpoint, mock.MagicMock(), _make_manager())

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
