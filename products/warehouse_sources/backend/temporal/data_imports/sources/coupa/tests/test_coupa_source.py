import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.coupa.source import CoupaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coupa import CoupaSourceConfig


class TestCoupaSource:
    def setup_method(self):
        self.source = CoupaSource()
        self.team_id = 123
        self.config = CoupaSourceConfig(
            instance_url="https://myorg.coupahost.com", client_id="cid", client_secret="sec"
        )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coupa.source.validate_coupa_credentials"
    )
    @mock.patch.object(CoupaSource, "is_database_host_valid")
    def test_validate_credentials_happy_path(self, mock_host_valid, mock_validate):
        mock_host_valid.return_value = (True, None)
        mock_validate.return_value = True

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_host_valid.assert_called_once_with("myorg.coupahost.com", self.team_id)
        mock_validate.assert_called_once_with("https://myorg.coupahost.com", "cid", "sec")

    @mock.patch.object(CoupaSource, "is_database_host_valid")
    def test_validate_credentials_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Host is not allowed"

    def test_validate_credentials_rejects_invalid_url(self):
        config = CoupaSourceConfig(instance_url="ftp://nope", client_id="cid", client_secret="sec")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Coupa instance URL"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coupa.source.validate_coupa_credentials"
    )
    @mock.patch.object(CoupaSource, "is_database_host_valid")
    def test_validate_credentials_bad_secret(self, mock_host_valid, mock_validate):
        mock_host_valid.return_value = (True, None)
        mock_validate.return_value = False

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Coupa credentials" in (error_message or "")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.coupa.source.coupa_source")
    @mock.patch.object(CoupaSource, "is_database_host_valid")
    def test_source_for_pipeline_plumbs_arguments(self, mock_host_valid, mock_coupa_source):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.schema_name = "invoices"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_coupa_source.assert_called_once()
        kwargs = mock_coupa_source.call_args.kwargs
        assert kwargs["instance_url"] == "https://myorg.coupahost.com"
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "sec"
        assert kwargs["endpoint"] == "invoices"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @mock.patch.object(CoupaSource, "is_database_host_valid")
    def test_source_for_pipeline_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")
        inputs = mock.MagicMock()
        inputs.schema_name = "invoices"
        inputs.team_id = self.team_id

        with pytest.raises(ValueError, match="Host is not allowed"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.coupa.source.coupa_source")
    @mock.patch.object(CoupaSource, "is_database_host_valid")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_host_valid, mock_coupa_source):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_coupa_source.call_args.kwargs["db_incremental_field_last_value"] is None
