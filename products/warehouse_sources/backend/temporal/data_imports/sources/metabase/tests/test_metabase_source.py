from typing import Literal

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    MetabaseAuthMethodConfig,
    MetabaseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.metabase import (
    API_KEY_AUTH,
    SESSION_AUTH,
    MetabaseAuth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.source import MetabaseSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(selection: Literal["api_key", "session"] = "api_key", **auth_kwargs) -> MetabaseSourceConfig:
    return MetabaseSourceConfig(
        host="https://company.metabaseapp.com",
        auth_method=MetabaseAuthMethodConfig(selection=selection, **auth_kwargs),
    )


class TestMetabaseSource:
    def setup_method(self):
        self.source = MetabaseSource()
        self.team_id = 123
        self.config = _config(api_key="mb_secret")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.METABASE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Metabase"
        assert config.label == "Metabase"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/metabase.png"

        host_field, auth_field = config.fields
        assert isinstance(host_field, SourceFieldInputConfig)
        assert host_field.name == "host"
        assert host_field.secret is False

        assert isinstance(auth_field, SourceFieldSelectConfig)
        assert auth_field.name == "auth_method"
        assert [o.value for o in auth_field.options] == [API_KEY_AUTH, SESSION_AUTH]

    def test_credential_fields_are_secret(self):
        auth_field = self.source.get_source_config.fields[1]
        assert isinstance(auth_field, SourceFieldSelectConfig)
        secret_field_names = {
            f.name
            for option in auth_field.options
            for f in (option.fields or [])
            if isinstance(f, SourceFieldInputConfig) and f.secret
        }
        assert secret_field_names == {"api_key", "password"}

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error", "Invalid Metabase credentials"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_schemas_are_full_refresh(self):
        # Metabase has no server-side timestamp filter, so nothing is incremental.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["cards"])
        assert [s.name for s in schemas] == ["cards"]

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "selection, auth_kwargs, expected",
        [
            (API_KEY_AUTH, {"api_key": "mb_x"}, ("mb_x", None, None)),
            (SESSION_AUTH, {"username": "me@x.com", "password": "pw"}, (None, "me@x.com", "pw")),
        ],
    )
    def test_build_auth(self, selection, auth_kwargs, expected):
        auth = self.source._build_auth(_config(selection, **auth_kwargs))
        assert isinstance(auth, MetabaseAuth)
        assert auth.method == selection
        assert (auth.api_key, auth.username, auth.password) == expected

    @pytest.mark.parametrize("mock_return", [(True, None), (False, "Invalid Metabase credentials")])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.metabase.source.validate_metabase_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="cards")

        assert result == mock_return
        args = mock_validate.call_args.args
        assert args[0] == self.config.host
        assert isinstance(args[1], MetabaseAuth)
        assert args[2] == self.team_id
        assert args[3] == "cards"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.metabase.source.metabase_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_metabase_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "cards"
        inputs.team_id = 42

        self.source.source_for_pipeline(self.config, inputs)

        mock_metabase_source.assert_called_once()
        kwargs = mock_metabase_source.call_args.kwargs
        assert kwargs["host"] == "https://company.metabaseapp.com"
        assert isinstance(kwargs["auth"], MetabaseAuth)
        assert kwargs["endpoint"] == "cards"
        assert kwargs["team_id"] == 42

    def test_canonical_descriptions_cover_endpoints(self):
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
