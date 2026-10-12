from typing import Literal

from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.metabase import (
    MetabaseAuthMethodConfig,
    MetabaseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.metabase import MetabaseAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.source import MetabaseSource


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

    def test_internal_ip_host_message_is_classified_non_retryable(self):
        # `_is_host_safe` raises this exact message when the Instance URL resolves to a
        # private/internal address (SSRF guard) — a permanent, deterministic failure until the
        # customer points the source at a public host. Build the message via the real
        # `_is_host_safe` code path so this test breaks if either side's wording drifts from
        # the classifier's key.
        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.is_cloud",
                return_value=True,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.get_instance_region",
                return_value="US",
            ),
        ):
            ok, err = _is_host_safe("10.0.0.5", team_id=999)

        assert not ok
        assert err is not None
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in err for key in non_retryable)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["cards"])
        assert [s.name for s in schemas] == ["cards"]

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
