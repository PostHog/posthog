from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest

import requests
import structlog
from parameterized import parameterized
from structlog.testing import capture_logs

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gusto import GustoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gusto.gusto import (
    DEFAULT_WINDOW_START,
    GUSTO_API_VERSION_2024_04_01,
    GUSTO_API_VERSION_2026_06_15,
    GustoClient,
    GustoResumeConfig,
    _window_bounds,
    base_url,
    extract_next_page,
    extract_rows,
    list_companies,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gusto.settings import ENDPOINTS, GUSTO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gusto.source import GustoSource


class _FakeResponse:
    def __init__(self, headers: Optional[dict[str, str]] = None) -> None:
        self.headers = headers or {}


def _me_body(company_uuids: list[str]) -> dict[str, Any]:
    return {
        "email": "admin@acme.test",
        "roles": {"payroll_admin": {"companies": [{"uuid": uuid, "name": uuid.upper()} for uuid in company_uuids]}},
    }


def _token() -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": "tok-1"})


def _config() -> GustoSourceConfig:
    return GustoSourceConfig(client_id="cid", client_secret="secret", refresh_token="refresh", environment="production")


def _driver() -> SourceDriver:
    return SourceDriver(GustoSource(), _config())


class TestBaseUrl:
    @parameterized.expand(
        [
            ("production", "production", "https://api.gusto.com"),
            ("demo", "demo", "https://api.gusto-demo.com"),
            ("blank_defaults_to_production", "", "https://api.gusto.com"),
        ]
    )
    def test_resolves_known_environments(self, _name: str, environment: str, expected: str) -> None:
        assert base_url(environment) == expected

    def test_rejects_unknown_environment(self) -> None:
        with pytest.raises(ValueError, match="Invalid Gusto environment"):
            base_url("sandbox")


class TestExtractNextPage:
    @parameterized.expand(
        [
            ("has_next_page_true", {"X-Has-Next-Page": "true"}, 3, 1, 4),
            ("has_next_page_mixed_case", {"X-Has-Next-Page": "True"}, 1, 1, 2),
            ("has_next_page_false", {"X-Has-Next-Page": "false"}, 3, 100, None),
            ("total_pages_remaining", {"X-Total-Pages": "4"}, 2, 1, 3),
            ("total_pages_exhausted", {"X-Total-Pages": "2"}, 2, 100, None),
            ("garbage_total_pages_falls_back_to_short_page", {"X-Total-Pages": "many"}, 1, 3, None),
            ("no_headers_full_page", {}, 1, 100, 2),
            ("no_headers_short_page", {}, 1, 7, None),
        ]
    )
    def test_next_page(
        self, _name: str, headers: dict[str, str], page: int, item_count: int, expected: Optional[int]
    ) -> None:
        response = cast(Any, _FakeResponse(headers))
        assert extract_next_page(response, page, item_count) == expected


class TestListCompanies:
    @parameterized.expand(
        [
            ("no_roles", {"email": "a@b.test"}),
            ("empty_role", {"roles": {"payroll_admin": {"companies": []}}}),
            ("non_dict_role", {"roles": {"payroll_admin": "nope"}}),
            ("company_without_identifier", {"roles": {"payroll_admin": {"companies": [{"name": "Acme"}]}}}),
        ]
    )
    def test_returns_empty_when_no_companies_are_reachable(self, _name: str, body: dict[str, Any]) -> None:
        with scripted_network([_token(), ScriptedResponse(json=body)]) as network:
            client = GustoClient("production", "cid", "secret", "refresh", GUSTO_API_VERSION_2026_06_15)
            assert list_companies(client) == []
        assert [request.path for request in network.requests_log] == ["/oauth/token", "/v1/me"]

    def test_rejects_unexpected_payload(self) -> None:
        with scripted_network([_token(), ScriptedResponse(json=["not", "a", "dict"])]):
            client = GustoClient("production", "cid", "secret", "refresh", GUSTO_API_VERSION_2026_06_15)
            with pytest.raises(ValueError, match="unexpected /v1/me payload"):
                list_companies(client)


class TestExtractRows:
    def test_group_without_payments_is_kept_as_a_row(self) -> None:
        body = {"contractor_payments": [{"contractor_uuid": "k-1", "reimbursement_total": "10.00"}]}
        assert extract_rows(GUSTO_ENDPOINTS["contractor_payments"], body) == [
            {"contractor_uuid": "k-1", "reimbursement_total": "10.00"}
        ]

    @parameterized.expand(
        [
            ("mirrors_bare_uuid", {"uuid": "pr-1"}, "pr-1"),
            ("keeps_existing_payroll_uuid", {"uuid": "pr-1", "payroll_uuid": "pr-9"}, "pr-9"),
        ]
    )
    def test_payroll_primary_key_is_always_populated(self, _name: str, row: dict[str, Any], expected: str) -> None:
        # `payroll_uuid` is the declared primary key, so a response that only carries `uuid` must
        # still merge instead of seeding null-keyed duplicates.
        assert extract_rows(GUSTO_ENDPOINTS["payrolls"], [row])[0]["payroll_uuid"] == expected

    def test_non_mapping_body_yields_nothing(self) -> None:
        assert extract_rows(GUSTO_ENDPOINTS["employees"], "oops") == []


class TestWindowBounds:
    @parameterized.expand(
        [
            ("date", date(2024, 5, 6), "2024-05-06"),
            ("datetime", datetime(2024, 5, 6, 12, 30, tzinfo=UTC), "2024-05-06"),
            ("iso_string", "2024-05-06T12:30:00+00:00", "2024-05-06"),
            ("plain_date_string", "2024-05-06", "2024-05-06"),
        ]
    )
    def test_watermark_becomes_the_window_start(self, _name: str, watermark: Any, expected: str) -> None:
        assert _window_bounds(watermark).start == expected


class TestGustoClient:
    @parameterized.expand([(GUSTO_API_VERSION_2024_04_01,), (GUSTO_API_VERSION_2026_06_15,)])
    def test_session_pins_the_api_version_and_redacts_secrets(self, api_version: str) -> None:
        # Each supported version reaches the header verbatim, so a pinned source syncs under its pin.
        with scripted_network([]) as network:
            GustoClient("production", "cid", "secret", "refresh", api_version)
        kwargs = network.session_options[0]
        assert kwargs["headers"]["X-Gusto-API-Version"] == api_version
        assert set(kwargs["redact_values"]) == {"secret", "refresh"}
        # Payroll PII must never reach HTTP sample capture.
        assert kwargs["capture"] is False

    def test_persistent_401_is_raised_rather_than_reminted_forever(self) -> None:
        answers = [_token(), ScriptedResponse(status=401), _token(), ScriptedResponse(status=401)]
        with scripted_network(answers) as network:
            client = GustoClient("production", "cid", "secret", "refresh", GUSTO_API_VERSION_2026_06_15)
            with pytest.raises(requests.HTTPError):
                client.request("/v1/me")
        assert [request.path for request in network.requests_log] == [
            "/oauth/token",
            "/v1/me",
            "/oauth/token",
            "/v1/me",
        ]

    @parameterized.expand([("forbidden", 403), ("not_found", 404), ("server_error", 500)])
    def test_error_statuses_raise(self, _name: str, status: int) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            return _token() if request.path == "/oauth/token" else ScriptedResponse(status=status)

        with scripted_network(respond), capture_logs() as logs:
            client = GustoClient(
                "production",
                "cid",
                "secret",
                "refresh",
                GUSTO_API_VERSION_2026_06_15,
                logger=structlog.get_logger(),
            )
            with pytest.raises(requests.HTTPError):
                client.request("/v1/me")
        errors = [entry["event"] for entry in logs if entry["log_level"] == "error"]
        assert len(errors) == 1
        assert f"status={status}" in errors[0]

    def test_missing_access_token_is_an_explicit_failure(self) -> None:
        with scripted_network([ScriptedResponse(json={})]):
            client = GustoClient("production", "cid", "secret", "refresh", GUSTO_API_VERSION_2026_06_15)
            with pytest.raises(ValueError, match="did not return an access token"):
                client.mint_token()


class TestGetRowsPaginated:
    def test_resumes_at_the_saved_company_and_page(self) -> None:
        # c-1 is absent from the script on purpose: resuming must not re-request it.
        result = _driver().run(
            "locations",
            [
                _token(),
                ScriptedResponse(json=_me_body(["c-1", "c-2"])),
                ScriptedResponse(json=[{"uuid": "l-9"}], headers={"X-Total-Pages": "3"}),
            ],
            resume_state=GustoResumeConfig(company_index=1, next_page=3),
        )
        assert result.raised is None
        assert [row["uuid"] for row in result.rows] == ["l-9"]
        assert result.paths == ["/oauth/token", "/v1/me", "/v1/companies/c-2/locations"]
        assert result.params("page")[-1] == "3"

    def test_stops_on_an_empty_page(self) -> None:
        result = _driver().run(
            "employees",
            [
                _token(),
                ScriptedResponse(json=_me_body(["c-1"])),
                ScriptedResponse(json=[{"uuid": "e-1"}], headers={"X-Has-Next-Page": "true"}),
                ScriptedResponse(json=[], headers={"X-Has-Next-Page": "true"}),
            ],
        )
        assert result.raised is None
        assert [row["uuid"] for row in result.rows] == ["e-1"]
        assert result.params("page") == [None, None, "1", "2"]


class TestGetRowsCompanies:
    def test_yields_the_full_company_detail_per_company(self) -> None:
        result = _driver().run(
            "companies",
            [
                _token(),
                ScriptedResponse(json=_me_body(["c-1", "c-2"])),
                ScriptedResponse(json={"uuid": "c-1", "name": "Acme"}),
                ScriptedResponse(json={"uuid": "c-2", "name": "Globex"}),
            ],
        )
        assert result.raised is None
        assert [row["name"] for row in result.rows] == ["Acme", "Globex"]


class TestGetRowsUnpaginated:
    def test_full_list_is_read_in_one_request(self) -> None:
        # A page-size response must not trigger a page 2 that would re-read the same list.
        departments = [{"uuid": f"d-{index}"} for index in range(100)]
        result = _driver().run(
            "departments",
            [_token(), ScriptedResponse(json=_me_body(["c-1"])), ScriptedResponse(json=departments)],
        )
        assert result.raised is None
        assert len(result.rows) == 100
        assert {row["_company_uuid"] for row in result.rows} == {"c-1"}
        assert result.paths == ["/oauth/token", "/v1/me", "/v1/companies/c-1/departments"]
        assert result.params("page")[-1] is None


class TestGetRowsFanOut:
    def test_resumes_partway_through_a_company_employee_list(self) -> None:
        result = _driver().run(
            "jobs",
            [
                _token(),
                ScriptedResponse(json=_me_body(["c-1"])),
                ScriptedResponse(json=[{"uuid": "e-2"}, {"uuid": "e-1"}], headers={"X-Total-Pages": "1"}),
                ScriptedResponse(json=[{"uuid": "j-1", "title": "Designer"}]),
            ],
            resume_state=GustoResumeConfig(company_index=0, employee_index=1),
        )
        assert result.raised is None
        assert [row["_employee_uuid"] for row in result.rows] == ["e-2"]
        assert result.paths[-1] == "/v1/employees/e-2/jobs"


class TestGetRowsWindowed:
    def _payroll_script(self) -> list[ScriptedResponse]:
        return [
            _token(),
            ScriptedResponse(json=_me_body(["c-1", "c-2"])),
            ScriptedResponse(json=[{"uuid": "pr-3", "check_date": "2024-03-15"}], headers={"X-Total-Pages": "1"}),
            ScriptedResponse(
                json=[
                    {"payroll_uuid": "pr-2", "check_date": "2024-02-15"},
                    {"payroll_uuid": "pr-1", "check_date": "2024-01-15"},
                ],
                headers={"X-Total-Pages": "1"},
            ),
        ]

    def test_first_sync_requests_the_full_history_window(self) -> None:
        result = _driver().run("payrolls", self._payroll_script())
        assert result.raised is None
        assert result.requests[2].param("start_date") == DEFAULT_WINDOW_START

    def test_unpaginated_windowed_endpoint_flattens_and_sorts(self) -> None:
        result = _driver().run(
            "contractor_payments",
            [
                _token(),
                ScriptedResponse(json=_me_body(["c-1"])),
                ScriptedResponse(
                    json={
                        "contractor_payments": [
                            {
                                "contractor_uuid": "k-1",
                                "payments": [
                                    {"uuid": "p-2", "date": "2024-06-01"},
                                    {"uuid": "p-1", "date": "2024-01-01"},
                                ],
                            }
                        ]
                    },
                ),
            ],
        )
        assert result.raised is None
        assert [row["uuid"] for row in result.rows] == ["p-1", "p-2"]
        assert {row["_company_uuid"] for row in result.rows} == {"c-1"}


class TestGustoSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_primary_keys_match_the_endpoint_catalog(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_token(), ScriptedResponse(json=_me_body([]))])
        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == GUSTO_ENDPOINTS[endpoint].primary_keys
        assert result.response.sort_mode == "asc"

    @parameterized.expand([("jobs",), ("recurring_reimbursements",), ("contractor_payments",), ("pay_periods",)])
    def test_fan_out_and_keyless_tables_include_their_parent_in_the_key(self, endpoint: str) -> None:
        # Child rows from every parent land in one table, so a per-parent identifier alone would
        # collide and make each merge multi-match.
        assert any(key.startswith("_") for key in GUSTO_ENDPOINTS[endpoint].primary_keys)

    def test_items_are_lazy(self) -> None:
        source = GustoSource()
        inputs = source_inputs("employees")
        manager = source.get_resumable_source_manager(inputs)
        with scripted_network([]) as network:
            response = source.source_for_pipeline(_config(), manager, inputs)
            # Building the response must not touch the network — only iterating does.
            items = cast(Iterable[Any], response.items())
            assert isinstance(items, Iterator)
        assert network.requests_log == []


class TestValidateCredentials:
    def _validate(self, answers: list[ScriptedResponse]) -> tuple[bool, Optional[str]]:
        with scripted_network(answers):
            return validate_credentials("production", "cid", "secret", "refresh", GUSTO_API_VERSION_2026_06_15)

    def test_accepts_credentials_that_reach_a_company(self) -> None:
        assert self._validate([_token(), ScriptedResponse(json=_me_body(["c-1"]))]) == (True, None)

    @parameterized.expand([("bad_request", 400), ("unauthorized", 401)])
    def test_rejected_token_exchange_explains_rotation(self, _name: str, status: int) -> None:
        ok, message = self._validate([ScriptedResponse(status=status)])
        assert ok is False
        assert message is not None and "rotates refresh tokens" in message

    def test_forbidden_company_read_asks_for_a_payroll_admin(self) -> None:
        ok, message = self._validate([_token(), ScriptedResponse(status=403)])
        assert ok is False
        assert message is not None and "payroll admin" in message

    def test_token_without_companies_is_rejected(self) -> None:
        ok, message = self._validate([_token(), ScriptedResponse(json={"roles": {}})])
        assert ok is False
        assert message is not None and "no companies" in message

    def test_invalid_environment_is_reported(self) -> None:
        with scripted_network([]) as network:
            ok, message = validate_credentials("sandbox", "cid", "secret", "refresh", GUSTO_API_VERSION_2026_06_15)
        assert ok is False
        assert message is not None and "Invalid Gusto environment" in message
        assert network.requests_log == []
