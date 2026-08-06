import datetime as dt
from typing import Any

import pytest
from unittest import mock

import structlog

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.aws_ses import AwsSesResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.settings import (
    AWS_SES_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.source import AwsSesSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsses import AwsSesSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def make_inputs(
    schema_name: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="last_update_time",
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestAwsSesSource:
    def setup_method(self) -> None:
        self.source = AwsSesSource()
        self.config = AwsSesSourceConfig(
            aws_access_key_id="AKIAEXAMPLE",
            aws_secret_access_key="secret",
            region="us-east-1",
            aws_session_token=None,
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.AWSSES

    def test_source_is_released_and_labelled_alpha(self) -> None:
        # The scaffolded stub shipped with unreleasedSource=True, which hides it from the picker.
        config = self.source.get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/aws-ses"

    @pytest.mark.parametrize(
        "field_name,required,secret",
        [
            ("aws_access_key_id", True, False),
            ("aws_secret_access_key", True, True),
            ("aws_session_token", False, True),
            ("region", True, False),
        ],
    )
    def test_credential_fields_are_marked_secret_so_they_are_not_echoed_back(
        self, field_name: str, required: bool, secret: bool
    ) -> None:
        field = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name == field_name
        )

        assert field.required is required
        assert field.secret is secret
        assert (field.type == SourceFieldInputConfigType.PASSWORD) is secret

    def test_only_the_suppression_list_syncs_incrementally(self) -> None:
        # Only ListSuppressedDestinations has a server-side timestamp filter; marking the
        # current-state endpoints incremental would fake a cursor and re-scan every run.
        schemas = {s.name: s for s in self.source.get_schemas(self.config, team_id=1)}

        assert set(schemas) == set(ENDPOINTS)
        assert schemas["suppressed_destinations"].supports_incremental is True
        assert [f["field"] for f in schemas["suppressed_destinations"].incremental_fields] == ["last_update_time"]
        for name in ("account", "configuration_sets", "email_identities"):
            assert schemas[name].supports_incremental is False
        for schema in schemas.values():
            assert schema.description

    def test_get_schemas_honors_the_schema_picker_filter(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["account"])

        assert [s.name for s in schemas] == ["account"]

    def test_table_catalog_is_listable_without_credentials_for_public_docs(self) -> None:
        assert self.source.lists_tables_without_credentials is True
        assert self.source.get_schemas(AwsSesSourceConfig(aws_access_key_id="", aws_secret_access_key="", region=""), 1)

    def test_canonical_descriptions_are_keyed_by_the_schema_names(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "AWS SES request failed: AccessDeniedException - User is not authorized to perform ses:GetAccount",
            "AWS SES request failed: UnrecognizedClientException - The security token included in the request is invalid",
            "AWS SES request failed: ExpiredTokenException - The security token included in the request is expired",
        ],
    )
    def test_permanent_aws_failures_stop_the_sync_instead_of_retrying(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_transient_failures_are_not_marked_non_retryable(self) -> None:
        assert not any(key in "AWS SES request failed: HTTP 503 - " for key in self.source.get_non_retryable_errors())

    def test_validate_credentials_passes_the_configured_credentials_through(self) -> None:
        with mock.patch.object(source_module, "validate_aws_ses_credentials", return_value=(True, None)) as v:
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)

        assert v.call_args[0] == ("AKIAEXAMPLE", "secret", None, "us-east-1")

    def test_resumable_manager_is_bound_to_the_sources_resume_dataclass(self) -> None:
        manager = self.source.get_resumable_source_manager(make_inputs("suppressed_destinations"))

        assert manager._data_class is AwsSesResumeConfig

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_uses_the_endpoints_primary_key(self, endpoint: str) -> None:
        inputs = make_inputs(endpoint)
        manager = self.source.get_resumable_source_manager(inputs)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.name == endpoint
        assert response.primary_keys == AWS_SES_ENDPOINTS[endpoint].primary_key

    def test_source_for_pipeline_forwards_the_watermark_only_on_an_incremental_run(self) -> None:
        watermark = dt.datetime(2024, 5, 1, tzinfo=dt.UTC)

        with mock.patch.object(source_module, "aws_ses_source") as build:
            inputs = make_inputs("suppressed_destinations", True, watermark)
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)
            assert build.call_args[1]["db_incremental_field_last_value"] == watermark

            inputs = make_inputs("suppressed_destinations", False, watermark)
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)
            assert build.call_args[1]["db_incremental_field_last_value"] is None
