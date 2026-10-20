from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.source import VellumSource


class TestVellumValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, 200), True, None),
            ("bad_key_403", (False, 403), False, "Invalid Vellum API key"),
            ("unauthorized_401", (False, 401), False, "Invalid Vellum API key"),
            ("network_error", (False, None), False, "Could not connect to Vellum. Please try again later."),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_result: tuple[bool, int | None], expected_ok: bool, expected_msg: str | None
    ) -> None:
        source = VellumSource()
        config = MagicMock(api_key="test-key")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.vellum.source.check_credentials",
            return_value=probe_result,
        ):
            ok, msg = source.validate_credentials(config, team_id=1)
        assert ok is expected_ok
        assert msg == expected_msg
