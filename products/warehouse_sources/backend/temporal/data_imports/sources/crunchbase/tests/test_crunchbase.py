from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.crunchbase import (
    PAGE_SIZE,
    CrunchbaseResumeConfig,
    _flatten_entity,
    _format_updated_at,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.settings import (
    CRUNCHBASE_ENDPOINTS,
    CrunchbaseEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crunchbase.source import CrunchbaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.crunchbase import (
    CrunchbaseSourceConfig,
)


def _page(entities: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"count": len(entities), "entities": entities})


def _driver() -> SourceDriver:
    return SourceDriver(CrunchbaseSource(), CrunchbaseSourceConfig(api_key="key"))


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
    def test_format_values(self, value: Any, expected: str) -> None:
        assert _format_updated_at(value) == expected


class TestFlattenEntity:
    def test_hoists_properties_and_uuid(self) -> None:
        entity = {"uuid": "u1", "properties": {"name": "Acme", "updated_at": "2024-01-02T00:00:00Z"}}
        assert _flatten_entity(entity) == {"name": "Acme", "updated_at": "2024-01-02T00:00:00Z", "uuid": "u1"}

    def test_handles_missing_properties(self) -> None:
        assert _flatten_entity({"uuid": "u1"}) == {"uuid": "u1"}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("key") is expected

        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.path == "/v4/data/searches/organizations"
        assert request.method == "POST"
        assert request.headers["x-cb-user-key"] == "key"
        assert request.json() == {"field_ids": ["identifier"], "limit": 1}

    def test_validate_credentials_swallows_exceptions(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))):
            assert validate_credentials("key") is False


class TestPagination:
    def test_paginates_via_after_id_keyset(self) -> None:
        full_page = [{"uuid": f"u{i}", "properties": {"updated_at": "2024-01-01T00:00:00Z"}} for i in range(PAGE_SIZE)]
        result = _driver().run("organizations", [_page(full_page), _page([{"uuid": "last", "properties": {}}])])

        assert result.raised is None
        assert len(result.items) == 2
        # A short second page ends pagination without an extra empty request.
        assert len(result.requests) == 2
        # Checkpoint saved once after the first full page, pointing at the keyset cursor.
        assert result.saved_states == [CrunchbaseResumeConfig(after_id=f"u{PAGE_SIZE - 1}")]
        # First page carries no cursor; the second requests entities after the last full-page uuid.
        assert "after_id" not in result.requests[0].json()
        assert result.requests[1].json()["after_id"] == f"u{PAGE_SIZE - 1}"

    def test_rows_are_flattened(self) -> None:
        result = _driver().run("organizations", [_page([{"uuid": "u1", "properties": {"name": "Acme"}}])])

        assert result.raised is None
        assert result.rows == [{"name": "Acme", "uuid": "u1"}]

    def test_resumes_from_saved_after_id(self) -> None:
        result = _driver().run(
            "organizations", [_page([])], resume_state=CrunchbaseResumeConfig(after_id="uuid-resume")
        )

        assert result.raised is None
        assert result.requests[0].json()["after_id"] == "uuid-resume"

    def test_incremental_body_built_from_watermark(self) -> None:
        result = _driver().run(
            "organizations",
            [_page([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert result.raised is None
        query = result.requests[0].json()["query"]
        assert query[0]["operator_id"] == "gte"
        assert query[0]["values"] == ["2024-01-02T00:00:00Z"]

    def test_entity_without_uuid_raises(self) -> None:
        # uuid is the primary key; a missing one must surface immediately rather
        # than producing a null-keyed row that corrupts downstream merge/dedup.
        result = _driver().run("organizations", [_page([{"properties": {}}])])

        assert isinstance(result.raised, KeyError)


class TestCrunchbaseSourceResponse:
    @pytest.mark.parametrize("config", list(CRUNCHBASE_ENDPOINTS.values()))
    def test_field_ids_always_include_watermark_fields(self, config: CrunchbaseEndpointConfig) -> None:
        # updated_at must be requested or the incremental watermark can't track.
        assert "updated_at" in config.field_ids
        assert "created_at" in config.field_ids
