from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.gainsight_cs import (
    GainsightCsHostNotAllowedError,
    GainsightCsPageBudgetExhaustedError,
    GainsightCsResponseTooLargeError,
    GainsightCsResponseTooSlowError,
    GainsightCsResumeConfig,
    _normalize_row,
    _parse_fields,
    _picklist_rows,
    _read_capped_json,
    _rows_from_body,
    normalize_domain,
    parse_custom_objects,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.source import GainsightCsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gainsightcs import (
    GainsightCsSourceConfig,
)

HOST_CHECK_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.gainsight_cs._is_host_safe"
)
PAGE_SIZE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.gainsight_cs.MAX_PAGE_SIZE"
)
GAINSIGHT_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.gainsight_cs"

DOMAIN = "acme.gainsightcloud.com"


def _describe_body(fields: list[dict[str, Any]], object_name: str = "company") -> dict[str, Any]:
    return {"result": True, "data": [{"objectName": object_name, "fields": fields}]}


def _field(name: str, data_type: str = "STRING", sortable: bool = True) -> dict[str, Any]:
    return {"fieldName": name, "dataType": data_type, "meta": {"sortable": sortable}}


class TestResponseEnvelope:
    @parameterized.expand(
        [
            ("records_at_data", {"result": True, "data": [{"Gsid": "1"}]}, [{"Gsid": "1"}]),
            ("records_nested", {"result": True, "data": {"records": [{"Gsid": "1"}]}}, [{"Gsid": "1"}]),
            ("empty_nested", {"result": True, "data": {"records": []}}, []),
            ("empty_list", {"result": True, "data": []}, []),
            ("null_data", {"result": True, "data": None}, []),
        ]
    )
    def test_reads_both_documented_envelopes(self, _name: str, body: dict[str, Any], expected: list[Any]) -> None:
        # The Company docs put the records directly on `data`, Timeline nests them under
        # `data.records`. Reading only one shape turns the other into a single junk row.
        assert _rows_from_body(body, "company") == expected

    def test_rejects_an_unrecognized_data_shape(self) -> None:
        with pytest.raises(ValueError, match="unexpected record shape"):
            _rows_from_body({"result": True, "data": {"count": 3}}, "company")

    def test_surfaces_an_api_failure_returned_on_a_200(self) -> None:
        body = {"result": False, "errorDesc": "Object not found", "data": None}
        with pytest.raises(ValueError, match="Object not found"):
            _rows_from_body(body, "company")


class TestParseFields:
    def test_raises_when_the_object_exposes_no_fields(self) -> None:
        with pytest.raises(ValueError, match="no fields for object"):
            _parse_fields(_describe_body([]), "company")

    def test_never_substitutes_another_objects_fields(self) -> None:
        # The requested object is present but empty. Borrowing the neighbour's fields would build a
        # `select` of columns this object doesn't have.
        body = {
            "result": True,
            "data": [
                {"objectName": "company", "fields": []},
                {"objectName": "company_person", "fields": [_field("PersonId")]},
            ],
        }
        with pytest.raises(ValueError, match="no fields for object"):
            _parse_fields(body, "company")


class TestNormalizeRow:
    @parameterized.expand(
        [
            ("epoch_millis", 1521691459693, datetime(2018, 3, 22, 4, 4, 19, 693000, tzinfo=UTC)),
            ("iso_string_untouched", "2024-02-05T07:17:16Z", "2024-02-05T07:17:16Z"),
            ("none_untouched", None, None),
        ]
    )
    def test_converts_date_fields(self, _name: str, value: Any, expected: Any) -> None:
        assert _normalize_row({"CreatedDate": value}, frozenset({"CreatedDate"})) == {"CreatedDate": expected}


class TestCustomObjects:
    @parameterized.expand(
        [
            ("trims_whitespace", " health__gc , renewal__gc ", ["health__gc", "renewal__gc"]),
            ("drops_path_traversal", "../../etc/passwd,ok__gc", ["ok__gc"]),
            ("drops_query_injection", "company?x=1", []),
            ("drops_standard_objects", "company,health__gc", ["health__gc"]),
            ("empty", "", []),
            ("none", None, []),
        ]
    )
    def test_only_object_shaped_names_survive(self, _name: str, raw: str | None, expected: list[str]) -> None:
        # These names are interpolated into the request path, so anything that isn't a bare
        # object name has to be dropped before it can reshape the URL.
        assert parse_custom_objects(raw) == expected


class TestNormalizeDomain:
    @parameterized.expand(
        [
            ("bare", "acme.gainsightcloud.com"),
            ("with_scheme", "https://acme.gainsightcloud.com"),
            ("with_trailing_slash", "https://acme.gainsightcloud.com/"),
            ("with_path", "acme.gainsightcloud.com/v1/data"),
            ("padded", "  acme.gainsightcloud.com  "),
        ]
    )
    def test_reduces_user_input_to_a_bare_host(self, _name: str, raw: str) -> None:
        assert normalize_domain(raw) == DOMAIN


class TestPagination:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(GainsightCsSource(), GainsightCsSourceConfig(domain=DOMAIN, access_key="key"))

    def test_checkpoints_then_stops_when_the_page_budget_runs_out(self) -> None:
        full_page = {"result": True, "data": [{"Gsid": "1"}, {"Gsid": "2"}]}
        with mock.patch(PAGE_SIZE_PATCH, 2), mock.patch(f"{GAINSIGHT_MODULE}.MAX_PAGES_PER_ATTEMPT", 3):
            result = self._driver().run(
                "company",
                [ScriptedResponse(json=_describe_body([_field("Gsid")]))]
                + [ScriptedResponse(json=full_page) for _ in range(3)],
            )

        assert isinstance(result.raised, GainsightCsPageBudgetExhaustedError)
        assert result.paths == [
            "/v1/meta/services/objects/company/describe",
            "/v1/data/objects/query/company",
            "/v1/data/objects/query/company",
            "/v1/data/objects/query/company",
        ]
        assert [request.json()["offset"] for request in result.requests[1:]] == [0, 2, 4]
        assert result.saved_states[-1] == GainsightCsResumeConfig(offset=6)
        assert result.final_state == GainsightCsResumeConfig(offset=6)

    def test_resumes_from_the_saved_offset(self) -> None:
        with mock.patch(PAGE_SIZE_PATCH, 2):
            result = self._driver().run(
                "company",
                [
                    ScriptedResponse(json=_describe_body([_field("Gsid")])),
                    ScriptedResponse(json={"result": True, "data": [{"Gsid": "9"}]}),
                ],
                resume_state=GainsightCsResumeConfig(offset=4),
            )

        assert result.raised is None
        assert result.requests[1].json()["offset"] == 4
        assert result.rows == [{"Gsid": "9"}]
        assert result.final_state is None

    def test_refuses_a_host_that_resolves_internally(self) -> None:
        driver = SourceDriver(GainsightCsSource(), GainsightCsSourceConfig(domain="internal.corp", access_key="key"))
        with mock.patch(HOST_CHECK_PATCH, return_value=(False, "Host not allowed")):
            result = driver.run(
                "company",
                [],
                team_id=1,
            )

        assert isinstance(result.raised, GainsightCsHostNotAllowedError)
        assert result.requests == []


class TestCtaConfiguration:
    def test_flattens_each_category_and_drops_repeats(self) -> None:
        status = {"gsid": "s1", "name": "New", "picklistCategory": "CTA_STATUS"}
        body = {
            "result": True,
            "data": {
                "CTA_STATUS": [status, status],
                "CTA_PRIORITY": [{"gsid": "p1", "name": "High"}],
                "CTA_REASON": [{"name": "no id"}],
            },
        }

        assert _picklist_rows(body) == [status, {"gsid": "p1", "name": "High", "picklistCategory": "CTA_PRIORITY"}]

    def test_requests_every_category_for_companies(self) -> None:
        driver = SourceDriver(GainsightCsSource(), GainsightCsSourceConfig(domain=DOMAIN, access_key="key"))
        result = driver.run(
            "cta_configuration",
            [ScriptedResponse(json={"result": True, "data": {"CTA_TYPE": [{"gsid": "t1", "name": "Risk"}]}})],
        )

        assert result.raised is None
        assert result.paths == ["/v2/cockpit/admin/picklist/lite"]
        assert result.params("category") == ["CTA_TYPE,CTA_STATUS,CTA_PRIORITY,CTA_REASON"]
        assert result.params("et") == ["COMPANY"]
        assert result.rows == [{"gsid": "t1", "name": "Risk", "picklistCategory": "CTA_TYPE"}]


class TestCtaTasks:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(GainsightCsSource(), GainsightCsSourceConfig(domain=DOMAIN, access_key="key"))

    @staticmethod
    def _page(rows: list[dict[str, Any]]) -> ScriptedResponse:
        return ScriptedResponse(json={"result": True, "data": rows})

    def test_walks_every_cta_and_pages_through_its_tasks(self) -> None:
        describe = ScriptedResponse(json=_describe_body([_field("Gsid")], "call_to_action"))
        with mock.patch(PAGE_SIZE_PATCH, 3), mock.patch(f"{GAINSIGHT_MODULE}.TASK_PAGE_SIZE", 2):
            result = self._driver().run(
                "cta_task",
                [
                    describe,
                    self._page([{"Gsid": "ctaA"}, {"Gsid": "../x"}, {"Gsid": "ctaB"}]),
                    self._page([{"Gsid": "t1"}, {"Gsid": "t2"}]),
                    self._page([{"Gsid": "t3"}]),
                    self._page([]),
                    self._page([{"Gsid": "ctaC"}]),
                    self._page([{"Gsid": "t4"}]),
                ],
            )

        assert result.raised is None
        assert result.paths == [
            "/v1/meta/services/objects/call_to_action/describe",
            "/v1/data/objects/query/call_to_action",
            "/v2/cockpit/task/list/ctaA",
            "/v2/cockpit/task/list/ctaA",
            "/v2/cockpit/task/list/ctaB",
            "/v1/data/objects/query/call_to_action",
            "/v2/cockpit/task/list/ctaC",
        ]
        assert result.requests[1].json() == {
            "select": ["Gsid"],
            "limit": 3,
            "offset": 0,
            "orderBy": {"Gsid": "asc"},
        }
        assert result.requests[5].json()["offset"] == 3
        assert result.params("pn") == [None, None, "1", "2", "1", None, "1"]
        assert result.rows == [
            {"Gsid": "t1", "CtaId": "ctaA"},
            {"Gsid": "t2", "CtaId": "ctaA"},
            {"Gsid": "t3", "CtaId": "ctaA"},
            {"Gsid": "t4", "CtaId": "ctaC"},
        ]
        assert result.saved_states == [
            GainsightCsResumeConfig(offset=0, task_page=2),
            GainsightCsResumeConfig(offset=1),
            GainsightCsResumeConfig(offset=3),
            GainsightCsResumeConfig(offset=4),
        ]
        assert result.final_state == GainsightCsResumeConfig(offset=4)
        assert result.completed_state is None

    def test_resumes_mid_way_through_a_ctas_tasks(self) -> None:
        with mock.patch(f"{GAINSIGHT_MODULE}.TASK_PAGE_SIZE", 2):
            result = self._driver().run(
                "cta_task",
                [
                    ScriptedResponse(json=_describe_body([_field("Gsid")], "call_to_action")),
                    self._page([{"Gsid": "ctaD"}, {"Gsid": "ctaE"}]),
                    self._page([{"Gsid": "t9"}]),
                    self._page([{"Gsid": "t10"}]),
                ],
                resume_state=GainsightCsResumeConfig(offset=7, task_page=3),
            )

        assert result.raised is None
        assert result.requests[1].json()["offset"] == 7
        assert result.params("pn") == [None, None, "3", "1"]
        assert result.rows == [{"Gsid": "t9", "CtaId": "ctaD"}, {"Gsid": "t10", "CtaId": "ctaE"}]

    def test_checkpoints_the_next_task_page_when_a_cta_exhausts_its_budget(self) -> None:
        full_page = self._page([{"Gsid": "t1"}, {"Gsid": "t2"}])
        with (
            mock.patch(f"{GAINSIGHT_MODULE}.TASK_PAGE_SIZE", 2),
            mock.patch(f"{GAINSIGHT_MODULE}.MAX_TASK_PAGES_PER_CTA", 2),
        ):
            result = self._driver().run(
                "cta_task",
                [
                    ScriptedResponse(json=_describe_body([_field("Gsid")], "call_to_action")),
                    self._page([{"Gsid": "ctaA"}]),
                    full_page,
                    full_page,
                ],
                resume_state=GainsightCsResumeConfig(offset=5, task_page=4),
            )

        assert isinstance(result.raised, GainsightCsPageBudgetExhaustedError)
        assert result.params("pn") == [None, None, "4", "5"]
        assert result.final_state == GainsightCsResumeConfig(offset=5, task_page=6)


class TestCappedResponses:
    def _streaming(self, chunks: list[bytes]) -> mock.MagicMock:
        response = mock.MagicMock()
        response.iter_content.return_value = iter(chunks)
        return response

    def test_refuses_a_body_past_the_size_cap(self) -> None:
        response = self._streaming([b"x" * 10, b"y" * 10])
        with mock.patch(f"{GAINSIGHT_MODULE}.MAX_RESPONSE_BYTES", 15), pytest.raises(GainsightCsResponseTooLargeError):
            _read_capped_json(response)
        response.close.assert_called_once_with()

    def test_refuses_a_body_that_dribbles_past_the_time_cap(self) -> None:
        response = self._streaming([b"{", b"}"])
        with (
            mock.patch(f"{GAINSIGHT_MODULE}.time.monotonic", side_effect=[0.0, 1.0, 500.0]),
            mock.patch(f"{GAINSIGHT_MODULE}.MAX_DOWNLOAD_SECONDS", 100),
            pytest.raises(GainsightCsResponseTooSlowError),
        ):
            _read_capped_json(response)
        response.close.assert_called_once_with()


class TestValidateCredentials:
    def _validate(self, response: ScriptedResponse) -> tuple[bool, str | None]:
        with scripted_network(always(response)):
            return validate_credentials(DOMAIN, "key", "company", 1)

    @parameterized.expand(
        [
            ("unauthorized", 401, "rejected the access key"),
            ("forbidden", 403, "rejected the access key"),
            ("missing_object", 404, "no object named 'company'"),
            ("server_error", 500, "unexpected status (500)"),
        ]
    )
    def test_maps_each_status_to_the_message_a_user_reads(self, _name: str, status: int, expected: str) -> None:
        ok, error = self._validate(ScriptedResponse(status=status, json={}))
        assert ok is False
        assert error is not None and expected in error

    def test_accepts_a_describe_that_returns_fields(self) -> None:
        assert self._validate(ScriptedResponse(json=_describe_body([_field("Gsid")]))) == (True, None)

    def test_rejects_a_200_that_describes_nothing(self) -> None:
        ok, error = self._validate(ScriptedResponse(json=_describe_body([])))
        assert ok is False
        assert error is not None and "no fields for object" in error

    def test_rejects_a_redirect_rather_than_replaying_the_key(self) -> None:
        redirect = ScriptedResponse(status=302, json={}, headers={"Location": "https://evil.example.com/"})
        with scripted_network([redirect]) as network:
            ok, error = validate_credentials(DOMAIN, "key", "company", 1)
        assert ok is False
        assert error is not None and "isn't allowed" in error
        assert [request.path for request in network.requests_log] == ["/v1/meta/services/objects/company/describe"]

    def test_rejects_a_domain_that_resolves_internally(self) -> None:
        with mock.patch(HOST_CHECK_PATCH, return_value=(False, "Host not allowed")):
            assert validate_credentials("internal.corp", "key", "company", 1) == (False, "Host not allowed")

    def test_rejects_a_domain_that_is_not_a_hostname(self) -> None:
        ok, error = validate_credentials("acme corp.gainsightcloud.com", "key", "company", None)
        assert ok is False
        assert error is not None and "doesn't look like a Gainsight domain" in error
