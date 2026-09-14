from typing import Optional

from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.unstructured import (
    UnstructuredSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.unstructured.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.unstructured.source import UnstructuredSource


class TestUnstructuredSourceClass:
    def setup_method(self) -> None:
        self.source = UnstructuredSource()
        self.team_id = 123

    def test_form_fields(self) -> None:
        fields = {f.name: f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        # The API key must be a password + secret so it never leaks into logs or the API surface.
        assert fields["api_key"].required is True
        assert fields["api_key"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["api_key"].secret is True
        # The API host is optional (defaults to the public platform) and is not a secret.
        assert fields["base_url"].required is False
        assert fields["base_url"].secret is False

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog, so the public docs table list is safe to render.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_are_all_full_refresh(self) -> None:
        schemas = self.source.get_schemas(UnstructuredSourceConfig(api_key="k"), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # No endpoint exposes a verified server-side incremental filter, so every stream is full refresh.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_name_filter(self) -> None:
        schemas = self.source.get_schemas(UnstructuredSourceConfig(api_key="k"), self.team_id, names=["jobs"])
        assert [s.name for s in schemas] == ["jobs"]

    @parameterized.expand(
        [
            ("valid", (True, None), True, None),
            ("invalid", (False, "Invalid Unstructured API key"), False, "Invalid Unstructured API key"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, backend_result: tuple[bool, Optional[str]], expected_ok: bool, expected_msg: Optional[str]
    ) -> None:
        config = UnstructuredSourceConfig(api_key="k", base_url="https://custom.example.com")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.unstructured.source.validate_unstructured_credentials",
            return_value=backend_result,
        ) as mock_validate:
            ok, msg = self.source.validate_credentials(config, self.team_id)

        assert ok is expected_ok
        assert msg == expected_msg
        # The user-configured host and team are threaded through to the probe, not discarded.
        mock_validate.assert_called_once_with("https://custom.example.com", "k", self.team_id)
