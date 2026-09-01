from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
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
    get_rows,
    gusto_source,
    list_companies,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gusto.settings import ENDPOINTS, GUSTO_ENDPOINTS


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        body: Any = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.status_code = status_code
        self._body = body if body is not None else []
        self.headers = headers or {}
        self.text = ""

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=cast(Any, self))


class _FakeSession:
    """Routes requests by path, replaying a queued response list per path."""

    def __init__(
        self,
        routes: dict[str, list[_FakeResponse]],
        token_responses: Optional[list[_FakeResponse]] = None,
    ) -> None:
        self._routes = routes
        self._token_responses = token_responses or [_FakeResponse(200, {"access_token": "tok-1"})]
        self.get_urls: list[str] = []
        self.post_urls: list[str] = []

    def _next(self, queue: list[_FakeResponse]) -> _FakeResponse:
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def get(self, url: str, headers: Optional[dict[str, str]] = None, timeout: Optional[int] = None) -> _FakeResponse:
        self.get_urls.append(url)
        path = urlparse(url).path
        if path not in self._routes:
            raise AssertionError(f"unexpected Gusto request to {path}")
        return self._next(self._routes[path])

    def post(
        self,
        url: str,
        data: Optional[dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> _FakeResponse:
        self.post_urls.append(url)
        return self._next(self._token_responses)


class _FakeResumableManager(ResumableSourceManager[GustoResumeConfig]):
    def __init__(self, state: Optional[GustoResumeConfig] = None) -> None:
        self._state = state
        self.saved: list[GustoResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> Optional[GustoResumeConfig]:
        return self._state

    def save_state(self, data: GustoResumeConfig) -> None:
        self.saved.append(data)


def _me_body(company_uuids: list[str]) -> dict[str, Any]:
    return {
        "email": "admin@acme.test",
        "roles": {"payroll_admin": {"companies": [{"uuid": uuid, "name": uuid.upper()} for uuid in company_uuids]}},
    }


def _run(
    endpoint: str,
    routes: dict[str, list[_FakeResponse]],
    manager: Optional[_FakeResumableManager] = None,
    db_incremental_field_last_value: Any = None,
) -> tuple[list[list[dict[str, Any]]], _FakeSession, _FakeResumableManager]:
    session = _FakeSession(routes)
    resume_manager = manager or _FakeResumableManager()
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gusto.gusto.make_tracked_session",
        return_value=session,
    ):
        batches = list(
            get_rows(
                environment="production",
                client_id="cid",
                client_secret="secret",
                refresh_token="refresh",
                endpoint=endpoint,
                api_version=GUSTO_API_VERSION_2026_06_15,
                logger=MagicMock(),
                resumable_source_manager=resume_manager,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
        )
    return batches, session, resume_manager


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
        response = cast(Any, _FakeResponse(200, [], headers))
        assert extract_next_page(response, page, item_count) == expected

    def test_has_next_page_header_wins_over_total_pages(self) -> None:
        # Endpoints that ship both must not terminate early on a stale total-pages count.
        response = cast(Any, _FakeResponse(200, [], {"X-Has-Next-Page": "true", "X-Total-Pages": "1"}))
        assert extract_next_page(response, 1, 100) == 2


class TestListCompanies:
    def _client(self, body: Any) -> GustoClient:
        session = _FakeSession({"/v1/me": [_FakeResponse(200, body)]})
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gusto.gusto.make_tracked_session",
            return_value=session,
        ):
            return GustoClient("production", "cid", "secret", "refresh", GUSTO_API_VERSION_2026_06_15)

    def test_returns_companies_sorted_by_uuid(self) -> None:
        client = self._client(_me_body(["c-zeta", "c-alpha"]))
        assert [company["uuid"] for company in list_companies(client)] == ["c-alpha", "c-zeta"]

    def test_dedupes_companies_shared_across_roles(self) -> None:
        body = {
            "roles": {
                "payroll_admin": {"companies": [{"uuid": "c-1"}]},
                "manager": {"companies": [{"uuid": "c-1"}, {"uuid": "c-2"}]},
            }
        }
        client = self._client(body)
        assert [company["uuid"] for company in list_companies(client)] == ["c-1", "c-2"]

    @parameterized.expand(
        [
            ("no_roles", {"email": "a@b.test"}),
            ("empty_role", {"roles": {"payroll_admin": {"companies": []}}}),
            ("non_dict_role", {"roles": {"payroll_admin": "nope"}}),
            ("company_without_identifier", {"roles": {"payroll_admin": {"companies": [{"name": "Acme"}]}}}),
        ]
    )
    def test_returns_empty_when_no_companies_are_reachable(self, _name: str, body: dict[str, Any]) -> None:
        assert list_companies(self._client(body)) == []

    def test_rejects_unexpected_payload(self) -> None:
        with pytest.raises(ValueError, match="unexpected /v1/me payload"):
            list_companies(self._client(["not", "a", "dict"]))


class TestExtractRows:
    def test_bare_array_body(self) -> None:
        rows = extract_rows(GUSTO_ENDPOINTS["employees"], [{"uuid": "e-1"}, "junk", {"uuid": "e-2"}])
        assert rows == [{"uuid": "e-1"}, {"uuid": "e-2"}]

    def test_single_object_body_for_company_detail(self) -> None:
        assert extract_rows(GUSTO_ENDPOINTS["companies"], {"uuid": "c-1"}) == [{"uuid": "c-1"}]

    def test_contractor_payments_are_flattened_out_of_their_contractor_group(self) -> None:
        body = {
            "total": {"reimbursements": "0.00"},
            "contractor_payments": [
                {
                    "contractor_uuid": "k-1",
                    "payments": [{"uuid": "p-1", "date": "2024-01-05"}, {"uuid": "p-2", "date": "2024-02-05"}],
                },
                {"contractor_uuid": "k-2", "payments": [{"uuid": "p-3", "date": "2024-01-05"}]},
            ],
        }
        rows = extract_rows(GUSTO_ENDPOINTS["contractor_payments"], body)
        assert [(row["uuid"], row["contractor_uuid"]) for row in rows] == [
            ("p-1", "k-1"),
            ("p-2", "k-1"),
            ("p-3", "k-2"),
        ]

    def test_contractor_payment_keeps_its_own_contractor_uuid(self) -> None:
        body = {
            "contractor_payments": [{"contractor_uuid": "k-1", "payments": [{"uuid": "p-1", "contractor_uuid": "k-9"}]}]
        }
        rows = extract_rows(GUSTO_ENDPOINTS["contractor_payments"], body)
        assert rows[0]["contractor_uuid"] == "k-9"

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
    def test_defaults_to_full_history_without_a_watermark(self) -> None:
        window = _window_bounds(None)
        assert window.start == DEFAULT_WINDOW_START
        # The window reaches forward because payrolls and pay periods are scheduled ahead of today.
        assert window.end > datetime.now(UTC).date().isoformat()

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
    def _client(self, session: _FakeSession, environment: str = "production") -> GustoClient:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gusto.gusto.make_tracked_session",
            return_value=session,
        ):
            return GustoClient(environment, "cid", "secret", "refresh", GUSTO_API_VERSION_2026_06_15, MagicMock())

    @parameterized.expand([(GUSTO_API_VERSION_2024_04_01,), (GUSTO_API_VERSION_2026_06_15,)])
    def test_session_pins_the_api_version_and_redacts_secrets(self, api_version: str) -> None:
        # Each supported version reaches the header verbatim, so a pinned source syncs under its pin.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gusto.gusto.make_tracked_session"
        ) as make_session:
            GustoClient("production", "cid", "secret", "refresh", api_version)
        kwargs = make_session.call_args.kwargs
        assert kwargs["headers"]["X-Gusto-API-Version"] == api_version
        assert set(kwargs["redact_values"]) == {"secret", "refresh"}
        # Payroll PII must never reach HTTP sample capture.
        assert kwargs["capture"] is False

    def test_mints_a_token_before_the_first_request(self) -> None:
        session = _FakeSession({"/v1/me": [_FakeResponse(200, {"roles": {}})]})
        client = self._client(session)
        client.request("/v1/me")
        assert session.post_urls == ["https://api.gusto.com/oauth/token"]

    def test_remints_once_when_the_token_expires_mid_sync(self) -> None:
        session = _FakeSession(
            {"/v1/me": [_FakeResponse(401), _FakeResponse(200, {"roles": {}})]},
            token_responses=[
                _FakeResponse(200, {"access_token": "tok-1"}),
                _FakeResponse(200, {"access_token": "tok-2"}),
            ],
        )
        client = self._client(session)
        response = client.request("/v1/me")
        assert response.status_code == 200
        assert len(session.post_urls) == 2

    def test_persistent_401_is_raised_rather_than_reminted_forever(self) -> None:
        session = _FakeSession({"/v1/me": [_FakeResponse(401)]})
        client = self._client(session)
        with pytest.raises(requests.HTTPError):
            client.request("/v1/me")
        assert len(session.post_urls) == 2

    @parameterized.expand([("forbidden", 403), ("not_found", 404), ("server_error", 500)])
    def test_error_statuses_raise(self, _name: str, status: int) -> None:
        session = _FakeSession({"/v1/me": [_FakeResponse(status)]})
        with pytest.raises(requests.HTTPError):
            self._client(session).request("/v1/me")

    def test_missing_access_token_is_an_explicit_failure(self) -> None:
        session = _FakeSession({"/v1/me": [_FakeResponse(200, {})]}, token_responses=[_FakeResponse(200, {})])
        with pytest.raises(ValueError, match="did not return an access token"):
            self._client(session).mint_token()

    def test_demo_environment_targets_the_demo_host(self) -> None:
        session = _FakeSession({"/v1/me": [_FakeResponse(200, {"roles": {}})]})
        client = self._client(session, environment="demo")
        client.request("/v1/me")
        assert session.get_urls == ["https://api.gusto-demo.com/v1/me"]


class TestGetRowsPaginated:
    def test_walks_every_company_and_stamps_the_parent(self) -> None:
        routes = {
            "/v1/me": [_FakeResponse(200, _me_body(["c-1", "c-2"]))],
            "/v1/companies/c-1/locations": [
                _FakeResponse(200, [{"uuid": "l-1"}], {"X-Total-Pages": "2"}),
                _FakeResponse(200, [{"uuid": "l-2"}], {"X-Total-Pages": "2"}),
            ],
            "/v1/companies/c-2/locations": [_FakeResponse(200, [{"uuid": "l-3"}], {"X-Total-Pages": "1"})],
        }
        batches, _, manager = _run("locations", routes)

        assert [[row["uuid"] for row in batch] for batch in batches] == [["l-1"], ["l-2"], ["l-3"]]
        assert [row["_company_uuid"] for batch in batches for row in batch] == ["c-1", "c-1", "c-2"]
        # Page state is checkpointed mid-company, and each finished company advances the index.
        assert GustoResumeConfig(company_index=0, next_page=2) in manager.saved
        assert manager.saved[-1] == GustoResumeConfig(company_index=2)

    def test_resumes_at_the_saved_company_and_page(self) -> None:
        routes = {
            "/v1/me": [_FakeResponse(200, _me_body(["c-1", "c-2"]))],
            "/v1/companies/c-2/locations": [_FakeResponse(200, [{"uuid": "l-9"}], {"X-Total-Pages": "3"})],
        }
        # c-1 is absent from the routes on purpose: resuming must not re-request it.
        batches, session, _ = _run(
            "locations", routes, manager=_FakeResumableManager(GustoResumeConfig(company_index=1, next_page=3))
        )

        assert [row["uuid"] for batch in batches for row in batch] == ["l-9"]
        assert parse_qs(urlparse(session.get_urls[-1]).query)["page"] == ["3"]

    def test_stops_on_an_empty_page(self) -> None:
        routes = {
            "/v1/me": [_FakeResponse(200, _me_body(["c-1"]))],
            "/v1/companies/c-1/employees": [
                _FakeResponse(200, [{"uuid": "e-1"}], {"X-Has-Next-Page": "true"}),
                _FakeResponse(200, [], {"X-Has-Next-Page": "true"}),
            ],
        }
        batches, _, _ = _run("employees", routes)
        assert [row["uuid"] for batch in batches for row in batch] == ["e-1"]


class TestGetRowsCompanies:
    def test_yields_the_full_company_detail_per_company(self) -> None:
        routes = {
            "/v1/me": [_FakeResponse(200, _me_body(["c-1", "c-2"]))],
            "/v1/companies/c-1": [_FakeResponse(200, {"uuid": "c-1", "name": "Acme"})],
            "/v1/companies/c-2": [_FakeResponse(200, {"uuid": "c-2", "name": "Globex"})],
        }
        batches, _, _ = _run("companies", routes)
        assert [row["name"] for batch in batches for row in batch] == ["Acme", "Globex"]


class TestGetRowsFanOut:
    def _routes(self) -> dict[str, list[_FakeResponse]]:
        return {
            "/v1/me": [_FakeResponse(200, _me_body(["c-1"]))],
            "/v1/companies/c-1/employees": [
                _FakeResponse(200, [{"uuid": "e-2"}, {"uuid": "e-1"}], {"X-Total-Pages": "1"})
            ],
            "/v1/employees/e-1/jobs": [_FakeResponse(200, [{"uuid": "j-1", "title": "Engineer"}])],
            "/v1/employees/e-2/jobs": [_FakeResponse(200, [{"uuid": "j-1", "title": "Designer"}])],
        }

    def test_jobs_carry_both_parent_identifiers(self) -> None:
        batches, _, _ = _run("jobs", self._routes())
        rows = [row for batch in batches for row in batch]
        # Employees are walked in uuid order, and the same job uuid under two employees stays
        # distinct because the parent employee is part of the primary key.
        assert [(row["_employee_uuid"], row["uuid"], row["title"]) for row in rows] == [
            ("e-1", "j-1", "Engineer"),
            ("e-2", "j-1", "Designer"),
        ]
        assert {row["_company_uuid"] for row in rows} == {"c-1"}

    def test_checkpoints_after_each_employee(self) -> None:
        _, _, manager = _run("jobs", self._routes())
        assert manager.saved[:2] == [
            GustoResumeConfig(company_index=0, employee_index=1),
            GustoResumeConfig(company_index=0, employee_index=2),
        ]

    def test_resumes_partway_through_a_company_employee_list(self) -> None:
        routes = self._routes()
        del routes["/v1/employees/e-1/jobs"]
        batches, _, _ = _run(
            "jobs", routes, manager=_FakeResumableManager(GustoResumeConfig(company_index=0, employee_index=1))
        )
        assert [row["_employee_uuid"] for batch in batches for row in batch] == ["e-2"]


class TestGetRowsWindowed:
    def _payroll_routes(self) -> dict[str, list[_FakeResponse]]:
        return {
            "/v1/me": [_FakeResponse(200, _me_body(["c-1", "c-2"]))],
            "/v1/companies/c-1/payrolls": [
                _FakeResponse(200, [{"uuid": "pr-3", "check_date": "2024-03-15"}], {"X-Total-Pages": "1"})
            ],
            "/v1/companies/c-2/payrolls": [
                _FakeResponse(
                    200,
                    [
                        {"payroll_uuid": "pr-2", "check_date": "2024-02-15"},
                        {"payroll_uuid": "pr-1", "check_date": "2024-01-15"},
                    ],
                    {"X-Total-Pages": "1"},
                )
            ],
        }

    def test_rows_are_sorted_ascending_across_companies(self) -> None:
        # `sort_mode="asc"` promises the pipeline an ascending cursor, and Gusto documents no
        # ordering — so the source has to establish it.
        batches, _, _ = _run("payrolls", self._payroll_routes())
        rows = [row for batch in batches for row in batch]
        assert [row["check_date"] for row in rows] == ["2024-01-15", "2024-02-15", "2024-03-15"]
        assert [row["payroll_uuid"] for row in rows] == ["pr-1", "pr-2", "pr-3"]

    def test_watermark_becomes_the_start_date_filter(self) -> None:
        _, session, _ = _run("payrolls", self._payroll_routes(), db_incremental_field_last_value=date(2024, 2, 1))
        query = parse_qs(urlparse(session.get_urls[1]).query)
        assert query["start_date"] == ["2024-02-01"]
        assert query["end_date"][0] > datetime.now(UTC).date().isoformat()

    def test_first_sync_requests_the_full_history_window(self) -> None:
        _, session, _ = _run("payrolls", self._payroll_routes())
        assert parse_qs(urlparse(session.get_urls[1]).query)["start_date"] == [DEFAULT_WINDOW_START]

    def test_windowed_endpoints_do_not_checkpoint(self) -> None:
        # The whole window is buffered so it can be sorted; there is no partial position to resume.
        _, _, manager = _run("payrolls", self._payroll_routes())
        assert manager.saved == []

    def test_unpaginated_windowed_endpoint_flattens_and_sorts(self) -> None:
        routes = {
            "/v1/me": [_FakeResponse(200, _me_body(["c-1"]))],
            "/v1/companies/c-1/contractor_payments": [
                _FakeResponse(
                    200,
                    {
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
                )
            ],
        }
        batches, _, _ = _run("contractor_payments", routes)
        rows = [row for batch in batches for row in batch]
        assert [row["uuid"] for row in rows] == ["p-1", "p-2"]
        assert {row["_company_uuid"] for row in rows} == {"c-1"}


class TestGustoSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_primary_keys_match_the_endpoint_catalog(self, endpoint: str) -> None:
        response = gusto_source(
            environment="production",
            client_id="cid",
            client_secret="secret",
            refresh_token="refresh",
            endpoint=endpoint,
            api_version=GUSTO_API_VERSION_2026_06_15,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == GUSTO_ENDPOINTS[endpoint].primary_keys
        assert response.sort_mode == "asc"

    @parameterized.expand([("jobs",), ("contractor_payments",), ("pay_periods",)])
    def test_fan_out_and_keyless_tables_include_their_parent_in_the_key(self, endpoint: str) -> None:
        # Child rows from every parent land in one table, so a per-parent identifier alone would
        # collide and make each merge multi-match.
        assert any(key.startswith("_") for key in GUSTO_ENDPOINTS[endpoint].primary_keys)

    def test_items_are_lazy(self) -> None:
        response = gusto_source(
            environment="production",
            client_id="cid",
            client_secret="secret",
            refresh_token="refresh",
            endpoint="employees",
            api_version=GUSTO_API_VERSION_2026_06_15,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),
        )
        # Building the response must not touch the network — only iterating does.
        items = cast(Iterable[Any], response.items())
        assert isinstance(items, Iterator)


class TestValidateCredentials:
    def _validate(
        self,
        routes: dict[str, list[_FakeResponse]],
        token_responses: Optional[list[_FakeResponse]] = None,
    ) -> tuple[bool, Optional[str]]:
        session = _FakeSession(routes, token_responses=token_responses)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gusto.gusto.make_tracked_session",
            return_value=session,
        ):
            return validate_credentials("production", "cid", "secret", "refresh", GUSTO_API_VERSION_2026_06_15)

    def test_accepts_credentials_that_reach_a_company(self) -> None:
        assert self._validate({"/v1/me": [_FakeResponse(200, _me_body(["c-1"]))]}) == (True, None)

    @parameterized.expand([("bad_request", 400), ("unauthorized", 401)])
    def test_rejected_token_exchange_explains_rotation(self, _name: str, status: int) -> None:
        ok, message = self._validate({"/v1/me": []}, token_responses=[_FakeResponse(status)])
        assert ok is False
        assert message is not None and "rotates refresh tokens" in message

    def test_other_token_errors_report_the_status(self) -> None:
        ok, message = self._validate({"/v1/me": []}, token_responses=[_FakeResponse(500)])
        assert (ok, message) == (False, "Gusto returned HTTP 500 when requesting an access token")

    def test_forbidden_company_read_asks_for_a_payroll_admin(self) -> None:
        ok, message = self._validate({"/v1/me": [_FakeResponse(403)]})
        assert ok is False
        assert message is not None and "payroll admin" in message

    def test_token_without_companies_is_rejected(self) -> None:
        ok, message = self._validate({"/v1/me": [_FakeResponse(200, {"roles": {}})]})
        assert ok is False
        assert message is not None and "no companies" in message

    def test_invalid_environment_is_reported(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gusto.gusto.make_tracked_session",
            return_value=_FakeSession({}),
        ):
            ok, message = validate_credentials("sandbox", "cid", "secret", "refresh", GUSTO_API_VERSION_2026_06_15)
        assert ok is False
        assert message is not None and "Invalid Gusto environment" in message


class TestWindowReach:
    def test_future_window_covers_scheduled_pay_periods(self) -> None:
        window = _window_bounds(None)
        assert date.fromisoformat(window.end) > datetime.now(UTC).date() + timedelta(days=180)
