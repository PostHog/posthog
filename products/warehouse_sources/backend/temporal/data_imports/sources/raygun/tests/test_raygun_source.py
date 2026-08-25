import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.raygun import RaygunSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.source import RaygunSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.raygun.source"


def _config() -> RaygunSourceConfig:
    return RaygunSourceConfig(personal_access_token="tok")


class TestRaygunSourceConfig:
    def test_get_source_config_shape(self) -> None:
        config = RaygunSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        # A finished source ships visible with a soft ALPHA label, never hidden.
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None

        fields = [f for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert len(fields) == 1
        token_field = fields[0]
        assert token_field.name == "personal_access_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

    def test_get_schemas_full_refresh_only(self) -> None:
        schemas = RaygunSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No endpoint has a server-side timestamp filter, so none support incremental sync.
        assert all(s.supports_incremental is False for s in schemas)

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas does no I/O, so the public docs catalog can render.
        assert RaygunSource.lists_tables_without_credentials is True


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("token_result", "schema_name", "expected_valid"),
        [
            ((True, 200), None, True),
            # A valid token missing a scope is accepted at source-create (no schema)...
            ((False, 403), None, True),
            # ...but rejected when probing a specific table's scope.
            ((False, 403), "sessions", False),
            ((False, 401), None, False),
            ((False, None), None, False),
        ],
    )
    @patch(f"{MODULE}.validate_token")
    def test_status_to_result(
        self,
        mock_validate: MagicMock,
        token_result: tuple[bool, int | None],
        schema_name: str | None,
        expected_valid: bool,
    ) -> None:
        mock_validate.return_value = token_result
        is_valid, _ = RaygunSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert is_valid is expected_valid
