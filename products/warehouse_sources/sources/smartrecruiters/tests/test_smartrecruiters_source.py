from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network
from products.warehouse_sources.sources.smartrecruiters._config import SmartrecruitersSourceConfig
from products.warehouse_sources.sources.smartrecruiters.source import SmartrecruitersSource


class TestValidateCredentials:
    def test_probe_sends_the_key_in_the_smart_token_header(self) -> None:
        with scripted_network([ScriptedResponse(status=200, json={"content": []})]) as network:
            ok, message = SmartrecruitersSource().validate_credentials(
                SmartrecruitersSourceConfig(api_key="sr-key"), team_id=1
            )

        assert (ok, message) == (True, None)
        assert network.requests_log[0].path == "/jobs"
        assert network.requests_log[0].headers["x-smarttoken"] == "sr-key"
        assert network.session_options[0]["redact_values"] == ("sr-key",)

    def test_unknown_table_fails_without_a_request(self) -> None:
        with scripted_network([]) as network:
            ok, message = SmartrecruitersSource().validate_credentials(
                SmartrecruitersSourceConfig(api_key="sr-key"), team_id=1, schema_name="interviews"
            )

        assert ok is False
        assert message is not None
        assert network.requests_log == []
