from typing import cast

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.settings import (
    ENDPOINTS,
    EZOFFICEINVENTORY_API_VERSION_V1,
    EZOFFICEINVENTORY_API_VERSION_V2,
    V2_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.source import (
    EZOfficeInventorySource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ezofficeinventory import (
    EZOfficeInventorySourceConfig,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.source"


def _config() -> EZOfficeInventorySourceConfig:
    return cast(EZOfficeInventorySourceConfig, EZOfficeInventorySourceConfig(subdomain="acme", api_key="tok"))


class TestSourceConfig:
    def test_get_source_config_fields(self) -> None:
        config = EZOfficeInventorySource().get_source_config
        fields = {f.name: cast(SourceFieldInputConfig, f) for f in config.fields}
        assert set(fields) == {"subdomain", "api_key"}
        # The token is the only secret; the subdomain is a plain connection host field.
        assert fields["api_key"].secret is True
        assert fields["subdomain"].secret is False
        assert fields["api_key"].required is True
        assert fields["subdomain"].required is True

    def test_connection_host_fields_include_subdomain(self) -> None:
        # Retargeting the subdomain must re-require the stored token.
        assert EZOfficeInventorySource().connection_host_fields == ["subdomain"]


class TestSourceVersions:
    def test_v2_is_the_default(self) -> None:
        # New sources are stamped with default_version; the whole point of this bump is that they
        # land on v2 while existing v1 pins are untouched.
        source = EZOfficeInventorySource()
        assert source.default_version == EZOFFICEINVENTORY_API_VERSION_V2
        assert source.supported_versions == (EZOFFICEINVENTORY_API_VERSION_V1, EZOFFICEINVENTORY_API_VERSION_V2)


class TestGetSchemas:
    @pytest.mark.parametrize(
        ("api_version", "expected_names"),
        [
            (EZOFFICEINVENTORY_API_VERSION_V1, set(ENDPOINTS)),
            (EZOFFICEINVENTORY_API_VERSION_V2, set(V2_ENDPOINTS)),
        ],
    )
    def test_returns_version_specific_endpoints_full_refresh(self, api_version: str, expected_names: set) -> None:
        schemas = EZOfficeInventorySource().get_schemas(_config(), team_id=1, api_version=api_version)
        assert {s.name for s in schemas} == expected_names
        # EZOfficeInventory exposes no server-side cursor — every table is full refresh.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)

    def test_defaults_to_v2_endpoints(self) -> None:
        # No pin resolves to default_version (v2), so a v1-only table must not appear.
        schemas = {s.name for s in EZOfficeInventorySource().get_schemas(_config(), team_id=1)}
        assert schemas == set(V2_ENDPOINTS)
        assert "labels" not in schemas

    def test_primary_keys_are_endpoint_specific(self) -> None:
        schemas = {s.name: s for s in EZOfficeInventorySource().get_schemas(_config(), team_id=1)}
        assert schemas["assets"].detected_primary_keys == ["identifier"]
        assert schemas["members"].detected_primary_keys == ["id"]

    def test_names_filter(self) -> None:
        schemas = EZOfficeInventorySource().get_schemas(_config(), team_id=1, names=["assets", "members"])
        assert {s.name for s in schemas} == {"assets", "members"}

    def test_documented_tables_render_without_credentials(self) -> None:
        source = EZOfficeInventorySource()
        assert source.lists_tables_without_credentials is True
        tables = source.get_documented_tables()
        # Public docs render the default version's catalog.
        assert {t["name"] for t in tables} == set(V2_ENDPOINTS)
        # Curated descriptions flow through from canonical_descriptions.py.
        assets = next(t for t in tables if t["name"] == "assets")
        assert assets["description"]
        assert assets["sync_methods"] == ["Full refresh"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("transport_result", "expected_ok"),
        [((True, None), True), ((False, None), False)],
    )
    def test_delegates_to_transport(self, transport_result: tuple[bool, str | None], expected_ok: bool) -> None:
        with patch(f"{_MODULE}.validate_ezofficeinventory_credentials", return_value=transport_result) as mocked:
            ok, error = EZOfficeInventorySource().validate_credentials(_config(), team_id=1)
        # No pin resolves to the default version, so the probe runs under v2.
        mocked.assert_called_once_with("tok", "acme", EZOFFICEINVENTORY_API_VERSION_V2)
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_surfaces_transport_error_message(self) -> None:
        with patch(
            f"{_MODULE}.validate_ezofficeinventory_credentials",
            return_value=(False, "EZOfficeInventory rate limit reached while validating credentials."),
        ):
            ok, error = EZOfficeInventorySource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error == "EZOfficeInventory rate limit reached while validating credentials."


class TestResumableWiring:
    @pytest.mark.parametrize(
        ("pin", "expected_version"),
        [
            (None, EZOFFICEINVENTORY_API_VERSION_V2),  # NULL pin → default (v2)
            ("v1", "v1"),  # an existing v1 pin still reaches the request layer as v1
            ("v2", "v2"),
        ],
    )
    def test_source_for_pipeline_plumbs_resolved_version(self, pin: str | None, expected_version: str) -> None:
        inputs = MagicMock()
        inputs.schema_name = "members"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        inputs.api_version = pin
        manager = MagicMock()

        with patch(f"{_MODULE}.ezofficeinventory_source") as mocked:
            EZOfficeInventorySource().source_for_pipeline(_config(), manager, inputs)

        mocked.assert_called_once_with(
            api_key="tok",
            subdomain="acme",
            endpoint="members",
            team_id=7,
            job_id="job-1",
            resumable_source_manager=manager,
            api_version=expected_version,
            db_incremental_field_last_value=None,
        )
