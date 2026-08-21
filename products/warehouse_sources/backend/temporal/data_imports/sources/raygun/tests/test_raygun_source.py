import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.raygun import RaygunSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.raygun.source import RaygunSource

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.raygun.source"


def _config() -> RaygunSourceConfig:
    return RaygunSourceConfig(personal_access_token="tok")


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
