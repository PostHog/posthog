import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.moxie import MoxieSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie import moxie as moxie_module
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.moxie import (
    MoxieHostNotAllowedError,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.moxie.source import MoxieSource

BASE_URL = "https://pod00.withmoxie.dev/api/public"


def _driver(base_url: str = BASE_URL) -> SourceDriver:
    return SourceDriver(MoxieSource(), MoxieSourceConfig(base_url=base_url, api_key="test_key"))


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://pod00.withmoxie.dev/api/public", "https://pod00.withmoxie.dev/api/public"),
            ("https://pod00.withmoxie.dev/api/public/", "https://pod00.withmoxie.dev/api/public"),
            ("pod00.withmoxie.dev", "https://pod00.withmoxie.dev/api/public"),
            ("http://pod00.withmoxie.dev", "http://pod00.withmoxie.dev/api/public"),
            ("  https://pod00.withmoxie.dev/api/public  ", "https://pod00.withmoxie.dev/api/public"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalizes_variants(self, raw: str | None, expected: str) -> None:
        assert normalize_base_url(raw) == expected


class TestMoxieTransport:
    @pytest.mark.parametrize("endpoint", ["email_templates", "invoice_templates", "vendor_names", "form_names"])
    def test_scalar_endpoints_wrap_bare_strings_into_rows(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=["Template A", "Template B"])])

        assert result.raised is None
        assert result.items == [[{"name": "Template A"}, {"name": "Template B"}]]

    def test_workspace_users_flattens_nested_user_id(self) -> None:
        row = {"userType": "OWNER", "user": {"userId": 42, "firstName": "Alex"}}
        result = _driver().run("workspace_users", [ScriptedResponse(json=[row])])

        assert result.raised is None
        assert result.items == [[{**row, "user_id": 42}]]

    def test_host_check_blocks_before_any_request(self) -> None:
        with mock.patch.object(moxie_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver().run("clients", [])

        assert isinstance(result.raised, MoxieHostNotAllowedError)
        assert "internal address" in str(result.raised)
        assert result.requests == []

    def test_plaintext_http_is_rejected_before_any_request(self) -> None:
        result = _driver(base_url="http://pod00.withmoxie.dev/api/public").run("clients", [])

        assert isinstance(result.raised, MoxieHostNotAllowedError)
        assert "HTTPS" in str(result.raised)
        assert result.requests == []


class TestValidateCredentials:
    def test_probes_clients_list_with_api_key_header_and_redaction(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials(BASE_URL, "test_key", team_id=1)

        assert len(network.requests_log) == 1
        assert network.requests_log[0].url == f"{BASE_URL}/action/clients/list"
        assert network.requests_log[0].headers["x-api-key"] == "test_key"
        # The key must be registered for redaction in tracked telemetry.
        assert network.session_options[0]["redact_values"] == ("test_key",)

    def test_blank_base_url_is_rejected(self) -> None:
        is_valid, message = validate_credentials("", "test_key", team_id=1)
        assert is_valid is False
        assert message == "That doesn't look like a Moxie workspace base URL."

    def test_plaintext_http_is_rejected_before_any_request(self) -> None:
        is_valid, message = validate_credentials("http://pod00.withmoxie.dev/api/public", "test_key", team_id=1)
        assert is_valid is False
        assert message is not None and "HTTPS" in message

    def test_host_not_allowed_is_rejected(self) -> None:
        with mock.patch.object(moxie_module, "_is_host_safe", return_value=(False, "internal address")):
            is_valid, message = validate_credentials(BASE_URL, "test_key", team_id=1)
        assert is_valid is False
        assert message == "internal address"
