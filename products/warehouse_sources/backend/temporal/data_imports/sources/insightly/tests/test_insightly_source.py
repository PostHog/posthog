import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.insightly import (
    InsightlySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.settings import INSIGHTLY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.source import InsightlySource

FULL_REFRESH_ENDPOINTS = {name for name, cfg in INSIGHTLY_ENDPOINTS.items() if not cfg.supports_incremental}


class TestInsightlySource:
    def setup_method(self) -> None:
        self.source = InsightlySource()
        self.team_id = 123
        self.config = InsightlySourceConfig(pod="na1", api_key="key")

    def test_pod_is_connection_host_field(self) -> None:
        assert self.source.connection_host_fields == ["pod"]

    @pytest.mark.parametrize(
        "schema_name, expected",
        [
            ("Contacts", True),
            ("OpportunityStateHistory", False),
            (None, True),
        ],
    )
    def test_resume_covers_only_checkpointed_endpoints(self, schema_name: str | None, expected: bool) -> None:
        assert self.source.resume_covers_run(incremental_or_append=False, schema_name=schema_name) is expected

    @pytest.mark.parametrize("endpoint", sorted(FULL_REFRESH_ENDPOINTS))
    def test_full_refresh_endpoints_have_no_incremental(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id, names=[endpoint]))
        assert schema.supports_incremental is False
        assert schema.incremental_fields == []

    @pytest.mark.parametrize(
        "status, schema_name, expected_ok",
        [
            (200, None, True),
            (200, "Contacts", True),
            (403, None, True),  # missing scope tolerated at source-create
            (403, "Leads", False),  # but rejected for a specific schema
            (401, None, False),
            (500, None, False),
            (None, None, False),
        ],
    )
    def test_validate_credentials(
        self,
        status: int | None,
        schema_name: str | None,
        expected_ok: bool,
    ) -> None:
        answer = ConnectionResetError("boom") if status is None else ScriptedResponse(status=status)
        with scripted_network(always(answer)) as network:
            ok, _ = self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert ok is expected_ok
        assert {request.path for request in network.requests_log} == {f"/v3.1/{schema_name or 'Contacts'}"}

    @pytest.mark.parametrize(
        "schema_name, expected_path",
        [
            ("Leads", "/Leads"),
            # The per-opportunity path has an `{id}` placeholder, so access is probed on its parent.
            ("OpportunityStateHistory", "/Opportunities"),
        ],
    )
    def test_validate_credentials_probes_a_requestable_path(self, schema_name: str, expected_path: str) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert [request.path for request in network.requests_log] == [f"/v3.1{expected_path}"]

    def test_validate_credentials_rejects_invalid_pod(self) -> None:
        ok, message = self.source.validate_credentials(
            InsightlySourceConfig(pod="evil.com", api_key="key"), self.team_id
        )
        assert ok is False
        assert "Invalid Insightly pod" in (message or "")

    def test_source_for_pipeline_passes_normalized_pod_and_cursor(self) -> None:
        # A full API URL in the pod field is normalized to the bare pod token.
        config = InsightlySourceConfig(pod="https://api.eu1.insightly.com/v3.1", api_key="key")
        result = SourceDriver(self.source, config).run(
            "Contacts",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2020-01-01T00:00:00Z",
        )

        assert result.raised is None
        assert result.paths == ["/v3.1/Contacts"]
        assert result.requests[0].origin == "https://api.eu1.insightly.com"
        assert result.params("updated_after_utc") == ["2020-01-01T00:00:00Z"]

    def test_source_for_pipeline_omits_cursor_when_not_incremental(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "Contacts",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=False,
            db_incremental_field_last_value="2020-01-01T00:00:00Z",
        )

        assert result.raised is None
        assert result.params("updated_after_utc") == [None]
