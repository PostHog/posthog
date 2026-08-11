import datetime as dt
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import structlog

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses import (
    aws_ses as transport_module,
    source as source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.aws_ses import AwsSesResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_ses.settings import ENDPOINTS
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
            aws_region="us-east-1",
            aws_session_token=None,
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.AWSSES

    def test_source_is_released_and_labelled_alpha(self) -> None:
        config = self.source.get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        assert config.label == "Amazon SES"
        assert config.iconPath == "/static/services/aws_ses.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/aws-ses"

    def test_source_config_fields(self) -> None:
        fields = self.source.get_source_config.fields

        assert [field.name for field in fields] == [
            "aws_access_key_id",
            "aws_secret_access_key",
            "aws_region",
            "aws_session_token",
        ]

    @pytest.mark.parametrize(
        "field_name,required,secret",
        [
            ("aws_access_key_id", True, False),
            ("aws_secret_access_key", True, True),
            ("aws_region", True, False),
            ("aws_session_token", False, True),
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

    def test_changing_the_region_requires_reentering_the_secrets(self) -> None:
        # The region picks the host the signed request is sent to, so retargeting it must not
        # reuse a preserved secret.
        assert self.source.connection_host_fields == ["aws_region"]

    def test_get_schemas_marks_only_the_suppression_list_incremental(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, team_id=1)}

        assert list(schemas) == list(ENDPOINTS)
        for schema in schemas.values():
            assert schema.description
        suppressed = schemas["suppressed_destinations"]
        assert suppressed.supports_incremental is True
        assert [field["field"] for field in suppressed.incremental_fields] == ["last_update_time"]
        for name in ("account", "configuration_sets", "email_identities"):
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False

    def test_get_schemas_honors_the_schema_picker_filter(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["email_identities"])

        assert [schema.name for schema in schemas] == ["email_identities"]

    def test_table_catalog_is_listable_without_credentials_for_public_docs(self) -> None:
        assert self.source.lists_tables_without_credentials is True
        assert self.source.get_schemas(
            AwsSesSourceConfig(aws_access_key_id="", aws_secret_access_key="", aws_region=""), 1
        )

    def test_canonical_descriptions_are_keyed_by_the_schema_names(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
        assert set(self.source.get_canonical_descriptions()) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Amazon SES request failed: UnrecognizedClientException - The security token included in the request is invalid",
            "Amazon SES request failed: SignatureDoesNotMatch - Signature expired",
            "Amazon SES request failed: ExpiredTokenException - The security token included in the request is expired",
            "Amazon SES request failed: AccessDeniedException - not authorized to perform: ses:GetAccount",
            "Invalid AWS region: 'email.evil.example/'",
        ],
    )
    def test_permanent_aws_failures_stop_the_sync_instead_of_retrying(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Amazon SES request failed: TooManyRequestsException - Rate exceeded",
            "Amazon SES request failed: HTTP 503 - ",
        ],
    )
    def test_transient_aws_failures_keep_retrying(self, observed_error: str) -> None:
        assert not any(key in observed_error for key in self.source.get_non_retryable_errors())

    def test_validate_credentials_passes_the_configured_credentials_through(self) -> None:
        with mock.patch.object(source_module, "validate_aws_ses_credentials", return_value=(True, None)) as validate:
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)
            assert self.source.validate_credentials(self.config, team_id=1, schema_name="account") == (True, None)

        assert validate.call_args_list[0] == mock.call("AKIAEXAMPLE", "secret", None, "us-east-1", schema_name=None)
        assert validate.call_args_list[1] == mock.call(
            "AKIAEXAMPLE", "secret", None, "us-east-1", schema_name="account"
        )

    def test_endpoint_permissions_pass_the_configured_credentials_through(self) -> None:
        with mock.patch.object(source_module, "probe_endpoint_permissions", return_value={"account": None}) as probe:
            assert self.source.get_endpoint_permissions(self.config, team_id=1, endpoints=["account"]) == {
                "account": None
            }

        assert probe.call_args[0] == ("AKIAEXAMPLE", "secret", None, "us-east-1", ["account"])

    def test_resumable_manager_is_bound_to_the_sources_resume_dataclass(self) -> None:
        manager = self.source.get_resumable_source_manager(make_inputs("suppressed_destinations"))

        assert manager._data_class is AwsSesResumeConfig

    @pytest.mark.parametrize(
        "endpoint,primary_keys",
        [
            ("account", None),
            ("configuration_sets", ["configuration_set_name"]),
            ("email_identities", ["identity_name"]),
            ("suppressed_destinations", ["email_address"]),
        ],
    )
    def test_source_for_pipeline_declares_the_endpoints_primary_key_and_a_final_commit_watermark(
        self, endpoint: str, primary_keys: list[str] | None
    ) -> None:
        inputs = make_inputs(endpoint)
        manager = self.source.get_resumable_source_manager(inputs)

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        # SES documents no response ordering, so the watermark must only commit when a walk
        # completes; "asc" would checkpoint it after every batch.
        assert response.sort_mode == "desc"

    def test_source_for_pipeline_forwards_the_watermark_only_on_an_incremental_run(self) -> None:
        watermark = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)

        with mock.patch.object(source_module, "aws_ses_source") as build:
            inputs = make_inputs("suppressed_destinations", True, watermark)
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)
            assert build.call_args[1]["db_incremental_field_last_value"] == watermark

            inputs = make_inputs("suppressed_destinations", False, watermark)
            self.source.source_for_pipeline(self.config, self.source.get_resumable_source_manager(inputs), inputs)
            assert build.call_args[1]["db_incremental_field_last_value"] is None

    def test_items_are_lazy_so_building_the_response_sends_no_request(self) -> None:
        inputs = make_inputs("suppressed_destinations")
        manager = self.source.get_resumable_source_manager(inputs)

        with mock.patch.object(transport_module, "send_request") as send:
            response = self.source.source_for_pipeline(self.config, manager, inputs)
            items = cast("Iterable[Any]", response.items())

        assert iter(items) is not None
        send.assert_not_called()
