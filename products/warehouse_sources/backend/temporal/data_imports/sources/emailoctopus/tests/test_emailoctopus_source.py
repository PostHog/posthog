from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.source import EmailOctopusSource


def _config() -> Any:
    config = MagicMock()
    config.api_key = "eo_key"
    return config


class TestEmailOctopusGetSchemas:
    def test_contacts_incremental_fields(self) -> None:
        schemas = {s.name: s for s in EmailOctopusSource().get_schemas(_config(), team_id=1)}
        fields = {f["field"] for f in schemas["contacts"].incremental_fields}
        assert fields == {"created_at", "last_updated_at"}


class TestEmailOctopusValidateCredentials:
    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_validate(self, _name: str, is_valid: bool) -> None:
        with patch.object(source_module, "validate_emailoctopus_credentials", return_value=is_valid):
            ok, message = EmailOctopusSource().validate_credentials(_config(), team_id=1)
        assert ok is is_valid
        assert (message is None) is is_valid


class TestEmailOctopusSourceVersions:
    def test_new_sources_default_to_v2(self) -> None:
        # New sources (no pin) must be created on the current API version.
        source = EmailOctopusSource()
        assert source.default_version == "v2"
        assert source.resolve_api_version(None) == "v2"

    @parameterized.expand([("v1",), ("v2",)])
    def test_existing_pin_is_honored(self, version: str) -> None:
        # Pinned rows — including the legacy "v1" default existing sources carry — keep their
        # version after the default bump, so their syncs are unaffected.
        source = EmailOctopusSource()
        assert version in source.supported_versions
        assert source.resolve_api_version(version) == version

    def test_v1_is_deprecated_without_sunset(self) -> None:
        # Guards the in-product deprecation banner: v1 must stay flagged (no announced sunset)
        # and the current default must not be, or the warning silently stops firing.
        source = EmailOctopusSource()
        deprecation = source.get_version_deprecation("v1")
        assert deprecation is not None
        assert deprecation.sunset_at is None
        assert source.get_version_deprecation("v2") is None
