from typing import Optional

import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.source import FreshchatSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.freshchat import (
    FreshchatSourceConfig,
)

PATCH_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.freshchat.source.validate_freshchat_credentials"
)


def _make_inputs(schema_name: str = "agents") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestFreshchatSource:
    def setup_method(self) -> None:
        self.source = FreshchatSource()
        self.team_id = 1
        self.config = FreshchatSourceConfig(domain="acme.freshchat.com", api_key="key")

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog -> the public docs Supported-tables section can render.
        assert self.source.lists_tables_without_credentials is True

    def test_connection_host_fields(self) -> None:
        # The domain is where the stored token is sent; editing it must re-require the secret.
        assert self.source.connection_host_fields == ["domain"]

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["agents"])
        assert len(schemas) == 1
        assert schemas[0].name == "agents"

    @pytest.mark.parametrize(
        "domain, probe, schema_name, expected_valid, expect_probe",
        [
            ("acme.freshchat.com", (200, True), None, True, True),
            # A Freshworks portal domain answers 200 with the web app's HTML, so a status-only check
            # accepts a domain no sync can read.
            ("acme.myfreshworks.com", (200, False), None, False, True),
            ("acme.myfreshworks.com", (200, False), "agents", False, True),
            # A non-JSON 403 is the same wrong host, so it must not be accepted as a missing scope.
            ("acme.myfreshworks.com", (403, False), None, False, True),
            ("acme.freshchat.com", (403, True), None, True, True),  # missing scope at source-create is accepted
            ("acme.freshchat.com", (403, True), "agents", False, True),  # missing scope for a specific schema fails
            ("acme.freshchat.com", (401, True), None, False, True),
            ("acme.freshchat.com", (None, False), None, False, True),  # connection error
            ("not a domain!", (200, True), None, False, False),  # domain regex rejects before probing
            # Non-Freshworks hosts are refused before probing — the stored token must never be
            # sent to a customer-chosen internal host (SSRF).
            ("metadata.google.internal", (200, True), None, False, False),
            ("api.default.svc.cluster.local", (200, True), None, False, False),
            ("evilfreshchat.com", (200, True), None, False, False),  # suffix match must not accept lookalikes
        ],
    )
    def test_validate_credentials(
        self,
        domain: str,
        probe: tuple[Optional[int], bool],
        schema_name: Optional[str],
        expected_valid: bool,
        expect_probe: bool,
    ) -> None:
        config = FreshchatSourceConfig(domain=domain, api_key="key")
        with mock.patch(PATCH_VALIDATE, return_value=probe) as mock_validate:
            is_valid, _ = self.source.validate_credentials(config, self.team_id, schema_name)

        assert is_valid is expected_valid
        if not expect_probe:
            mock_validate.assert_not_called()

    @pytest.mark.parametrize(
        "schema_name, primary_keys, partition_keys",
        [
            ("agents", ["id"], None),
            # Messages is the one endpoint with a stable creation timestamp and real volume, so it
            # is the one that partitions.
            ("conversation_messages", ["conversation_id", "id"], ["created_time"]),
        ],
    )
    def test_source_for_pipeline_plumbing(
        self, schema_name: str, primary_keys: list[str], partition_keys: Optional[list[str]]
    ) -> None:
        inputs = _make_inputs(schema_name)
        manager = self.source.get_resumable_source_manager(inputs)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.name == schema_name
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_keys == partition_keys
        assert response.partition_mode == ("datetime" if partition_keys else None)
