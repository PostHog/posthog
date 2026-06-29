from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import OmnisendSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.omnisend import OmnisendResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.source import OmnisendSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> OmnisendSourceConfig:
    return OmnisendSourceConfig(api_key="test-key")


def _source_inputs(schema_name: str = "contacts", **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestOmnisendSource:
    def test_source_type(self) -> None:
        assert OmnisendSource().source_type == ExternalDataSourceType.OMNISEND

    def test_source_config_basics(self) -> None:
        config = OmnisendSource().get_source_config
        assert config.label == "Omnisend"
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/omnisend.png"

    def test_source_config_has_api_key_password_field(self) -> None:
        fields = OmnisendSource().get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    def test_get_schemas_returns_all_endpoints(self) -> None:
        schemas = OmnisendSource().get_schemas(_config(), team_id=1)
        names = {s.name for s in schemas}
        assert names == {"contacts", "campaigns", "carts", "orders", "products", "categories"}

    def test_all_endpoints_are_full_refresh(self) -> None:
        # We can't curl-verify Omnisend's server-side timestamp filter, so every endpoint
        # ships full refresh (no incremental advertised). See api_inventory.md.
        for schema in OmnisendSource().get_schemas(_config(), team_id=1):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = OmnisendSource().get_schemas(_config(), team_id=1, names=["contacts", "orders"])
        assert {s.name for s in schemas} == {"contacts", "orders"}

    @pytest.mark.parametrize(
        ("validate_return", "expected_ok", "expected_msg"),
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Omnisend API key"),
            ((False, 403), False, "Invalid Omnisend API key"),
            ((False, None), False, "Could not connect to Omnisend with the provided API key"),
            ((False, 500), False, "Could not connect to Omnisend with the provided API key"),
        ],
    )
    def test_validate_credentials(
        self, validate_return: tuple[bool, int | None], expected_ok: bool, expected_msg: str | None
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.source.validate_omnisend_credentials",
            return_value=validate_return,
        ):
            ok, msg = OmnisendSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert msg == expected_msg

    def test_get_resumable_source_manager_is_bound_to_resume_config(self) -> None:
        manager = OmnisendSource().get_resumable_source_manager(_source_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OmnisendResumeConfig

    def test_get_non_retryable_errors_covers_auth(self) -> None:
        errors = OmnisendSource().get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        inputs = _source_inputs(schema_name="orders")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.source.omnisend_source"
        ) as mock_source:
            mock_source.return_value = MagicMock(spec=SourceResponse)
            OmnisendSource().source_for_pipeline(_config(), manager, inputs)

        _, kwargs = mock_source.call_args
        assert kwargs["api_key"] == "test-key"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["resumable_source_manager"] is manager
