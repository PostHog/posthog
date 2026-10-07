from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock

import responses
from requests.exceptions import HTTPError, Timeout

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.semanticscholar import (
    SemanticScholarSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.semantic_scholar import (
    SemanticScholarResumeConfig,
    semantic_scholar_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.settings import (
    AUTH_ERROR,
    LIMIT_ERROR,
    QUERY_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.source import (
    SemanticScholarSource,
)

BASE_URL = "https://api.semanticscholar.org/graph/v1"
CONFIG = SemanticScholarSourceConfig(api_key="test-api-key", query='"test paper" | graphs')


def make_inputs(endpoint: str, incremental: bool = False) -> SourceInputs:
    return SourceInputs(
        schema_name=endpoint,
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value="2025-01-01",
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="test-job",
        logger=MagicMock(),
        reset_pipeline=False,
    )


def make_manager(state: dict[str, Any] | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = state is not None
    manager.load_state.return_value = SemanticScholarResumeConfig(paginator_state=state) if state is not None else None
    return manager


def items(response: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], response.items())


@pytest.mark.parametrize("incremental", [False, True])
@pytest.mark.parametrize("resume_token", [None, "saved-token"])
@responses.activate
def test_bulk_pagination_auth_and_full_refresh(incremental: bool, resume_token: str | None) -> None:
    responses.get(f"{BASE_URL}/paper/search/bulk", json={"total": 2, "token": "next-token", "data": [{"paperId": "a"}]})
    responses.get(f"{BASE_URL}/paper/search/bulk", json={"total": 2, "data": [{"paperId": "b"}]})
    manager = make_manager({"cursor": resume_token} if resume_token else None)
    result = SemanticScholarSource().source_for_pipeline(CONFIG, manager, make_inputs("papers", incremental))
    assert list(items(result)) == [[{"paperId": "a"}], [{"paperId": "b"}]]
    requests = [call.request for call in responses.calls]
    params = [parse_qs(urlsplit(request.url).query) for request in requests]
    assert [param.get("token") for param in params] == [[resume_token] if resume_token else None, ["next-token"]]
    for request, param in zip(requests, params):
        assert request.headers["x-api-key"] == "test-api-key"
        assert "test-api-key" not in request.url
        assert param["query"] == [CONFIG.query]
        assert param["sort"] == ["paperId:asc"]
        assert "publicationDateOrYear" not in param
        assert "limit" not in param
        assert "citationCount" in param["fields"][0]
    manager.save_state.assert_called_once_with(SemanticScholarResumeConfig(paginator_state={"cursor": "next-token"}))


@pytest.mark.parametrize(("endpoint", "related_field"), [("citations", "citingPaper"), ("references", "citedPaper")])
@responses.activate
def test_edges_paginate_each_parent_and_keep_distinct_keys(endpoint: str, related_field: str) -> None:
    responses.get(f"{BASE_URL}/paper/search/bulk", json={"data": [{"paperId": "a"}, {"paperId": "b"}]})
    responses.get(f"{BASE_URL}/paper/a/{endpoint}", json={"next": 1, "data": [{related_field: {"paperId": "shared"}}]})
    responses.get(
        f"{BASE_URL}/paper/a/{endpoint}", json={"data": [{related_field: None}, {related_field: {"paperId": None}}]}
    )
    responses.get(f"{BASE_URL}/paper/b/{endpoint}", json={"data": [{related_field: {"paperId": "shared"}}]})
    manager = make_manager()
    result = semantic_scholar_source(CONFIG, make_inputs(endpoint), manager, "v1")
    rows = [row for page in items(result) for row in page]
    assert [(row["paper_id"], row["related_paper_id"]) for row in rows] == [("a", "shared"), ("b", "shared")]
    assert all("_papers_paperId" not in row for row in rows)
    params = [parse_qs(urlsplit(call.request.url).query) for call in responses.calls]
    assert [param.get("offset") for param in params] == [None, None, ["1"], None]
    assert params[0]["fields"] == ["paperId"]
    for param in params[1:]:
        assert param["limit"] == ["1000"]
        assert "paper_id" not in param
        assert "query" not in param
    assert manager.save_state.call_args.args[0].paginator_state["completed"] == [
        f"paper/a/{endpoint}",
        f"paper/b/{endpoint}",
    ]


@pytest.mark.parametrize("endpoint", ["citations", "references"])
@responses.activate
def test_resume_skips_completed_parents_and_restores_child_offset(endpoint: str) -> None:
    related_field = "citingPaper" if endpoint == "citations" else "citedPaper"
    responses.get(f"{BASE_URL}/paper/search/bulk", json={"data": [{"paperId": "a"}, {"paperId": "b"}]})
    responses.get(f"{BASE_URL}/paper/b/{endpoint}", json={"data": [{related_field: {"paperId": "c"}}]})
    manager = make_manager(
        {"completed": [f"paper/a/{endpoint}"], "current": f"paper/b/{endpoint}", "child_state": {"cursor": 1000}}
    )
    result = semantic_scholar_source(CONFIG, make_inputs(endpoint), manager, "v1")
    rows = [row for page in items(result) for row in page]
    assert [(row["paper_id"], row["related_paper_id"]) for row in rows] == [("b", "c")]
    assert len(responses.calls) == 2
    assert parse_qs(urlsplit(responses.calls[1].request.url).query)["offset"] == ["1000"]


@pytest.mark.parametrize("endpoint", ["papers", "citations", "references"])
@responses.activate
def test_empty_search_stops_without_child_requests(endpoint: str) -> None:
    responses.get(f"{BASE_URL}/paper/search/bulk", json={"total": 0, "data": []})
    result = semantic_scholar_source(CONFIG, make_inputs(endpoint), make_manager(), "v1")
    assert list(items(result)) == []
    assert len(responses.calls) == 1


@responses.activate
def test_bulk_limit_fails_before_yielding_partial_results() -> None:
    responses.get(f"{BASE_URL}/paper/search/bulk", json={"total": 10_000_001, "data": [{"paperId": "a"}]})
    result = semantic_scholar_source(CONFIG, make_inputs("papers"), make_manager(), "v1")
    with pytest.raises(ValueError, match=LIMIT_ERROR):
        list(items(result))


@pytest.mark.parametrize(("status", "message"), [(401, AUTH_ERROR), (403, AUTH_ERROR), (400, QUERY_ERROR)])
@responses.activate
def test_auth_and_query_errors_are_not_retryable(status: int, message: str) -> None:
    responses.get(f"{BASE_URL}/paper/search/bulk", json={"message": "rejected"}, status=status)
    result = semantic_scholar_source(CONFIG, make_inputs("papers"), make_manager(), "v1")
    with pytest.raises(HTTPError) as error:
        list(items(result))
    mapping = SemanticScholarSource().get_non_retryable_errors()
    assert next(value for key, value in mapping.items() if key in str(error.value)) == message
    assert len(responses.calls) == 1


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (200, None),
        (401, AUTH_ERROR),
        (403, AUTH_ERROR),
        (400, QUERY_ERROR),
        (429, "Semantic Scholar is unavailable or has limited requests. Try again later."),
        (500, "Semantic Scholar is unavailable or has limited requests. Try again later."),
    ],
)
@responses.activate
def test_validation_uses_one_call_and_maps_errors(status: int, message: str | None) -> None:
    responses.get(f"{BASE_URL}/paper/search/bulk", json={"data": []}, status=status)
    assert validate_credentials(CONFIG, "v1") == (status == 200, message)
    assert len(responses.calls) == 1
    assert responses.calls[0].request.headers["x-api-key"] == "test-api-key"
    assert parse_qs(urlsplit(responses.calls[0].request.url).query)["fields"] == ["paperId"]


@responses.activate
def test_validation_hides_transport_error_details() -> None:
    responses.get(f"{BASE_URL}/paper/search/bulk", body=Timeout("private transport detail"))
    valid, message = validate_credentials(CONFIG, "v1")
    assert not valid
    assert message == "Semantic Scholar is unavailable or has limited requests. Try again later."


@pytest.mark.parametrize(("key", "query"), [("", "graph"), ("key\n", "graph"), ("é", "graph"), ("key", " ")])
@responses.activate
def test_invalid_config_does_not_make_requests(key: str, query: str) -> None:
    valid, message = validate_credentials(SemanticScholarSourceConfig(api_key=key, query=query), "v1")
    assert not valid
    assert message
    assert len(responses.calls) == 0


@responses.activate
def test_rate_limit_retries_same_page() -> None:
    responses.get(
        f"{BASE_URL}/paper/search/bulk", json={"message": "limited"}, status=429, headers={"Retry-After": "0"}
    )
    responses.get(f"{BASE_URL}/paper/search/bulk", json={"data": [{"paperId": "a"}]})
    result = semantic_scholar_source(CONFIG, make_inputs("papers"), make_manager(), "v1")
    assert list(items(result)) == [[{"paperId": "a"}]]
    assert responses.calls[0].request.url == responses.calls[1].request.url
