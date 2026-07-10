from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.linode.linode import LinodeResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.linode.source import LinodeSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_config() -> Any:
    config = MagicMock()
    config.api_token = "tok"
    return config


class TestLinodeSourceClass:
    def setup_method(self) -> None:
        self.source = LinodeSource()
        self.team_id = 123

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.LINODE

    def test_config_exposes_api_token_as_secret_password(self) -> None:
        fields = self.source.get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_token"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    @parameterized.expand(
        [
            # (endpoint, supports_incremental, supports_append)
            # Events are immutable/append-only: offer append but never merge.
            ("events", False, True),
            # Invoices have a genuine server-side date filter: merge-incremental.
            ("invoices", True, True),
            # No server-side filter -> full refresh only.
            ("linodes", False, False),
            ("volumes", False, False),
            ("domains", False, False),
            ("users", False, False),
            ("payments", False, False),
        ]
    )
    def test_schema_sync_modes(self, endpoint: str, supports_incremental: bool, supports_append: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(_make_config(), self.team_id)}
        assert endpoint in schemas
        schema = schemas[endpoint]
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_append

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(_make_config(), self.team_id, names=["events", "volumes"])
        assert {s.name for s in schemas} == {"events", "volumes"}

    def test_documented_tables_render_for_public_docs(self) -> None:
        # lists_tables_without_credentials + a static get_schemas power the posthog.com Supported
        # tables section; if either regresses the docs silently render nothing.
        assert self.source.lists_tables_without_credentials is True
        docs = {d["name"]: d for d in self.source.get_documented_tables()}
        assert set(docs) == {s.name for s in self.source.get_schemas(_make_config(), self.team_id)}
        assert docs["events"]["sync_methods"] == ["Append only", "Full refresh"]
        assert docs["invoices"]["sync_methods"] == ["Incremental", "Full refresh"]
        assert docs["linodes"]["sync_methods"] == ["Full refresh"]
        # Canonical descriptions should flow through so the docs aren't blank.
        assert docs["events"]["description"]

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.linode.com/v4/volumes?page=1",),
            ("403 Client Error: Forbidden for url: https://api.linode.com/v4/account/events",),
        ]
    )
    def test_credential_errors_are_non_retryable(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_transient_error_stays_retryable(self) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        observed = "500 Server Error: Internal Server Error for url: https://api.linode.com/v4/volumes"
        assert not any(key in observed for key in non_retryable)

    def test_validate_credentials_delegates(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.linode.source.validate_linode_credentials",
            return_value=(True, None),
        ) as mock_validate:
            valid, message = self.source.validate_credentials(_make_config(), self.team_id)
        assert valid is True
        assert message is None
        mock_validate.assert_called_once_with("tok")

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(MagicMock())
        assert manager._data_class is LinodeResumeConfig

    def test_source_for_pipeline_omits_watermark_when_not_incremental(self) -> None:
        # A full-refresh run must not forward a stale last-value, or the transport would build an
        # X-Filter and silently window the results.
        inputs = MagicMock()
        inputs.schema_name = "volumes"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00"
        inputs.incremental_field = None

        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.linode.source.linode_source",
            side_effect=fake_source,
        ):
            self.source.source_for_pipeline(_make_config(), MagicMock(), inputs)

        assert captured["should_use_incremental_field"] is False
        assert captured["db_incremental_field_last_value"] is None
