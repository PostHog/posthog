from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.razorpay import (
    RazorpaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.razorpay import RazorpayResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.source import RazorpaySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _source_inputs(
    schema_name: str = "Payments",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema_id",
        source_id="source_id",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field="created_at" if should_use_incremental_field else None,
        incremental_field_type=None,
        job_id="job_id",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestRazorpaySource:
    def setup_method(self) -> None:
        self.source = RazorpaySource()
        self.config = RazorpaySourceConfig(key_id="rzp_test_key", key_secret="secret")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.RAZORPAY

    def test_source_is_released_as_alpha(self) -> None:
        config = self.source.get_source_config

        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_source_config_fields(self) -> None:
        fields = {
            field.name: field
            for field in self.source.get_source_config.fields
            if isinstance(field, SourceFieldInputConfig)
        }

        assert set(fields.keys()) == {"key_id", "key_secret"}
        assert fields["key_secret"].secret is True
        assert fields["key_secret"].type == SourceFieldInputConfigType.PASSWORD
        assert fields["key_id"].required is True
        assert fields["key_secret"].required is True

    @pytest.mark.parametrize(
        ("endpoint", "supports_incremental"),
        [
            ("Customers", True),
            ("Disputes", False),
            ("Invoices", False),
            ("Items", True),
            ("Orders", True),
            ("Payments", True),
            ("Plans", True),
            ("Refunds", True),
            ("Settlements", True),
            ("Subscriptions", True),
            ("VirtualAccounts", False),
        ],
    )
    def test_get_schemas_incremental_support(self, endpoint: str, supports_incremental: bool) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, team_id=1)}

        assert endpoint in schemas
        schema = schemas[endpoint]
        assert schema.supports_incremental is supports_incremental
        if supports_incremental:
            assert [field["field"] for field in schema.incremental_fields] == ["created_at"]
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_covers_all_endpoints_and_filters_by_name(self) -> None:
        all_schemas = self.source.get_schemas(self.config, team_id=1)
        assert [schema.name for schema in all_schemas] == list(ENDPOINTS)

        filtered = self.source.get_schemas(self.config, team_id=1, names=["Payments", "Refunds"])
        assert [schema.name for schema in filtered] == ["Payments", "Refunds"]

    @pytest.mark.parametrize(
        ("is_valid", "expected_ok"),
        [(True, True), (False, False)],
    )
    def test_validate_credentials(self, is_valid: bool, expected_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.source.validate_razorpay_credentials",
            return_value=is_valid,
        ) as mock_validate:
            ok, message = self.source.validate_credentials(self.config, team_id=1)

        mock_validate.assert_called_once_with("rzp_test_key", "secret")
        assert ok is expected_ok
        assert (message is None) is expected_ok

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_source_inputs())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is RazorpayResumeConfig

    @pytest.mark.parametrize(
        ("should_use_incremental_field", "last_value", "expected_last_value"),
        [
            (True, 1_750_000_000, 1_750_000_000),
            (False, 1_750_000_000, None),
        ],
    )
    def test_source_for_pipeline_plumbing(
        self,
        should_use_incremental_field: bool,
        last_value: Optional[int],
        expected_last_value: Optional[int],
    ) -> None:
        inputs = _source_inputs(
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )
        manager = MagicMock(spec=ResumableSourceManager)
        mock_resource = MagicMock()
        mock_resource.name = "Payments"
        mock_resource.column_hints = None

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.razorpay.source.razorpay_source",
            return_value=mock_resource,
        ) as mock_source:
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once_with(
            key_id="rzp_test_key",
            key_secret="secret",
            endpoint="Payments",
            team_id=1,
            job_id="job_id",
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=expected_last_value,
        )
        assert response.name == "Payments"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    def test_canonical_descriptions_cover_only_known_endpoints(self) -> None:
        assert set(CANONICAL_DESCRIPTIONS.keys()) == set(ENDPOINTS)
