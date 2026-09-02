from typing import Optional

from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.thinkific import (
    ThinkificSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.source import ThinkificSource

PATCH_VALIDATE = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.source.validate_thinkific_credentials"
)


def _config(api_key: str = "key", subdomain: str = "mycompany") -> ThinkificSourceConfig:
    return ThinkificSourceConfig(api_key=api_key, subdomain=subdomain)


class TestThinkificSourceConfig:
    def test_source_config_fields(self) -> None:
        cfg = ThinkificSource().get_source_config
        fields = {f.name: f for f in cfg.fields}
        assert set(fields) == {"api_key", "subdomain"}
        api_key, subdomain = fields["api_key"], fields["subdomain"]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert isinstance(subdomain, SourceFieldInputConfig)
        # The secret must be a password field; the subdomain is a plain text identifier.
        assert api_key.type == "password"
        assert api_key.secret is True
        assert subdomain.type == "text"
        assert subdomain.secret is False


class TestThinkificValidateCredentials:
    def test_rejects_invalid_subdomain_without_calling_api(self) -> None:
        with patch(PATCH_VALIDATE) as mock_validate:
            ok, err = ThinkificSource().validate_credentials(_config(subdomain="bad domain"), team_id=1)
        assert ok is False
        assert err is not None
        mock_validate.assert_not_called()

    def test_valid_credentials(self) -> None:
        with patch(PATCH_VALIDATE, return_value=(True, 200)):
            ok, err = ThinkificSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert err is None

    @parameterized.expand(
        [
            # (status, schema_name, expected_ok) - 403 at source-create (schema None) is accepted, but a
            # per-schema 403 is surfaced as a failure.
            ("forbidden_at_create", 403, None, True),
            ("forbidden_for_schema", 403, "courses", False),
            ("unauthorized_at_create", 401, None, False),
        ]
    )
    def test_status_handling(self, _name: str, status: int, schema_name: Optional[str], expected_ok: bool) -> None:
        with patch(PATCH_VALIDATE, return_value=(False, status)):
            ok, _err = ThinkificSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok
