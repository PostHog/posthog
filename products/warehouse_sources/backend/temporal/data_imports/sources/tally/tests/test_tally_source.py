from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tally import TallySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tally import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.tally.settings import TALLY_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.tally.source import TallySource


class TestTallySource:
    def setup_method(self) -> None:
        self.source = TallySource()
        self.team_id = 123
        self.config = TallySourceConfig(api_key="key-test")

    def test_pins_the_version_the_request_code_sends(self) -> None:
        assert self.source.supported_versions == (TALLY_API_VERSION,)
        assert self.source.default_version == TALLY_API_VERSION
        assert self.source.resolve_api_version(None) == TALLY_API_VERSION

    @parameterized.expand(
        [
            ("valid", True, 200, True, None),
            ("bad_key", False, 401, False, "Invalid Tally API key"),
            (
                "forbidden",
                False,
                403,
                False,
                "Your Tally API key does not have access to this data. Reconnect with a key from an account that can see these forms.",
            ),
            ("unreachable", False, None, False, "Could not reach the Tally API with this key"),
        ]
    )
    def test_validate_credentials_maps_probe_result(
        self, _name: str, probe_ok: bool, probe_status: int | None, expected_ok: bool, expected_error: str | None
    ) -> None:
        with mock.patch.object(source_module, "validate_tally_credentials", return_value=(probe_ok, probe_status)):
            ok, error = self.source.validate_credentials(self.config, self.team_id)
        assert ok is expected_ok
        assert error == expected_error
