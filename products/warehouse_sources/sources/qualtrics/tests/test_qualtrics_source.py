from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qualtrics import (
    QualtricsAuthMethodConfig,
    QualtricsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualtrics import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.qualtrics.qualtrics import QualtricsCredentials


def _config(selection: str = "api_token") -> QualtricsSourceConfig:
    return QualtricsSourceConfig(
        datacenter_id="iad1",
        auth_method=QualtricsAuthMethodConfig(
            selection=selection,  # type: ignore[arg-type]
            api_token="tok-123",
            client_id="client",
            client_secret="shhh",
        ),
    )


def _inputs(schema_name: str = "surveys", **kwargs: Any) -> SourceInputs:
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
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(kwargs)
    return SourceInputs(**defaults)


class TestQualtricsSource:
    def setup_method(self) -> None:
        self.source = source_module.QualtricsSource()

    def test_retargeting_the_host_re_requires_credentials(self) -> None:
        assert self.source.connection_host_fields == ["datacenter_id"]

    @pytest.mark.parametrize(
        "selection, expected",
        [
            ("api_token", QualtricsCredentials(method="api_token", api_token="tok-123")),
            (
                "oauth_client_credentials",
                QualtricsCredentials(method="oauth_client_credentials", client_id="client", client_secret="shhh"),
            ),
        ],
    )
    def test_credentials_are_read_from_the_selected_auth_method(
        self, selection: str, expected: QualtricsCredentials
    ) -> None:
        assert source_module._credentials_from_config(_config(selection)) == expected

    def test_source_for_pipeline_passes_the_incremental_watermark(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())
        inputs = _inputs(
            schema_name="survey_responses",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        with mock.patch.object(source_module, "qualtrics_source") as build:
            self.source.source_for_pipeline(_config(), manager, inputs)

        kwargs = build.call_args.kwargs
        assert kwargs["endpoint"] == "survey_responses"
        assert kwargs["api_version"] == "v3"
        assert kwargs["team_id"] == 1
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_drops_the_watermark_on_a_full_refresh(self) -> None:
        manager = self.source.get_resumable_source_manager(_inputs())
        inputs = _inputs(
            schema_name="surveys",
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        with mock.patch.object(source_module, "qualtrics_source") as build:
            self.source.source_for_pipeline(_config(), manager, inputs)

        assert build.call_args.kwargs["db_incremental_field_last_value"] is None
