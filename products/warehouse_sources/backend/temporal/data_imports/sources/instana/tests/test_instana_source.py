import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.instana import (
    InstanaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.instana import InstanaHostNotAllowedError
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.source import InstanaSource


class TestInstanaSource:
    def setup_method(self) -> None:
        self.source = InstanaSource()
        self.team_id = 123
        self.config = InstanaSourceConfig(base_url="https://unit-tenant.instana.io", api_token="secret-token")

    def test_base_url_is_a_connection_host_field(self) -> None:
        # Changing the base URL must force the token to be re-entered so it's never
        # sent to a freshly-specified host.
        assert self.source.connection_host_fields == ["base_url"]

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)

        assert schemas["events"].supports_incremental is True
        # Events mutate while open (state/end change), so append mode is never offered.
        assert schemas["events"].supports_append is False
        assert schemas["events"].incremental_fields == [
            {
                "label": "start",
                "type": "integer",
                "field": "start",
                "field_type": "integer",
            }
        ]
        assert schemas["events"].description is not None

        for name in set(ENDPOINTS) - {"events"}:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["applications"])
        assert [s.name for s in schemas] == ["applications"]

    @pytest.mark.parametrize(
        ("probe_result", "expected_valid"),
        [
            ((True, 200), True),
            # 403 = genuine token missing the probe's scope; must not block source-create.
            ((False, 403), True),
            ((False, 401), False),
            ((False, 500), False),
            ((False, None), False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.instana.source.validate_instana_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        probe_result: tuple[bool, int | None],
        expected_valid: bool,
    ) -> None:
        mock_validate.return_value = probe_result

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with("https://unit-tenant.instana.io", "secret-token", self.team_id)

    @pytest.mark.parametrize("exception", [ValueError("bad url"), InstanaHostNotAllowedError("blocked")])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.instana.source.validate_instana_credentials"
    )
    def test_validate_credentials_surfaces_url_errors(
        self, mock_validate: mock.MagicMock, exception: Exception
    ) -> None:
        mock_validate.side_effect = exception

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == str(exception)
