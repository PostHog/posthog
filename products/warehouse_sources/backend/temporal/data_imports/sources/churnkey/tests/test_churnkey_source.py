import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.source import ChurnkeySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.churnkey import (
    ChurnkeySourceConfig,
)

_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.source.validate_churnkey_credentials"
)


def _config() -> ChurnkeySourceConfig:
    return ChurnkeySourceConfig.from_dict({"api_key": "data_key", "app_id": "app_123"})


class TestChurnkeySchemas:
    def test_get_schemas(self) -> None:
        schemas = ChurnkeySource().get_schemas(_config(), team_id=1)
        names = {s.name for s in schemas}
        assert "Sessions" in names

        sessions = next(s for s in schemas if s.name == "Sessions")
        assert sessions.supports_incremental is False
        assert sessions.supports_append is False
        assert sessions.detected_primary_keys == ["_id"]


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

    def test_app_id_error_is_specific(self) -> None:
        with patch(_VALIDATE, return_value=(False, 404)):
            _, error = ChurnkeySource().validate_credentials(_config(), team_id=1)
        assert error is not None and "App ID" in error
