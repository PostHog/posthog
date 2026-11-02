import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.source import ChurnkeySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.churnkey import (
    ChurnkeySourceConfig,
)


def _config() -> ChurnkeySourceConfig:
    return ChurnkeySourceConfig.from_dict({"api_key": "data_key", "app_id": "app_123"})


class TestChurnkeySourceConfig:
    def test_lists_tables_without_credentials(self) -> None:
        # Static catalog (no I/O), so the public docs can render the table list.
        assert ChurnkeySource.lists_tables_without_credentials is True

    def test_connection_host_fields_includes_app_id(self) -> None:
        # Changing app_id retargets where the stored API key is used, so editing it must
        # require re-entering the secret.
        assert ChurnkeySource().connection_host_fields == ["app_id"]


class TestChurnkeyValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_ok"),
        [
            (404, False),
            (None, False),
        ],
    )
    def test_validate_credentials(self, status_code: int | None, expected_ok: bool) -> None:
        script = always(ConnectionError("boom")) if status_code is None else [ScriptedResponse(status=status_code)]
        with scripted_network(script):
            ok, error = ChurnkeySource().validate_credentials(_config(), team_id=1)

        assert ok is expected_ok
        if not expected_ok:
            assert error


class TestChurnkeyPipeline:
    def test_source_for_pipeline_plumbing(self) -> None:
        result = SourceDriver(ChurnkeySource(), _config()).run("Sessions", [ScriptedResponse(json=[{"_id": "1"}])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == "Sessions"
        assert result.response.primary_keys == ["_id"]
        assert result.response.partition_keys == ["createdAt"]
