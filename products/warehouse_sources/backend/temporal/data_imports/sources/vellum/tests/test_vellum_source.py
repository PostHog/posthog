from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.source import VellumSource


class TestVellumValidateCredentials:
    @parameterized.expand(
        [
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
