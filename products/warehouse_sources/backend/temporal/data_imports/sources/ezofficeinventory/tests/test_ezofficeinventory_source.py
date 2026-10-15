from typing import cast

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.settings import (
    EZOFFICEINVENTORY_API_VERSION_V1,
    EZOFFICEINVENTORY_API_VERSION_V2,
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
    def test_names_filter(self) -> None:
        schemas = EZOfficeInventorySource().get_schemas(_config(), team_id=1, names=["assets", "members"])
        assert {s.name for s in schemas} == {"assets", "members"}


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
