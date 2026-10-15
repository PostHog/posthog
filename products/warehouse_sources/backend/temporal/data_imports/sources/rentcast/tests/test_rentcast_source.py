from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rentcast import (
    RentCastSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.rentcast import RentCastResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.source import RentCastSource


class TestRentCastSource:
    def setup_method(self) -> None:
        self.source = RentCastSource()
        self.team_id = 123
        self.config = RentCastSourceConfig(api_key="rc-key")

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.rentcast.io/v1/properties?limit=500&offset=0",),
            ("403 Client Error: Forbidden for url: https://api.rentcast.io/v1/listings/sale?limit=500&offset=0",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.rentcast.io/v1/properties",),
            ("429 Client Error: Too Many Requests for url: https://api.rentcast.io/v1/listings/sale",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            ("unauthorized", 401, (False, "Invalid RentCast API key")),
            ("ok", 200, (True, None)),
        ]
    )
    def test_validate_credentials_probes_with_the_configured_key(
        self, _name: str, status: int, expected: tuple[bool, str | None]
    ) -> None:
        # The status->message mapping is covered in test_rentcast.py.
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            result = self.source.validate_credentials(self.config, self.team_id)

        assert result == expected
        assert network.requests_log[0].headers["x-api-key"] == "rc-key"

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "properties",
            [ScriptedResponse(json=[])],
            resume_state=RentCastResumeConfig(offset=500),
        )

        assert result.requests[0].headers["x-api-key"] == "rc-key"
        assert result.paths == ["/v1/properties"]
        # The resume manager reaches the extraction: the first page is the saved offset.
        assert result.params("offset") == ["500"]
        assert result.response is not None
        assert result.response.name == "properties"

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        result = SourceDriver(self.source, self.config).run("not_a_table", [])

        assert isinstance(result.raised, ValueError)
        assert "Unknown RentCast schema 'not_a_table'" in str(result.raised)
