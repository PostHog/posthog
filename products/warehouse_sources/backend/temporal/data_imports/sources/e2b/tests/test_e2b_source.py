from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.e2b import E2BResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.e2b.source import E2BSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import E2BSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestE2BSource:
    def setup_method(self) -> None:
        self.source = E2BSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.E2B

    def test_api_key_field_is_required_password_secret(self) -> None:
        fields = self.source.get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.required is True
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True

    def test_get_schemas_are_all_full_refresh(self) -> None:
        # No E2B list endpoint has a server-side timestamp filter, so none may advertise incremental
        # or append — doing so would let the pipeline skip rows it never actually filtered server-side.
        schemas = self.source.get_schemas(MagicMock(spec=E2BSourceConfig), team_id=self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(spec=E2BSourceConfig), team_id=self.team_id, names=["templates"])
        assert [s.name for s in schemas] == ["templates"]

    @parameterized.expand([("valid", True, (True, None)), ("invalid", False, (False, "Invalid E2B API key"))])
    def test_validate_credentials_delegates_to_transport(self, _name: str, transport_ok: bool, expected) -> None:
        config = E2BSourceConfig(api_key="e2b_test")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.e2b.source.validate_e2b_credentials",
            return_value=transport_ok,
        ):
            assert self.source.validate_credentials(config, self.team_id) == expected

    def test_validate_credentials_transient_error_is_not_reported_as_invalid(self) -> None:
        # A probe that can't reach E2B must not brand a possibly-valid key "invalid" and send the user
        # down the credential-reset path — the message has to point at retrying instead.
        config = E2BSourceConfig(api_key="e2b_test")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.e2b.source.validate_e2b_credentials",
            side_effect=Exception("upstream 503"),
        ):
            ok, message = self.source.validate_credentials(config, self.team_id)
        assert ok is False
        assert message is not None and "invalid" not in message.lower()

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.e2b.app/v2/sandboxes?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.e2b.app/snapshots"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.e2b.app', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.e2b.app/v2/sandboxes"),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is E2BResumeConfig

    def test_source_for_pipeline_plumbs_api_key_and_schema(self) -> None:
        config = E2BSourceConfig(api_key="e2b_secret")
        inputs = MagicMock()
        inputs.schema_name = "sandboxes"
        manager = MagicMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.e2b.source.e2b_source"
        ) as mock_source:
            self.source.source_for_pipeline(config, manager, inputs)
        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "e2b_secret"
        assert kwargs["endpoint"] == "sandboxes"
        assert kwargs["resumable_source_manager"] is manager

    def test_documented_tables_render_from_static_catalog(self) -> None:
        # lists_tables_without_credentials=True lets posthog.com render the Supported tables section
        # with no credentials; the canonical descriptions must feed through.
        assert self.source.lists_tables_without_credentials is True
        tables = {t["name"]: t for t in self.source.get_documented_tables()}
        assert set(tables) == set(ENDPOINTS)
        assert tables["sandboxes"]["description"]
        assert tables["sandboxes"]["sync_methods"] == ["Full refresh"]
