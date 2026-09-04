from typing import Any

from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.airops.source import AirOpsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.airops import AirOpsSourceConfig


def _config(api_key: str = "test-key") -> AirOpsSourceConfig:
    return AirOpsSourceConfig.from_dict({"api_key": api_key})


class TestAirOpsSource:
    def test_source_config_shape(self) -> None:
        config = AirOpsSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/airops"
        # The single credential field must be a secret so it isn't echoed back to the client.
        field_names = {f.name for f in config.fields}
        assert field_names == {"api_key"}
        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.secret is True

    def test_get_schemas_are_full_refresh_only(self) -> None:
        # AirOps exposes no server-side timestamp filter and executions mutate after creation, so
        # neither table may advertise incremental/append — that would silently drop mutated rows.
        schemas = AirOpsSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == {"apps", "executions"}
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid AirOps API key"))])
    def test_validate_credentials(self, _name: str, probe_result: bool, expected: tuple[bool, str | None]) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.airops.source.validate_airops_credentials",
            return_value=probe_result,
        ):
            assert AirOpsSource().validate_credentials(_config(), team_id=1) == expected

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.airops.com/public_api/airops_apps",),
            ("403 Client Error: Forbidden for url: https://api.airops.com/public_api/airops_apps",),
        ]
    )
    def test_non_retryable_errors_match_credential_failures(self, raised_message: str) -> None:
        # A revoked/regenerated key must permanently fail the sync rather than retry forever; the
        # matcher keys on the stable status text + base host, so a real HTTPError string matches.
        errors = AirOpsSource().get_non_retryable_errors()
        assert any(pattern in raised_message and friendly for pattern, friendly in errors.items())

    def test_documented_tables_render_without_credentials(self) -> None:
        # `lists_tables_without_credentials=True` powers the public docs table catalog; it must resolve
        # from the static endpoint catalog with no network call and merge canonical descriptions.
        tables = AirOpsSource().get_documented_tables()
        by_name: dict[str, dict[str, Any]] = {t["name"]: t for t in tables}
        assert set(by_name) == {"apps", "executions"}
        assert by_name["apps"]["sync_methods"] == ["Full refresh"]
        assert by_name["executions"]["description"]
