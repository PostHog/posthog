from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.invoiceninja import (
    InvoiceninjaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja import (
    invoiceninja as invoiceninja_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.invoiceninja import (
    InvoiceNinjaHostNotAllowedError,
    InvoiceNinjaResumeConfig,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.source import InvoiceninjaSource


def _scripted_page(
    rows: list[dict[str, Any]],
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
    links_next: Any = "__omit__",
) -> ScriptedResponse:
    pagination: dict[str, Any] = {}
    if current_page is not None:
        pagination["current_page"] = current_page
    if total_pages is not None:
        pagination["total_pages"] = total_pages
    if links_next != "__omit__":
        pagination["links"] = {"next": links_next}
    return ScriptedResponse(json={"data": rows, "meta": {"pagination": pagination}})


def _driver(base_url: str | None = None) -> SourceDriver:
    return SourceDriver(InvoiceninjaSource(), InvoiceninjaSourceConfig(api_token="tok", base_url=base_url))


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://invoicing.co/api/v1"),
            ("", "https://invoicing.co/api/v1"),
            ("   ", "https://invoicing.co/api/v1"),
            ("https://invoicing.co", "https://invoicing.co/api/v1"),
            ("https://invoicing.co/", "https://invoicing.co/api/v1"),
            ("https://invoicing.co/api/v1", "https://invoicing.co/api/v1"),
            ("invoices.example.com", "https://invoices.example.com/api/v1"),
            ("http://invoices.example.com/", "http://invoices.example.com/api/v1"),
            ("https://invoices.example.com/api/v5", "https://invoices.example.com/api/v1"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_base_url(raw) == expected


class TestValidateCredentials:
    def test_invalid_token_403_message_always_fails(self):
        # A bad Invoice Ninja token returns 403 {"message": "Invalid token"} — reject it even at create.
        with scripted_network([ScriptedResponse(status=403, json={"message": "Invalid token"})]):
            valid, msg = validate_credentials(None, "tok", schema_name=None)
            assert valid is False
            assert msg == "Invalid Invoice Ninja API token"

    def test_permission_403_at_source_create_is_accepted(self):
        # A 403 without the "Invalid token" message is a restricted (enterprise) token, not a bad one.
        with scripted_network([ScriptedResponse(status=403, json={"message": "This action is unauthorized."})]):
            assert validate_credentials(None, "tok", schema_name=None) == (True, None)

    def test_permission_403_for_scoped_probe_fails(self):
        with scripted_network([ScriptedResponse(status=403, json={"message": "This action is unauthorized."})]):
            valid, msg = validate_credentials(None, "tok", schema_name="invoices")
            assert valid is False
            assert msg is not None

    def test_rejects_redirect_response(self):
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://elsewhere.example.com"})]
        ) as network:
            valid, msg = validate_credentials(None, "tok")
            assert valid is False
            assert msg == invoiceninja_module.HOST_NOT_ALLOWED_ERROR
            assert len(network.requests_log) == 1

    def test_blocks_unsafe_host(self):
        with mock.patch.object(invoiceninja_module, "_is_host_safe", return_value=(False, "internal address")):
            with scripted_network([]) as network:
                valid, msg = validate_credentials("http://10.0.0.1", "tok", team_id=99)
                assert valid is False
                assert msg == "internal address"
                assert network.requests_log == []

    def test_probe_hits_configured_host_with_required_headers(self):
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials("https://invoices.example.com", "tok")
            request = network.requests_log[0]
            assert request.url.startswith("https://invoices.example.com/api/v1/clients")
            assert request.headers["x-api-token"] == "tok"
            assert request.headers["x-requested-with"] == "XMLHttpRequest"

    def test_redacts_token_in_telemetry(self):
        # The token rides in X-API-TOKEN, which the transport's name-based scrubber doesn't cover, so
        # it must be passed as a redact value to keep it out of captured HTTP samples.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            validate_credentials(None, "tok")
            assert network.session_options[0]["redact_values"] == ("tok",)

    def test_rejects_plaintext_http_before_sending_token(self):
        # A plaintext http:// URL would expose the X-API-TOKEN on the wire, so reject it without
        # ever issuing the token-bearing request.
        with scripted_network([]) as network:
            valid, msg = validate_credentials("http://invoices.example.com", "tok")
            assert valid is False
            assert msg == invoiceninja_module.HTTP_NOT_ALLOWED_ERROR
            assert network.requests_log == []


class TestPagination:
    def test_resumes_from_saved_state(self):
        result = _driver().run(
            "clients",
            [_scripted_page([{"id": "9"}], current_page=3, total_pages=3)],
            resume_state=InvoiceNinjaResumeConfig(next_page=3),
        )

        assert result.params("page") == ["3"]
        assert [row["id"] for row in result.rows] == ["9"]

    def test_paginates_via_links_next_when_page_counts_absent(self):
        # Some deployments only expose `links.next` without current/total page counts.
        result = _driver().run(
            "clients",
            [
                _scripted_page([{"id": "1"}], links_next="https://next"),
                _scripted_page([{"id": "2"}], links_next=None),
            ],
        )

        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert len(result.requests) == 2
        assert result.params("page") == ["1", "2"]

    def test_empty_page_terminates(self):
        result = _driver().run("clients", [_scripted_page([], current_page=1, total_pages=5)])

        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_does_not_follow_redirects(self):
        result = _driver().run("clients", [ScriptedResponse(status=302, headers={"Location": "https://internal"})])
        # With redirects disabled the framework rejects a 3xx before following it.
        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/api/v1/clients"]

    def test_redacts_token_in_telemetry(self):
        # The api_key auth carries the token, so the framework masks it in logs / raised errors by
        # passing it to the tracked session as a redact value.
        result = _driver().run("clients", [_scripted_page([{"id": "1"}], current_page=1, total_pages=1)])
        assert result.session_options[0]["redact_values"] == ("tok",)

    def test_raises_when_host_not_allowed(self):
        with mock.patch.object(invoiceninja_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver().run("clients", [])
        assert isinstance(result.raised, InvoiceNinjaHostNotAllowedError)
        assert result.requests == []

    def test_raises_on_plaintext_http(self):
        # A plaintext http:// URL must fail before the token-bearing request goes out.
        result = _driver(base_url="http://invoices.example.com").run("clients", [])
        assert isinstance(result.raised, InvoiceNinjaHostNotAllowedError)
        assert result.requests == []
