from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.faire.source import FaireSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.faire import FaireSourceConfig


class TestFaireSource:
    def setup_method(self) -> None:
        self.source = FaireSource()
        self.team_id = 123
        self.config = FaireSourceConfig(api_key="token")

    def test_api_version(self) -> None:
        assert self.source.default_version == "v2"
        assert self.source.default_version in self.source.supported_versions
        assert self.source.api_docs_url is not None
        assert self.source.api_docs_url.startswith("https://")

    @parameterized.expand(
        [
            ((False, None), False, "Could not connect to Faire with the provided API access token"),
        ]
    )
    def test_validate_credentials(
        self, probe_result: tuple[bool, int | None], expected_valid: bool, expected_message: str | None
    ) -> None:
        _, status_code = probe_result
        script = (
            always(ConnectionError("connection lost"))
            if status_code is None
            else [ScriptedResponse(status=status_code)]
        )
        with scripted_network(script) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert {request.path for request in network.requests_log} == {"/external-api/v2/brands/profile"}
        assert {request.headers["x-faire-access-token"] for request in network.requests_log} == {"token"}
