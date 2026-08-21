from typing import Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.veracode import (
    VeracodeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.veracode.source import VeracodeSource


def _config() -> VeracodeSourceConfig:
    return VeracodeSourceConfig(api_id="the-id", api_secret="the-secret", region="com")


def _inputs(schema_name: str) -> SourceInputs:
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
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, 200), None, True),
            ("forbidden_at_create_is_accepted", (False, 403), None, True),
            ("forbidden_for_schema_is_rejected", (False, 403), "findings", False),
            ("unauthorized_is_rejected", (False, 401), None, False),
            ("unreachable_is_rejected", (False, None), None, False),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_result: tuple[bool, Optional[int]], schema_name: Optional[str], expected_ok: bool
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.veracode.source.validate_veracode_credentials",
            return_value=probe_result,
        ):
            ok, error = VeracodeSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestResumableWiring:
    def test_source_for_pipeline_rejects_unknown_endpoint(self) -> None:
        try:
            VeracodeSource().source_for_pipeline(_config(), MagicMock(), _inputs("not_an_endpoint"))
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for unknown endpoint")
