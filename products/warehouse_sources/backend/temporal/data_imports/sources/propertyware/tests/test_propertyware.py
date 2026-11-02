from datetime import UTC, date, datetime
from typing import Any

from requests import PreparedRequest
from requests.structures import CaseInsensitiveDict

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.propertyware import (
    PropertywareSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.propertyware import (
    PAGE_SIZE,
    PropertywareAuth,
    PropertywareResumeConfig,
    _format_pw_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.source import PropertywareSource

BASE = "https://api.propertyware.com/pw/api/rest/v1"


def _driver() -> SourceDriver:
    return SourceDriver(
        PropertywareSource(), PropertywareSourceConfig(client_id="cid", client_secret="secret", system_id="org-1")
    )


def _page(items: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json=items)


class TestPropertywareAuth:
    def test_sets_all_three_headers(self) -> None:
        auth = PropertywareAuth(client_id="cid", client_secret="csecret", system_id="org-1")
        request = PreparedRequest()
        request.headers = CaseInsensitiveDict()
        auth(request)
        assert request.headers["x-propertyware-client-id"] == "cid"
        assert request.headers["x-propertyware-client-secret"] == "csecret"
        assert request.headers["x-propertyware-system-id"] == "org-1"

    def test_secret_values_redacts_all_three(self) -> None:
        auth = PropertywareAuth(client_id="cid", client_secret="csecret", system_id="org-1")
        assert set(auth.secret_values()) == {"cid", "csecret", "org-1"}

    def test_secret_values_omits_blank_fields(self) -> None:
        auth = PropertywareAuth(client_id="cid", client_secret="", system_id="")
        assert auth.secret_values() == ("cid",)


class TestFormatPwDatetime:
    def test_date_formats_at_midnight(self) -> None:
        assert _format_pw_datetime(date(2021, 6, 7)) == "2021-06-07T00:00:00Z"

    def test_string_passes_through(self) -> None:
        assert _format_pw_datetime("2022-03-04T05:06:07Z") == "2022-03-04T05:06:07Z"


class TestPagination:
    def test_sync_requests_pin_host_and_refuse_redirects(self) -> None:
        # Credentials ride in custom headers, not `Authorization` — `requests` won't strip those
        # on a cross-origin redirect, so every sync request (not just the validation probe) must
        # refuse to follow one and stay pinned to the Propertyware host.
        redirect = ScriptedResponse(status=302, json={}, headers={"Location": "https://evil.example.com/steal"})

        result = _driver().run("Portfolios", [redirect])

        assert result.raised is not None
        assert [request.origin for request in result.requests] == ["https://api.propertyware.com"]

    def test_requests_carry_all_three_credential_headers(self) -> None:
        result = _driver().run("Portfolios", [_page([{"id": 1}])])

        headers = result.requests[0].headers
        assert headers["x-propertyware-client-id"] == "cid"
        assert headers["x-propertyware-client-secret"] == "secret"
        assert headers["x-propertyware-system-id"] == "org-1"

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run("Portfolios", [_page([{"id": 7}])], resume_state=PropertywareResumeConfig(offset=1000))

        assert result.rows == [{"id": 7}]
        assert result.params("offset")[0] == "1000"

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("Portfolios", [_page([{"id": 7}])])

        assert result.params("offset")[0] == "0"

    def test_incremental_filter_applied_on_every_page(self) -> None:
        full_page = [{"id": i} for i in range(PAGE_SIZE)]

        result = _driver().run(
            "Portfolios",
            [_page(full_page), _page([])],
            incremental_field="lastModifiedDateTime",
            db_incremental_field_last_value=datetime(2020, 1, 1, tzinfo=UTC),
        )

        assert all(p == "2020-01-01T00:00:00Z" for p in result.params("lastModifiedDateTimeStart"))
        assert len(result.requests) == 2

    def test_raises_on_non_retryable_error(self) -> None:
        result = _driver().run("Portfolios", [ScriptedResponse(status=401, json={})])

        assert result.raised is not None
        assert "401 Client Error" in str(result.raised)

    def test_raises_on_non_list_response(self) -> None:
        # A 200 with an unexpected (non-array) body must fail loudly, not sync zero rows silently.
        result = _driver().run("Portfolios", [ScriptedResponse(json={"error": "boom"})])

        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestValidateCredentials:
    def test_probes_a_specific_endpoint_path(self) -> None:
        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            validate_credentials("cid", "secret", "org-1", path="/leases?limit=1")

        assert network.requests_log[0].url == f"{BASE}/leases?limit=1"
        assert network.requests_log[0].headers["x-propertyware-client-id"] == "cid"
        assert network.session_options[0]["redact_values"] == ("cid", "secret", "org-1")
