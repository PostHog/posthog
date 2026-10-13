from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.culture_amp import (
    CultureAmpResumeConfig,
    _format_timestamp,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.settings import (
    CULTURE_AMP_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.source import CultureAmpSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cultureamp import (
    CultureAmpSourceConfig,
)

DEMOGRAPHICS_PATH = "employees/{employee_id}/demographics"


def _page(rows: list[dict[str, Any]], after_key: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"data": rows}
    if after_key:
        body["pagination"] = {"afterKey": after_key, "nextPath": f"/v1/x?cursor={after_key}"}
    return body


def _token_response() -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": "tok-1", "expires_in": 3599, "token_type": "Bearer"})


def _driver() -> SourceDriver:
    return SourceDriver(
        CultureAmpSource(), CultureAmpSourceConfig(client_id="cid", client_secret="sec", account_id="entity-1")
    )


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_formats(self, value, expected):
        assert _format_timestamp(value) == expected


class TestValidateCredentials:
    def test_invalid_on_exception(self):
        # A failed token mint (bad credentials) raises out of the auth callable during the probe.
        def fail_token(_request: RecordedRequest) -> ScriptedResponse:
            raise Exception("boom")

        with scripted_network(fail_token) as network:
            assert validate_credentials("cid", "bad", "entity-1") is False

        assert [request.path for request in network.requests_log] == ["/v1/oauth2/token"]


class TestCursorEndpoints:
    def test_follow_after_key_until_absent(self):
        result = _driver().run(
            "employees",
            [
                _token_response(),
                ScriptedResponse(json=_page([{"id": "e1"}], after_key="k1")),
                ScriptedResponse(json=_page([{"id": "e2"}])),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["e1", "e2"]
        assert result.params("cursor")[1:] == [None, "k1"]
        # State saved only while a next page remains, after the batch is yielded.
        assert [state.cursor for state in result.saved_states] == ["k1"]

    def test_incremental_passes_after_date(self):
        result = _driver().run(
            "performance_cycles",
            [_token_response(), ScriptedResponse(json=_page([]))],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[1].param("after_date") == "2024-01-02T03:04:05Z"

    def test_resumes_from_saved_cursor(self):
        result = _driver().run(
            "manager_reviews",
            [_token_response(), ScriptedResponse(json=_page([{"managerReviewId": "r9"}]))],
            resume_state=CultureAmpResumeConfig(cursor="k9"),
        )

        assert result.raised is None
        assert result.requests[1].param("cursor") == "k9"

    def test_4xx_raises_immediately(self):
        result = _driver().run("employees", [_token_response(), ScriptedResponse(status=400, json={})])

        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/v1/oauth2/token", "/v1/employees"]


class TestEmployeeDemographicsFanOut:
    def test_fans_out_per_employee_and_injects_employee_id(self):
        result = _driver().run(
            "employee_demographics",
            route(
                {
                    "/oauth2/token": [_token_response()],
                    "/employees": [ScriptedResponse(json=_page([{"id": "e1"}, {"id": "e2"}]))],
                    "/employees/e1/demographics": [
                        ScriptedResponse(json=_page([{"name": "department", "value": "eng"}]))
                    ],
                    "/employees/e2/demographics": [
                        ScriptedResponse(json=_page([{"name": "department", "value": "sales"}]))
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [(row["_employee_id"], row["value"]) for row in result.rows] == [("e1", "eng"), ("e2", "sales")]
        # The framework's include_from_parent key is renamed away — rows keep their old shape.
        assert all("_employees_id" not in row for row in result.rows)
        assert result.urls[1:] == [
            "https://api.cultureamp.com/v1/employees",
            "https://api.cultureamp.com/v1/employees/e1/demographics",
            "https://api.cultureamp.com/v1/employees/e2/demographics",
        ]

    def test_resumes_from_saved_fanout_state(self):
        result = _driver().run(
            "employee_demographics",
            route(
                {
                    "/oauth2/token": [_token_response()],
                    "/employees": [ScriptedResponse(json=_page([{"id": "e1"}, {"id": "e2"}]))],
                    "/employees/e2/demographics": [
                        ScriptedResponse(json=_page([{"name": "department", "value": "sales"}]))
                    ],
                }
            ),
            resume_state=CultureAmpResumeConfig(
                fanout_state={"completed": [DEMOGRAPHICS_PATH.format(employee_id="e1")]}
            ),
        )

        assert result.raised is None
        assert [row["_employee_id"] for row in result.rows] == ["e2"]
        assert result.paths[1:] == ["/v1/employees", "/v1/employees/e2/demographics"]

    def test_resumes_from_beginning_when_saved_employee_removed(self):
        # The employee whose id was saved (e9) is gone from the refetched list, so no one is
        # skipped and the sync processes everyone rather than dropping rows.
        result = _driver().run(
            "employee_demographics",
            route(
                {
                    "/oauth2/token": [_token_response()],
                    "/employees": [ScriptedResponse(json=_page([{"id": "e1"}, {"id": "e2"}]))],
                    "/employees/e1/demographics": [
                        ScriptedResponse(json=_page([{"name": "department", "value": "eng"}]))
                    ],
                    "/employees/e2/demographics": [
                        ScriptedResponse(json=_page([{"name": "department", "value": "sales"}]))
                    ],
                }
            ),
            resume_state=CultureAmpResumeConfig(last_processed_employee_id="e9"),
        )

        assert result.raised is None
        assert [row["_employee_id"] for row in result.rows] == ["e1", "e2"]


class TestCultureAmpSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = CULTURE_AMP_ENDPOINTS[endpoint]
        path = "/employees" if config.per_employee else config.path
        result = _driver().run(
            endpoint,
            route({"/oauth2/token": [_token_response()], path: [ScriptedResponse(json=_page([]))]}),
        )

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Incremental streams defer the watermark (ordering undocumented).
        expected_sort = "desc" if config.incremental_fields else "asc"
        assert response.sort_mode == expected_sort
