from typing import Optional

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.freshsales import (
    DEFAULT_PAGE_SIZE,
    FreshsalesResumeConfig,
    _normalize_alias,
    check_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.freshsales.source import FreshsalesSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.freshsales import (
    FreshsalesSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(FreshsalesSource(), FreshsalesSourceConfig.from_dict({"domain": "acme", "api_key": "key"}))


class TestNormalizeAlias:
    @parameterized.expand(
        [
            ("plain_alias", "acme", "acme"),
            ("uppercase", "ACME", "acme"),
            ("full_host", "acme.myfreshworks.com", "acme"),
            ("with_scheme", "https://acme.myfreshworks.com", "acme"),
            ("with_path", "acme.myfreshworks.com/crm/sales", "acme"),
            ("hyphenated", "personal-1234", "personal-1234"),
            ("whitespace", "  acme  ", "acme"),
        ]
    )
    def test_valid(self, _name: str, value: str, expected: str) -> None:
        assert _normalize_alias(value) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("underscore", "acme_corp"),
            ("at_sign", "acme@evil.com"),
            ("leading_hyphen", "-acme"),
            ("space_inside", "acme corp"),
        ]
    )
    def test_invalid(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            _normalize_alias(value)


class TestResolveViewId:
    def test_falls_back_to_first_view(self) -> None:
        result = _driver().run(
            "contacts",
            [
                ScriptedResponse(json={"filters": [{"id": 7, "name": "Recently created"}]}),
                ScriptedResponse(json={"contacts": []}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/crm/sales/api/contacts/filters", "/crm/sales/api/contacts/view/7"]


class TestGetRows:
    def test_paginates_until_total_pages(self) -> None:
        result = _driver().run(
            "sales_activities",
            [
                ScriptedResponse(
                    json={"sales_activities": [{"id": i} for i in range(100)], "meta": {"total_pages": 2}}
                ),
                ScriptedResponse(json={"sales_activities": [{"id": 100}], "meta": {"total_pages": 2}}),
            ],
        )

        assert result.raised is None
        assert len(result.items) == 2
        assert result.items[0][0] == {"id": 0}
        assert result.items[1] == [{"id": 100}]
        assert result.params("page") == ["1", "2"]
        # State saved after the first page only (pointing at the next page to fetch).
        assert [state.next_page for state in result.saved_states] == [2]

    def test_stops_on_empty_page(self) -> None:
        result = _driver().run("sales_activities", [ScriptedResponse(json={"sales_activities": []})])

        assert result.raised is None
        assert result.items == []

    def test_resumes_from_saved_state(self) -> None:
        # Resume at page 2 — the view id is already known so /filters is never fetched again.
        result = _driver().run(
            "contacts",
            [ScriptedResponse(json={"contacts": [{"id": 5}]})],
            resume_state=FreshsalesResumeConfig(next_page=2, view_id=99),
        )

        assert result.raised is None
        assert result.items == [[{"id": 5}]]
        assert result.paths == ["/crm/sales/api/contacts/view/99"]
        assert result.params("page") == ["2"]

    def test_view_endpoint_resolves_view_first(self) -> None:
        result = _driver().run(
            "contacts",
            [
                ScriptedResponse(json={"filters": [{"id": 3, "name": "All Contacts"}]}),
                ScriptedResponse(json={"contacts": [{"id": 1}]}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": 1}]]
        assert result.paths == ["/crm/sales/api/contacts/filters", "/crm/sales/api/contacts/view/3"]

    @parameterized.expand(
        [
            # Freshsales doesn't publish selector response bodies; an unexpected envelope key must not
            # silently sync an empty table.
            ("owners_unexpected_key", "owners", "portal_users"),
            ("contact_statuses", "contact_statuses", "contact_statuses"),
            ("contact_statuses_unexpected_key", "contact_statuses", "statuses"),
            ("territories", "territories", "territories"),
        ]
    )
    def test_selector_reads_the_whole_collection_in_one_request(
        self, _name: str, endpoint: str, envelope_key: str
    ) -> None:
        rows = [{"id": i, "name": f"Row {i}"} for i in range(DEFAULT_PAGE_SIZE)]
        result = _driver().run(endpoint, always(ScriptedResponse(json={envelope_key: rows})))

        assert result.raised is None
        assert result.items == [rows]
        assert result.paths == [f"/crm/sales/api/selector/{endpoint}"]
        assert result.params("page") == [None]

    def test_deal_stages_walks_every_pipeline(self) -> None:
        # /selector/deal_stages covers the default pipeline only, so a single request would miss the
        # stages that deals in every other pipeline point at.
        result = _driver().run(
            "deal_stages",
            [
                ScriptedResponse(json={"deal_pipelines": [{"id": 1, "name": "Sales"}, {"id": 2, "name": "Renewals"}]}),
                ScriptedResponse(json={"deal_stages": [{"id": 10, "name": "New", "deal_pipeline_id": 1}]}),
                ScriptedResponse(json={"deal_stages": [{"id": 20, "name": "Due", "deal_pipeline_id": 2}]}),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [10, 20]
        assert result.paths == [
            "/crm/sales/api/selector/deal_pipelines",
            "/crm/sales/api/selector/deal_pipelines/1/deal_stages",
            "/crm/sales/api/selector/deal_pipelines/2/deal_stages",
        ]

    def test_list_contacts_pages_every_list_and_tags_rows_with_list_id(self) -> None:
        # /lists and /contacts/lists/{id} are paginated, unlike selectors, and the contact rows don't
        # say which list they came from.
        result = _driver().run(
            "list_contacts",
            [
                ScriptedResponse(json={"lists": [{"id": 1}, {"id": 2}], "meta": {"total_pages": 1}}),
                ScriptedResponse(json={"contacts": [{"id": i} for i in range(100)], "meta": {"total_pages": 2}}),
                ScriptedResponse(json={"contacts": [{"id": 100}], "meta": {"total_pages": 2}}),
                ScriptedResponse(json={"contacts": [{"id": 0}], "meta": {"total_pages": 1}}),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 102
        assert result.rows[100] == {"id": 100, "list_id": 1}
        assert result.rows[101] == {"id": 0, "list_id": 2}
        assert result.paths == [
            "/crm/sales/api/lists",
            "/crm/sales/api/contacts/lists/1",
            "/crm/sales/api/contacts/lists/1",
            "/crm/sales/api/contacts/lists/2",
        ]
        assert result.params("page") == ["1", "1", "2", "1"]
        assert result.params("per_page") == ["100"] * 4
        assert result.saved_states == [FreshsalesResumeConfig(next_page=2, parent_id=1)]

    @parameterized.expand(
        [
            ("saved_list_still_exists", 2, ["contacts/lists/2?page=3&per_page=100"]),
            (
                "saved_list_deleted",
                9,
                ["contacts/lists/1?page=1&per_page=100", "contacts/lists/2?page=1&per_page=100"],
            ),
        ]
    )
    def test_list_contacts_resumes_at_saved_list_and_page(
        self, _name: str, saved_list_id: int, expected_child_calls: list[str]
    ) -> None:
        result = _driver().run(
            "list_contacts",
            [
                ScriptedResponse(json={"lists": [{"id": 1}, {"id": 2}], "meta": {"total_pages": 1}}),
                *[ScriptedResponse(json={"contacts": [{"id": 5}]}) for _ in expected_child_calls],
            ],
            resume_state=FreshsalesResumeConfig(next_page=3, parent_id=saved_list_id),
        )

        assert result.raised is None
        assert [request.url.rsplit("/api/", 1)[1] for request in result.requests[1:]] == expected_child_calls

    def test_tolerates_missing_object(self) -> None:
        # leads object absent -> /filters 404 -> stream yields nothing instead of failing.
        result = _driver().run("leads", [ScriptedResponse(status=404)])

        assert result.raised is None
        assert result.items == []


class TestCheckCredentials:
    @parameterized.expand(
        [
            ("forbidden", 403, False, 403),
            ("not_found", 404, False, 404),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool, expected_status: Optional[int]) -> None:
        answer = ScriptedResponse(status=status, json={})
        script = always(answer) if status >= 500 else [answer]
        with scripted_network(script) as network:
            ok, error, status_code = check_credentials("key", "acme")

        assert ok is expected_ok
        assert status_code == expected_status
        if not expected_ok:
            assert error
        assert network.requests_log[0].path == "/crm/sales/api/selector/owners"

    def test_invalid_domain_short_circuits(self) -> None:
        ok, error, status_code = check_credentials("key", "bad domain", None)
        assert ok is False
        assert status_code is None
        assert error is not None and "domain" in error.lower()

    def test_schema_probe_targets_endpoint(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            check_credentials("key", "acme", "contacts")

        # contacts requires a view, so it probes the filters endpoint.
        assert network.requests_log[0].path == "/crm/sales/api/contacts/filters"


class TestFreshsalesSource:
    @parameterized.expand(
        [
            ("contacts", ["id"], "created_at"),
            ("deals", ["id"], "created_at"),
            ("sales_activities", ["id"], None),
            ("open_tasks", ["id"], None),
            ("list_contacts", ["list_id", "id"], "created_at"),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: Optional[str]) -> None:
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/filters"):
                return ScriptedResponse(json={"filters": [{"id": 1, "name": "All"}]})
            return ScriptedResponse(json={})

        result = _driver().run(endpoint, answer)

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == primary_keys
        assert result.response.sort_mode == "asc"
        if partition_key:
            assert result.response.partition_mode == "datetime"
            assert result.response.partition_keys == [partition_key]
            assert result.response.partition_format == "month"
        else:
            assert result.response.partition_mode is None
            assert result.response.partition_keys is None
