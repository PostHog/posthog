from typing import Literal

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GrafanaAuthMethodConfig,
    GrafanaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.grafana import (
    BASIC_AUTH,
    TOKEN_AUTH,
    GrafanaAuth,
    GrafanaResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.source import GrafanaSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(selection: Literal["token", "basic"] = "token", **auth_kwargs) -> GrafanaSourceConfig:
    return GrafanaSourceConfig(
        host="https://yourstack.grafana.net",
        auth_method=GrafanaAuthMethodConfig(selection=selection, **auth_kwargs),
    )


class TestGrafanaSource:
    def setup_method(self):
        self.source = GrafanaSource()
        self.team_id = 123
        self.config = _config(token="glsa_secret")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GRAFANA

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Grafana"
        assert config.label == "Grafana"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/grafana.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/grafana"

        host_field, auth_field, org_id_field = config.fields
        assert isinstance(host_field, SourceFieldInputConfig)
        assert host_field.name == "host"
        assert host_field.secret is False

        assert isinstance(auth_field, SourceFieldSelectConfig)
        assert auth_field.name == "auth_method"
        assert [o.value for o in auth_field.options] == [TOKEN_AUTH, BASIC_AUTH]

        assert isinstance(org_id_field, SourceFieldInputConfig)
        assert org_id_field.name == "org_id"
        assert org_id_field.required is False

    def test_credential_fields_are_secret(self):
        auth_field = self.source.get_source_config.fields[1]
        assert isinstance(auth_field, SourceFieldSelectConfig)
        secret_field_names = {
            f.name
            for option in auth_field.options
            for f in (option.fields or [])
            if isinstance(f, SourceFieldInputConfig) and f.secret
        }
        assert secret_field_names == {"token", "password"}

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error",
            "403 Client Error",
            "Missing Grafana service account token",
            "Missing Grafana username or password",
        ],
    )
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_only_annotations_support_incremental(self):
        # Only /api/annotations exposes a server-side time filter; everything else must stay
        # full refresh so a sync never silently skips changed rows.
        for schema in self.source.get_schemas(self.config, self.team_id):
            if schema.name == "annotations":
                assert schema.supports_incremental is True
                assert [f["field"] for f in schema.incremental_fields] == ["time"]
            else:
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []
            assert schema.supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["dashboards"])
        assert [s.name for s in schemas] == ["dashboards"]

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "selection, auth_kwargs, expected",
        [
            (TOKEN_AUTH, {"token": "glsa_x"}, ("glsa_x", None, None)),
            (BASIC_AUTH, {"username": "admin", "password": "pw"}, (None, "admin", "pw")),
        ],
    )
    def test_build_auth(self, selection, auth_kwargs, expected):
        auth = self.source._build_auth(_config(selection, **auth_kwargs))
        assert isinstance(auth, GrafanaAuth)
        assert auth.method == selection
        assert (auth.token, auth.username, auth.password) == expected

    @pytest.mark.parametrize("mock_return", [(True, None), (False, "Invalid Grafana credentials")])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.grafana.source.validate_grafana_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="dashboards")

        assert result == mock_return
        args = mock_validate.call_args.args
        assert args[0] == self.config.host
        assert isinstance(args[1], GrafanaAuth)
        assert args[2] == self.config.org_id
        assert args[3] == self.team_id
        assert args[4] == "dashboards"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.grafana.source.grafana_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_grafana_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "annotations"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1784131261208
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_grafana_source.assert_called_once()
        kwargs = mock_grafana_source.call_args.kwargs
        assert kwargs["host"] == "https://yourstack.grafana.net"
        assert isinstance(kwargs["auth"], GrafanaAuth)
        assert kwargs["endpoint"] == "annotations"
        assert kwargs["team_id"] == 42
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1784131261208

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.grafana.source.grafana_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_grafana_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "annotations"
        inputs.team_id = 42
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1784131261208

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_grafana_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is GrafanaResumeConfig

    def test_canonical_descriptions_cover_endpoints(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)

    def test_documented_tables_render_without_credentials(self):
        # The public docs endpoint calls get_schemas with a credential-free placeholder config;
        # any I/O or config access in get_schemas would break the posthog.com table catalog.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        annotations = next(t for t in tables if t["name"] == "annotations")
        assert "Incremental" in annotations["sync_methods"]
