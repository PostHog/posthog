from typing import Any

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kapaai import KapaAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kapa_ai.kapa_ai import (
    KapaResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kapa_ai.source import KapaAISource

PROJECT_ID = "00000000-0000-4000-8000-000000000001"
API_KEY = "test-kapa-key"


def driver() -> SourceDriver:
    return SourceDriver(KapaAISource(), KapaAISourceConfig(api_key=API_KEY, project_id=PROJECT_ID))


@pytest.mark.parametrize(
    "endpoint,body,expected",
    [
        ("integrations", [{"id": "integration-1"}], [{"id": "integration-1"}]),
        ("integrations", [], []),
        (
            "activity",
            {"aggregate_statistics": {"total_query_count": 4}, "statistics_by_integration": []},
            [
                {
                    "aggregate_statistics": {"total_query_count": 4},
                    "statistics_by_integration": [],
                    "project_id": PROJECT_ID,
                }
            ],
        ),
    ],
)
def test_unpaginated_responses_keep_their_shape(endpoint: str, body: object, expected: list[dict[str, Any]]) -> None:
    result = driver().run(endpoint, [ScriptedResponse(json=body)])

    assert result.raised is None
    assert result.items == ([expected] if expected else [])
    assert len(result.requests) == 1
    assert result.requests[0].query == {}
    assert result.response is not None
    assert all(key in row for row in expected for key in result.response.primary_keys or [])


@pytest.mark.parametrize("endpoint,api_path", [("top_questions", "top-questions"), ("coverage_gaps", "coverage-gaps")])
def test_period_fanout_paginates_both_levels_and_resumes_children(endpoint: str, api_path: str) -> None:
    period1 = {"id": "period-1", "start_date": "2025-01-01", "end_date": "2025-02-01", "interval": "monthly"}
    period2 = {**period1, "id": "period-2", "start_date": "2025-02-01"}
    parent_page1 = ScriptedResponse(json={"periods": [period1], "next_cursor": "period-page-2"})
    parent_page2 = ScriptedResponse(json={"periods": [period2], "next_cursor": None})
    result = driver().run(
        endpoint,
        [
            parent_page1,
            ScriptedResponse(
                json={
                    "clusters": [{"id": "cluster-1", "thread_count": 123, "threads": []}],
                    "next_cursor": "cluster-page-2",
                }
            ),
            ScriptedResponse(json={"clusters": [{"id": "cluster-2"}], "next_cursor": None}),
            parent_page2,
            ScriptedResponse(json={"clusters": [{"id": "cluster-1"}], "next_cursor": None}),
        ],
    )

    assert result.raised is None
    assert [(row["period_id"], row["id"]) for row in result.rows] == [
        ("period-1", "cluster-1"),
        ("period-1", "cluster-2"),
        ("period-2", "cluster-1"),
    ]
    assert result.rows[0]["period_start_date"] == "2025-01-01"
    assert result.rows[0]["thread_count"] == 123
    assert result.rows[0]["threads"] == []
    assert result.response is not None
    assert result.response.primary_keys == ["period_id", "id"]
    assert result.response.partition_keys == ["period_start_date"]
    assert result.paths[1] == f"/query/v1/{api_path}/periods/period-1/"
    assert result.requests[2].param("cursor") == "cluster-page-2"
    assert result.requests[3].param("cursor") == "period-page-2"

    resumed = driver().run(
        endpoint,
        [
            parent_page1,
            ScriptedResponse(json={"clusters": [{"id": "cluster-2"}], "next_cursor": None}),
            parent_page2,
            ScriptedResponse(json={"clusters": [], "next_cursor": None}),
        ],
        resume_state=result.saved_states[0],
    )

    assert resumed.raised is None
    assert [row["id"] for row in resumed.rows] == ["cluster-2"]
    assert resumed.requests[1].param("cursor") == "cluster-page-2"


@pytest.mark.parametrize(
    "status,schema,valid,message",
    [
        (404, None, False, "The kapa.ai project was not found. Check your project ID and the key's project access."),
    ],
)
def test_credential_probe_status_mapping(status: int, schema: str | None, valid: bool, message: str | None) -> None:
    with scripted_network([ScriptedResponse(status=status, json={"results": [], "next_cursor": None})]) as network:
        assert validate_credentials(API_KEY, PROJECT_ID, 1, schema) == (valid, message)

    assert len(network.requests_log) == 1
    assert network.requests_log[0].param("page_size") == "1"


@pytest.mark.parametrize(
    "project_id,key,schema,message",
    [
        ("../threads", API_KEY, None, "Enter a valid kapa.ai project ID in UUID format."),
        (PROJECT_ID, "bad\nkey", None, "Enter a valid kapa.ai API key without whitespace or unsupported characters."),
        (PROJECT_ID, "", None, "Enter a valid kapa.ai API key without whitespace or unsupported characters."),
        (PROJECT_ID, API_KEY, "missing", "Unknown kapa.ai table. Refresh the table list and try again."),
    ],
)
def test_invalid_configuration_never_sends_a_request(
    project_id: str, key: str, schema: str | None, message: str
) -> None:
    with scripted_network([]) as network:
        assert validate_credentials(key, project_id, 1, schema) == (False, message)

    assert network.requests_log == []


def test_unexpected_probe_error_is_not_reported_as_bad_credentials() -> None:
    with scripted_network([ScriptedResponse(status=400, json={})]):
        with pytest.raises(HTTPError):
            validate_credentials(API_KEY, PROJECT_ID, 1)


def test_missing_response_collection_fails_instead_of_erasing_the_table() -> None:
    previous_state = KapaResumeConfig(paginator_state=None)
    result = driver().run("threads", [ScriptedResponse(json={"unexpected": []})], resume_state=previous_state)

    assert isinstance(result.raised, ValueError)
    assert "results" in str(result.raised)
    assert result.final_state == previous_state


@pytest.mark.parametrize("next_url", ["https://example.com/collect", "http://api.kapa.ai/query/v1/threads/"])
def test_pagination_cannot_send_the_key_to_another_origin(next_url: str) -> None:
    result = driver().run("end_users", [ScriptedResponse(json={"results": [{"id": "user-1"}], "next": next_url})])

    assert isinstance(result.raised, ValueError)
    assert "Refusing to send request" in str(result.raised)
    assert len(result.requests) == 1
