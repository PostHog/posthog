import pytest
from unittest import mock

from posthog.schema import ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gleif import GleifSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gleif.source import GleifSource

_VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.gleif.source.validate_gleif_credentials"
)
_SOURCE_FN_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.gleif.source.gleif_source"


class TestGleifSource:
    def setup_method(self) -> None:
        self.source = GleifSource()
        self.team_id = 123
        self.config = GleifSourceConfig()

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Gleif"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The source must ship visible: unreleasedSource hides it from every user.
        assert not config.unreleasedSource
        # GLEIF is fully open and keyless, so the connect form has nothing to fill in.
        assert config.fields == []

    @pytest.mark.parametrize(("mock_return", "expected_valid"), [(True, True), (False, False)])
    @mock.patch(_VALIDATE_PATCH)
    def test_validate_credentials(self, mock_validate: mock.MagicMock, mock_return: bool, expected_valid: bool) -> None:
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render it.
        assert self.source.lists_tables_without_credentials is True
