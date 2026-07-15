from typing import Any

from unittest import mock

import requests
from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceFieldInputConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.cody.cody import (
    CodyCredentialsError,
    CodyResumeConfig,
    CodyRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cody.source import CodySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CodySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

ALL_ENDPOINTS = [
    "usage_by_user",
    "usage_by_user_month",
    "usage_by_user_day",
    "usage_by_user_day_client_language",
    "credits",
]


def _make_inputs(**overrides) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "usage_by_user_day_client_language",
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": mock.Mock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestCodySource:
    def setup_method(self):
        self.source = CodySource()
        self.config = CodySourceConfig(instance_url="example.sourcegraphcloud.com", access_token="token")
        self.team_id = 123

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CODY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name == SchemaExternalDataSourceType.CODY
        assert config.label == "Cody"
        assert len(config.fields) == 2
        instance_url, access_token = config.fields
        assert isinstance(instance_url, SourceFieldInputConfig)
        assert instance_url.name == "instance_url"
        assert instance_url.required is True
        assert instance_url.secret is False
        assert isinstance(access_token, SourceFieldInputConfig)
        assert access_token.name == "access_token"
        assert access_token.required is True
        assert access_token.secret is True
        # The docs slug is derived from docsUrl; a mismatch 404s the public doc.
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/cody"

    def test_instance_url_requires_reentering_secret_on_change(self):
        # Retargeting the instance without re-entering the token would let a preserved
        # credential be pointed at another instance's analytics.
        assert self.source.connection_host_fields == ["instance_url"]

    def test_get_schemas_returns_all_endpoints_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert [s.name for s in schemas] == ALL_ENDPOINTS
        # The CSV column schema is unpublished, so no endpoint may advertise incremental or
        # append sync — a declared-but-wrong cursor field would corrupt the watermark.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_default_on_tables(self):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["usage_by_user_day_client_language"].should_sync_default is True
        assert schemas["credits"].should_sync_default is True
        # Coarser rollups are derivable from the detailed report, so they start disabled.
        assert schemas["usage_by_user"].should_sync_default is False
        assert schemas["usage_by_user_month"].should_sync_default is False
        assert schemas["usage_by_user_day"].should_sync_default is False

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["credits"])

        assert [s.name for s in schemas] == ["credits"]

    def test_get_documented_tables_lists_endpoints_without_credentials(self):
        # lists_tables_without_credentials=True drives the public docs' Supported tables section.
        tables = self.source.get_documented_tables()

        assert [t["name"] for t in tables] == ALL_ENDPOINTS
        assert all(t["description"] for t in tables)

    def test_validate_credentials_success(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cody.source.validate_cody_credentials",
            return_value=True,
        ) as validate:
            assert self.source.validate_credentials(self.config, self.team_id) == (True, None)

        validate.assert_called_once_with("token", "example.sourcegraphcloud.com")

    @parameterized.expand(
        [
            (CodyCredentialsError("Sourcegraph rejected the access token."), "Sourcegraph rejected the access token."),
            (CodyRetryableError("status=503"), "Could not reach Sourcegraph Analytics"),
            (requests.ConnectionError("boom"), "Could not reach Sourcegraph Analytics"),
        ]
    )
    def test_validate_credentials_failure_messages(self, raised, expected_prefix):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cody.source.validate_cody_credentials",
            side_effect=raised,
        ):
            valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert valid is False
        assert message is not None and message.startswith(expected_prefix)

    @parameterized.expand([("401 Client Error",), ("403 Client Error",)])
    def test_non_retryable_errors_cover_credential_failures(self, status):
        keys = self.source.get_non_retryable_errors()
        assert any(key.startswith(status) and "analytics.sourcegraph.com" in key for key in keys)

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(_make_inputs())

        assert manager._data_class is CodyResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self):
        inputs = _make_inputs()
        manager = mock.Mock()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cody.source.cody_source"
        ) as mock_source:
            self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            access_token="token",
            instance_url="example.sourcegraphcloud.com",
            endpoint="usage_by_user_day_client_language",
            logger=inputs.logger,
            resumable_source_manager=manager,
        )
