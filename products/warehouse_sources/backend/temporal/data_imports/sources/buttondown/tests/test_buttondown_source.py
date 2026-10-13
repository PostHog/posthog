import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.buttondown.source import ButtondownSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buttondown import (
    ButtondownSourceConfig,
)


class TestButtondownSource:
    def setup_method(self) -> None:
        self.source = ButtondownSource()
        self.team_id = 123
        self.config = ButtondownSourceConfig(api_key="bd-key")

    @pytest.mark.parametrize(
        "probe_result,schema_name,expected",
        [
            ((True, 200), None, (True, None)),
            ((False, 401), None, (False, "Invalid Buttondown API key")),
            # A 403 means a real key that can't read one endpoint, so it must not block setup.
            ((False, 403), None, (True, None)),
            ((False, 403), "emails", (False, "Invalid Buttondown API key")),
            ((False, None), None, (False, "Invalid Buttondown API key")),
        ],
    )
    def test_validate_credentials(
        self, probe_result: tuple[bool, int | None], schema_name: str | None, expected: tuple[bool, str | None]
    ) -> None:
        status_code = probe_result[1]
        answer = ScriptedResponse(status=status_code) if status_code is not None else ConnectionError("reset")
        with scripted_network(always(answer)) as network:
            assert self.source.validate_credentials(self.config, self.team_id, schema_name) == expected

        assert network.requests_log[0].path == "/v1/accounts/me"
        assert network.requests_log[0].headers["authorization"] == "Token bd-key"
        assert network.requests_log[0].headers["x-api-version"] == "2026-04-01"

    def test_source_for_pipeline_honors_a_pinned_api_version(self) -> None:
        result = SourceDriver(self.source, self.config).run(
            "emails",
            [ScriptedResponse(json={"count": 1, "next": None, "previous": None, "results": [{"id": "a"}]})],
            api_version="2025-01-02",
        )

        assert result.raised is None
        assert result.rows == [{"id": "a"}]
        assert result.requests[0].headers["x-api-version"] == "2025-01-02"
