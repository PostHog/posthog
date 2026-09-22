from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_organizations import (
    aws_organizations as transport_module,
    source as source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_organizations.settings import (
    AWS_ORGANIZATIONS_ENDPOINTS,
    ENDPOINTS,
    ORGANIZATIONS_API_VERSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_organizations.source import (
    AwsOrganizationsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsorganizations import (
    AwsOrganizationsSourceConfig,
)


def make_inputs(schema_name: str) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestAwsOrganizationsSource:
    def setup_method(self) -> None:
        self.source = AwsOrganizationsSource()
        self.config = AwsOrganizationsSourceConfig(
            aws_access_key_id="AKIAEXAMPLE",
            aws_secret_access_key="secret",
            aws_session_token=None,
        )

    def test_the_api_version_pins_the_service_model_the_requests_carry(self) -> None:
        assert self.source.supported_versions == (ORGANIZATIONS_API_VERSION,)
        assert self.source.default_version == ORGANIZATIONS_API_VERSION
        assert transport_module.target_prefix(self.source.default_version) == "AWSOrganizationsV20161128"
        assert self.source.api_docs_url.startswith("https://")

    def test_no_region_field_is_asked_for(self) -> None:
        # Organizations has one global endpoint, so a region would only mislead: a signature
        # scoped to anything but us-east-1 fails as though the key were wrong.
        assert [field.name for field in self.source.get_source_config.fields] == [
            "aws_access_key_id",
            "aws_secret_access_key",
            "aws_session_token",
        ]

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_names_the_table_and_uses_the_endpoint_primary_key(self, endpoint: str) -> None:
        inputs = make_inputs(endpoint)

        response = self.source.source_for_pipeline(
            self.config, self.source.get_resumable_source_manager(inputs), inputs
        )

        assert response.name == endpoint
        assert response.primary_keys == AWS_ORGANIZATIONS_ENDPOINTS[endpoint].primary_key

    def test_source_for_pipeline_passes_the_credentials_and_resolved_version_to_the_transport(self) -> None:
        inputs = make_inputs("accounts")
        manager = self.source.get_resumable_source_manager(inputs)

        with mock.patch.object(transport_module, "get_rows", return_value=iter([])) as get_rows:
            response = self.source.source_for_pipeline(self.config, manager, inputs)
            cast(Iterable[Any], response.items())

        assert get_rows.call_args.kwargs["aws_access_key_id"] == "AKIAEXAMPLE"
        assert get_rows.call_args.kwargs["aws_secret_access_key"] == "secret"
        assert get_rows.call_args.kwargs["endpoint"] == "accounts"
        assert get_rows.call_args.kwargs["api_version"] == ORGANIZATIONS_API_VERSION

    def test_endpoint_permissions_are_probed_per_table(self) -> None:
        with mock.patch.object(source_module, "probe_endpoint_permissions", return_value={"accounts": None}) as probe:
            assert self.source.get_endpoint_permissions(self.config, team_id=1, endpoints=["accounts"]) == {
                "accounts": None
            }

        assert probe.call_args.args == ("AKIAEXAMPLE", "secret", None, ["accounts"])
        assert probe.call_args.kwargs == {"api_version": ORGANIZATIONS_API_VERSION}

    def test_credential_and_permission_failures_are_not_retried(self) -> None:
        errors = self.source.get_non_retryable_errors()

        assert "AWS Organizations request failed: AccessDeniedException" in errors
        assert "AWS Organizations request failed: UnrecognizedClientException" in errors
        assert all(message for message in errors.values())
