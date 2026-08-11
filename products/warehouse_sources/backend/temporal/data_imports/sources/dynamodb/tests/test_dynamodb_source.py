from typing import Any, cast

import pytest
from unittest import mock

from structlog.types import FilteringBoundLogger

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.dynamodb import DynamoDBResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.source import DynamoDBSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynamodb import (
    DynamoDBSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dynamodb.source"


def _inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "users",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": cast(FilteringBoundLogger, mock.MagicMock()),
        "reset_pipeline": False,
    }
    return SourceInputs(**{**defaults, **overrides})


class TestDynamoDBSource:
    def setup_method(self) -> None:
        self.source = DynamoDBSource()
        self.config = DynamoDBSourceConfig(
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
            aws_region="us-east-1",
            aws_session_token=None,
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DYNAMODB

    def test_source_is_released_in_alpha(self) -> None:
        config = self.source.get_source_config

        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.category == DataWarehouseSourceCategory.DATABASES
        assert config.iconPath == "/static/services/dynamodb.png"

    def test_credential_fields(self) -> None:
        fields = self.source.get_source_config.fields

        assert [field.name for field in fields] == [
            "aws_access_key_id",
            "aws_secret_access_key",
            "aws_region",
            "aws_session_token",
        ]

    @pytest.mark.parametrize(
        "field_name, expected_secret, expected_required",
        [
            ("aws_access_key_id", False, True),
            ("aws_secret_access_key", True, True),
            ("aws_region", False, True),
            ("aws_session_token", True, False),
        ],
    )
    def test_secrets_are_password_fields(self, field_name: str, expected_secret: bool, expected_required: bool) -> None:
        field = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name == field_name
        )

        assert field.secret is expected_secret
        assert field.required is expected_required
        assert (field.type == SourceFieldInputConfigType.PASSWORD) is expected_secret

    def test_region_change_forces_credential_re_entry(self) -> None:
        # The region decides which host the stored key is signed for and sent to.
        assert self.source.connection_host_fields == ["aws_region"]

    def test_api_version_is_the_one_the_requests_actually_target(self) -> None:
        assert self.source.supported_versions == ("2012-08-10",)
        assert self.source.default_version == "2012-08-10"
        assert self.source.api_docs_url is not None and self.source.api_docs_url.startswith("https://")

    def test_tables_are_discovered_over_the_connection_not_from_a_static_catalog(self) -> None:
        # Table names are per-account, so the public docs must not try to list them.
        assert self.source.lists_tables_without_credentials is False
        assert self.source.get_documented_tables() == []

    @pytest.mark.parametrize(
        "error_code",
        ["UnrecognizedClientException", "AccessDeniedException", "ExpiredTokenException", "ValidationException"],
    )
    def test_permanent_aws_errors_stop_the_job(self, error_code: str) -> None:
        assert error_code in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "error_code", ["ThrottlingException", "ProvisionedThroughputExceededException", "InternalServerError"]
    )
    def test_throttling_is_treated_as_self_recovering(self, error_code: str) -> None:
        assert error_code in self.source.get_retryable_errors()
        assert error_code not in self.source.get_non_retryable_errors()

    def test_get_schemas_lists_the_accounts_tables(self) -> None:
        schemas = [SourceSchema(name="users", supports_incremental=False, supports_append=False)]

        with mock.patch(f"{_SOURCE_MODULE}.DynamoDBClient") as client_cls:
            with mock.patch(f"{_SOURCE_MODULE}.get_table_schemas", return_value=schemas) as get_schemas:
                assert self.source.get_schemas(self.config, team_id=1, with_counts=True, names=["users"]) == schemas

        client_cls.assert_called_once_with(
            access_key_id="AKIA",
            secret_access_key="secret",
            region="us-east-1",
            session_token=None,
            api_version="2012-08-10",
        )
        get_schemas.assert_called_once_with(client_cls.return_value, with_counts=True, names=["users"])

    def test_session_token_is_forwarded_when_set(self) -> None:
        config = DynamoDBSourceConfig(
            aws_access_key_id="AKIA",
            aws_secret_access_key="secret",
            aws_region="us-east-1",
            aws_session_token="temp",
        )

        with mock.patch(f"{_SOURCE_MODULE}.DynamoDBClient") as client_cls:
            with mock.patch(f"{_SOURCE_MODULE}.get_table_schemas", return_value=[]):
                self.source.get_schemas(config, team_id=1)

        assert client_cls.call_args.kwargs["session_token"] == "temp"

    @pytest.mark.parametrize(
        "result", [(True, None), (False, "AWS rejected your access key. Check the access key ID and secret.")]
    )
    def test_validate_credentials_passes_the_transport_result_through(self, result: tuple[bool, str | None]) -> None:
        with mock.patch(f"{_SOURCE_MODULE}.validate_dynamodb_credentials", return_value=result) as validate:
            assert self.source.validate_credentials(self.config, team_id=1) == result

        assert validate.call_args.kwargs["region"] == "us-east-1"
        assert validate.call_args.kwargs["api_version"] == "2012-08-10"

    def test_resumable_manager_is_bound_to_the_scan_cursor(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DynamoDBResumeConfig

    def test_source_for_pipeline_syncs_the_selected_table(self) -> None:
        manager: ResumableSourceManager[DynamoDBResumeConfig] = mock.MagicMock()
        inputs = _inputs(schema_name="orders")

        with mock.patch(f"{_SOURCE_MODULE}.dynamodb_source") as source_fn:
            assert self.source.source_for_pipeline(self.config, manager, inputs) == source_fn.return_value

        source_fn.assert_called_once_with(
            access_key_id="AKIA",
            secret_access_key="secret",
            region="us-east-1",
            session_token=None,
            table_name="orders",
            logger=inputs.logger,
            resumable_source_manager=manager,
            api_version="2012-08-10",
        )
