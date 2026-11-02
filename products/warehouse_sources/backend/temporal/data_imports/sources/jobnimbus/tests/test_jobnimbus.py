from typing import Any

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jobnimbus import (
    JobNimbusSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.jobnimbus import (
    PAGE_SIZE,
    JobNimbusResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.source import JobNimbusSource


def _driver() -> SourceDriver:
    return SourceDriver(JobNimbusSource(), JobNimbusSourceConfig(api_key="jn-key"))


def _response(results: list[dict[str, Any]], count: int) -> ScriptedResponse:
    return ScriptedResponse(json={"count": count, "results": results})


class TestPagination:
    def test_paginates_and_progresses_offset(self) -> None:
        full = [{"jnid": str(i)} for i in range(PAGE_SIZE)]
        result = _driver().run(
            "contacts", [_response(full, PAGE_SIZE + 1), _response([{"jnid": "last"}], PAGE_SIZE + 1)]
        )

        assert result.raised is None
        assert [row["jnid"] for row in result.rows] == [*(str(i) for i in range(PAGE_SIZE)), "last"]
        # size/from map onto the offset paginator's limit/offset params.
        assert result.params("from") == ["0", str(PAGE_SIZE)]
        assert result.params("size") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        # Checkpoint saved once after the first full page (points at the next page); short page ends it.
        assert result.saved_states == [JobNimbusResumeConfig(offset=PAGE_SIZE)]

    def test_resumes_from_saved_offset(self) -> None:
        # Offset 0 must never be fetched on resume.
        result = _driver().run(
            "contacts",
            [_response([{"jnid": "x"}], PAGE_SIZE + 1)],
            resume_state=JobNimbusResumeConfig(offset=PAGE_SIZE),
        )

        assert result.raised is None
        assert result.params("from") == [str(PAGE_SIZE)]

    @parameterized.expand(
        [
            ("users", {"users": [{"id": "u1"}, {"id": "u2"}], "date_updated": 1519413931}, "id", ["u1", "u2"], {}),
            (
                "workflows",
                {"workflows": [{"id": 1, "status": [{"id": 2}]}], "sources": [{"JobSourceId": 9}]},
                "id",
                [1],
                {},
            ),
            (
                "lead_sources",
                {"workflows": [{"id": 1, "status": [{"id": 2}]}], "sources": [{"JobSourceId": 9}]},
                "JobSourceId",
                [9],
                {},
            ),
            (
                "groups",
                [{"name": "Sales", "managers": ["u1"], "members": ["u2"]}, {"name": "Crew A", "members": []}],
                "name",
                ["Sales", "Crew A"],
                {"field": "groups"},
            ),
            ("units_of_measure", ["SQ", "Items", "LF"], "uom", ["SQ", "Items", "LF"], {}),
        ]
    )
    def test_account_lookups_are_fetched_in_one_unpaginated_request(
        self,
        endpoint: str,
        body: Any,
        key: str,
        expected: list[Any],
        expected_params: dict[str, Any],
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert [row[key] for row in result.rows] == expected
        assert len(result.requests) == 1
        assert result.queries[0] == {name: (str(value),) for name, value in expected_params.items()}
        assert result.saved_states == []


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int) -> None:
        result = _driver().run("contacts", [ScriptedResponse(status=status), _response([{"jnid": "ok"}], 1)])

        assert result.raised is None
        assert [row["jnid"] for row in result.rows] == ["ok"]
        # The first (retryable) response is reissued, so the successful page needs a second send.
        assert len(result.requests) == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_error_status_raises(self, _name: str, status: int) -> None:
        result = _driver().run("contacts", [ScriptedResponse(status=status)])

        assert isinstance(result.raised, HTTPError)

    @parameterized.expand(
        [
            ("missing_results_key", "contacts", {"count": 0}, "matched nothing"),
            ("bare_list_body", "contacts", [{"jnid": "1"}], "matched nothing"),
            ("groups_settings_object", "groups", {"workflows": [], "sources": []}, "Required a list response body"),
            ("uoms_object", "units_of_measure", {"uoms": ["SQ"]}, "Required a list response body"),
        ]
    )
    def test_shape_change_fails_loud(self, _name: str, endpoint: str, body: Any, error: str) -> None:
        # A 200 body without the expected list means the response shape changed — fail loud instead of
        # silently syncing 0 rows or wrapping a stray object as a row.
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert isinstance(result.raised, ValueError)
        assert error in str(result.raised)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("jn-key") == (expected_valid, expected_message)

        assert network.requests_log
        assert network.requests_log[0].path == "/api1/contacts"
        assert network.requests_log[0].param("size") == "1"
        assert network.requests_log[0].param("from") == "0"
        assert network.requests_log[0].headers["authorization"] == "Bearer jn-key"


class TestSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        if endpoint in ("groups", "units_of_measure"):
            body: Any = []
        elif endpoint == "users":
            body = {"users": []}
        elif endpoint == "workflows":
            body = {"workflows": []}
        elif endpoint == "lead_sources":
            body = {"sources": []}
        else:
            body = {"count": 0, "results": []}

        result = _driver().run(endpoint, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert result.response.partition_mode is None
