from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.survicate import (
    SurvicateSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.survicate.source import SurvicateSource
from products.warehouse_sources.backend.temporal.data_imports.sources.survicate.survicate import SurvicateResumeConfig

ORIGIN = "https://data-api.survicate.com"
BASE = ORIGIN + "/v2"
WATERMARK = "2025-04-01T00:00:00.000000Z"


def page(rows: list[dict[str, Any]], next_url: str | None = None, has_more: bool | None = None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "data": rows,
            "pagination_data": {"has_more": bool(next_url) if has_more is None else has_more, "next_url": next_url},
        }
    )


def answer(table: Mapping[str, ScriptedResponse]) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer by path and query, or by path alone when the table has no entry for the exact query."""

    def respond(request: RecordedRequest) -> ScriptedResponse:
        target = request.url.removeprefix(ORIGIN)
        if target in table:
            return table[target]
        if request.path in table:
            return table[request.path]
        raise UnexpectedRequest(f"the script has no answer for {request.method} {request.url}")

    return respond


def run(
    endpoint: str,
    script: Callable[[RecordedRequest], ScriptedResponse],
    resume_state: SurvicateResumeConfig | None = None,
    incremental: bool = False,
    watermark: Any = None,
    attributes: str | None = None,
) -> DriveResult:
    driver = SourceDriver(SurvicateSource(), SurvicateSourceConfig(api_key="fake-api-key", attribute_names=attributes))
    return driver.run(
        endpoint,
        script,
        resume_state=resume_state,
        incremental_field="collected_at" if incremental else None,
        db_incremental_field_last_value=watermark,
    )


@pytest.mark.parametrize(
    ("endpoint", "incremental", "watermark", "expected_end"),
    [
        ("responses", True, WATERMARK, WATERMARK),
        ("responses", True, datetime(2025, 4, 1, tzinfo=UTC), WATERMARK),
        ("responses", True, None, None),
        ("responses", False, WATERMARK, None),
        ("questions", False, WATERMARK, None),
    ],
)
def test_child_requests_and_parent_keys(
    endpoint: str, incremental: bool, watermark: Any, expected_end: str | None
) -> None:
    row = {"uuid": "response-a", "collected_at": WATERMARK} if endpoint == "responses" else {"id": 7}
    script = answer(
        {
            "/v2/surveys": page([{"id": "survey-a"}, {"id": "survey-b"}]),
            f"/v2/surveys/survey-a/{endpoint}": page([row]),
            f"/v2/surveys/survey-b/{endpoint}": page([row]),
        }
    )

    result = run(endpoint, script, incremental=incremental, watermark=watermark, attributes=" order_id, store, ,")

    assert result.rows == [{**row, "survey_id": "survey-a"}, {**row, "survey_id": "survey-b"}]
    assert result.response is not None
    primary_keys = result.response.primary_keys
    assert primary_keys is not None
    assert len({tuple(item[key] for key in primary_keys) for item in result.rows}) == 2
    assert result.queries[0] == {"items_per_page": ("100",)}
    for request in result.requests[1:]:
        assert request.param("end") == expected_end
        assert request.param("start") is None
        assert request.param("survey_id") is None
        assert request.query.get("attributes[]") == (("order_id", "store") if endpoint == "responses" else None)
        assert request.headers["authorization"] == "Basic fake-api-key"
    assert result.saved_states[-1].state["completed"] == [
        f"surveys/survey-a/{endpoint}",
        f"surveys/survey-b/{endpoint}",
    ]
    if incremental:
        assert result.response.sort_mode == "desc"


@pytest.mark.parametrize("endpoint", ["questions", "responses"])
@pytest.mark.parametrize("resumed", [False, True])
def test_child_pagination_and_resume(endpoint: str, resumed: bool) -> None:
    params = {"start": "2025-05-01T00:00:00.000000Z", "items_per_page": "100"}
    if endpoint == "responses":
        params["end"] = WATERMARK
    next_url = f"/surveys/survey-b/{endpoint}?{urlencode(params)}"
    first_row = {"id": 7} if endpoint == "questions" else {"uuid": "response-a", "collected_at": WATERMARK}
    last_row = {"id": 8} if endpoint == "questions" else {"uuid": "response-b", "collected_at": WATERMARK}
    table = {
        "/v2/surveys": page([{"id": "survey-a"}], "/surveys?start=older-survey"),
        "/v2/surveys?start=older-survey": page([{"id": "survey-b"}]),
        "/v2" + next_url: page([last_row], next_url, False),
    }
    if not resumed:
        table[f"/v2/surveys/survey-a/{endpoint}"] = page([])
        table[f"/v2/surveys/survey-b/{endpoint}"] = page([first_row], next_url)
    state = {
        "completed": [f"surveys/survey-a/{endpoint}"],
        "current": f"surveys/survey-b/{endpoint}",
        "child_state": {"next_url": BASE + next_url},
    }

    result = run(
        endpoint,
        answer(table),
        resume_state=SurvicateResumeConfig(state=state) if resumed else None,
        incremental=endpoint == "responses",
        watermark=WATERMARK,
    )

    expected = [last_row] if resumed else [first_row, last_row]
    assert result.rows == [{**row, "survey_id": "survey-b"} for row in expected]
    assert len(result.requests) == (3 if resumed else 5)
    assert result.urls[-1] == BASE + next_url
    if not resumed:
        assert any(saved.state == state for saved in result.saved_states)


RESPONDENT_PAGE_TWO = BASE + "/respondents/resp-a/attributes?start=2"


@pytest.mark.parametrize(
    ("resume_state", "expected_rows", "expected_attribute_requests"),
    [
        (
            None,
            [("resp-a", 1), ("resp-a", 2), ("resp-d", 4)],
            ["resp-a", "resp-a", "resp-b", "resp-c", "resp-d"],
        ),
        (
            {"respondent_uuid": "resp-a", "next_url": RESPONDENT_PAGE_TWO},
            [("resp-a", 2), ("resp-d", 4)],
            ["resp-a", "resp-b", "resp-c", "resp-d"],
        ),
        (
            {"respondent_uuid": "resp-b", "next_url": None},
            [("resp-d", 4)],
            ["resp-c", "resp-d"],
        ),
        (
            {"respondent_uuid": "resp-c-deleted", "next_url": None},
            [("resp-d", 4)],
            ["resp-d"],
        ),
    ],
)
def test_respondent_attributes_walk_and_resume(
    resume_state: dict[str, Any] | None,
    expected_rows: list[tuple[str, int]],
    expected_attribute_requests: list[str],
) -> None:
    script = answer(
        {
            "/v2/surveys": page([{"id": "survey-a"}], "/surveys?start=older-survey"),
            "/v2/surveys?start=older-survey": page([{"id": "survey-b"}]),
            "/v2/surveys/survey-a/responses": page(
                [{"uuid": "r1", "respondent": {"uuid": "resp-c"}}, {"uuid": "r2", "respondent": {"uuid": "resp-a"}}],
                "/surveys/survey-a/responses?start=older-response",
            ),
            "/v2/surveys/survey-a/responses?start=older-response": page(
                [{"uuid": "r3", "respondent": None}, {"uuid": "r4"}]
            ),
            "/v2/surveys/survey-b/responses": page(
                [
                    {"uuid": "r5", "respondent": {"uuid": "resp-a"}},
                    {"uuid": "r6", "respondent": {"uuid": "resp-d", "attributes": []}},
                    {"uuid": "r7", "respondent": {"uuid": "resp-b"}},
                ]
            ),
            "/v2/respondents/resp-a/attributes": page(
                [{"id": 1, "name": "plan", "value": "pro"}], "/respondents/resp-a/attributes?start=2"
            ),
            RESPONDENT_PAGE_TWO.removeprefix(ORIGIN): page([{"id": 2, "name": "store", "value": "north"}]),
            "/v2/respondents/resp-b/attributes": ScriptedResponse(status=404, json={"message": "Not found"}),
            "/v2/respondents/resp-c/attributes": page([]),
            "/v2/respondents/resp-d/attributes": page([{"id": 4, "name": "plan", "value": "free"}]),
        }
    )

    result = run(
        "respondent_attributes",
        script,
        resume_state=SurvicateResumeConfig(state=resume_state) if resume_state else None,
    )

    assert result.raised is None
    assert [(row["respondent_uuid"], row["id"]) for row in result.rows] == expected_rows
    attribute_requests = [request for request in result.requests if request.path.startswith("/v2/respondents/")]
    assert [request.path.split("/")[3] for request in attribute_requests] == expected_attribute_requests
    assert all(request.headers["authorization"] == "Basic fake-api-key" for request in result.requests)
    if resume_state is None or resume_state["next_url"] is None or resume_state["respondent_uuid"] != "resp-a":
        assert attribute_requests[0].query == {"items_per_page": ("100",)}
    if resume_state is None:
        assert result.saved_states[0].state == {"respondent_uuid": "resp-a", "next_url": RESPONDENT_PAGE_TWO}
    assert result.saved_states[-1].state == {"respondent_uuid": "resp-d", "next_url": None}
    assert result.completed_state is None


@pytest.mark.parametrize("status", [404, 429, 500])
def test_credential_probe_and_error_mapping(status: int) -> None:
    response = ScriptedResponse(status=status, json=page([]).json if status == 200 else {"message": "Unauthorized"})
    source = SurvicateSource()
    config = SurvicateSourceConfig(api_key="fake-api-key")
    with scripted_network(always(response)) as network:
        if status in (429, 500):
            assert source.validate_credentials(config, 1) == (
                False,
                "Couldn't reach Survicate to check your credentials. Try again in a few minutes.",
            )
        elif status == 404:
            with pytest.raises(HTTPError):
                source.validate_credentials(config, 1)
        else:
            valid, error = source.validate_credentials(config, 1)
            assert valid is (status == 200)
            if status == 200:
                assert error is None
            elif status == 401:
                assert (
                    error == "Survicate rejected your API key. Check the key in Settings > Organization > Access Keys."
                )
            else:
                assert error == "Survicate denied API access. Check that your plan includes the Data Export API."
            assert len(network.requests_log) == 1
    first = network.requests_log[0]
    assert first.headers["authorization"] == "Basic fake-api-key"
    assert first.query == {"items_per_page": ("1",)}


@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_errors_match_non_retryable_patterns(status: int) -> None:
    result = run("surveys", always(ScriptedResponse(status=status, json={"message": "Unauthorized"})))

    assert isinstance(result.raised, HTTPError)
    assert any(pattern in str(result.raised) for pattern in SurvicateSource().get_non_retryable_errors())
    assert len(result.requests) == 1


@pytest.mark.parametrize("next_url", [None, "https://example.com/next", "//example.com/next"])
def test_invalid_pagination_link_fails(next_url: str | None) -> None:
    result = run("surveys", always(page([], next_url, True)))

    assert isinstance(result.raised, ValueError)
    assert "invalid pagination link" in str(result.raised)
    assert len(result.requests) == 1


@pytest.mark.parametrize("endpoint", ["invalid", "responses"])
def test_invalid_sync_input(endpoint: str) -> None:
    result = run(endpoint, answer({}), incremental=True, watermark="invalid-date")

    assert isinstance(result.raised, UnknownResourceError if endpoint == "invalid" else ValueError)
