import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.source import ChurnkeySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.churnkey import (
    ChurnkeySourceConfig,
)

_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.source.validate_churnkey_credentials"
)


def _config() -> ChurnkeySourceConfig:
    return ChurnkeySourceConfig.from_dict({"api_key": "data_key", "app_id": "app_123"})


def _inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="Sessions",
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


class TestChurnkeySourceConfig:
    def test_lists_tables_without_credentials(self) -> None:
        # Static catalog (no I/O), so the public docs can render the table list.
        assert ChurnkeySource.lists_tables_without_credentials is True

    def test_connection_host_fields_includes_app_id(self) -> None:
        # Changing app_id retargets where the stored API key is used, so editing it must
        # require re-entering the secret.
        assert ChurnkeySource().connection_host_fields == ["app_id"]


class TestChurnkeySchemas:
    def test_get_schemas_name_filter(self) -> None:
        schemas = ChurnkeySource().get_schemas(_config(), team_id=1, names=["does-not-exist"])
        assert schemas == []


class TestChurnkeyValidateCredentials:
    @pytest.mark.parametrize(
        ("validate_return", "expected_ok"),
        [
            ((True, 200), True),
            ((False, 401), False),
            ((False, 403), False),
            ((False, 404), False),
            ((False, None), False),
        ],
    )
    def test_validate_credentials(self, validate_return: tuple[bool, int | None], expected_ok: bool) -> None:
        with patch(_VALIDATE, return_value=validate_return):
            ok, error = ChurnkeySource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        if not expected_ok:
            assert error


class TestChurnkeyPipeline:
    def test_source_for_pipeline_plumbing(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        response = ChurnkeySource().source_for_pipeline(_config(), manager, _inputs())
        assert response.name == "Sessions"
        assert response.primary_keys == ["_id"]
        assert response.partition_keys == ["createdAt"]
