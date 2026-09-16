from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aiven import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.source import AivenSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aiven import AivenSourceConfig


def _config() -> AivenSourceConfig:
    return AivenSourceConfig.from_dict({"api_token": "tok"})


class TestGetSchemas:
    def test_lists_all_endpoints_full_refresh_only(self) -> None:
        schemas = AivenSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Aiven exposes no server-side timestamp filter, so nothing is incremental.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_maps_validation_result(self, _name: str, valid: bool, expected: bool) -> None:
        with patch.object(source_module, "validate_aiven_credentials", return_value=valid):
            ok, error = AivenSource().validate_credentials(_config(), team_id=1)
        assert ok is expected
        assert (error is None) is expected


class TestDocsAndErrors:
    def test_documented_tables_cover_every_endpoint(self) -> None:
        # `lists_tables_without_credentials` is True, so the static catalog renders in public docs.
        tables = AivenSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
