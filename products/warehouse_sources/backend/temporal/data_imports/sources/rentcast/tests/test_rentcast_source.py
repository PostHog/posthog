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

    @parameterized.expand(
        [
            ("not_set", None, False),
            ("empty", "", False),
            ("malformed", "1234", False),
            ("configured", "10001, 20002", True),
        ]
    )
    def test_markets_is_enabled_by_default_only_with_zip_codes(
        self, _name: str, zip_codes: str | None, expected: bool
    ) -> None:
        config = RentCastSourceConfig(api_key="rc-key", zip_codes=zip_codes)
        schemas = {schema.name: schema for schema in self.source.get_schemas(config, self.team_id)}

        assert schemas["markets"].should_sync_default is expected
        assert schemas["properties"].should_sync_default is True

    def test_validate_credentials_rejects_bad_zip_codes_without_a_request(self) -> None:
        config = RentCastSourceConfig(api_key="rc-key", zip_codes="10001, 1234")
        with scripted_network(always(ScriptedResponse(status=200, json=[]))) as network:
            valid, message = self.source.validate_credentials(config, self.team_id)

        assert valid is False
        assert message is not None and "1234" in message
        assert network.requests_log == []

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
