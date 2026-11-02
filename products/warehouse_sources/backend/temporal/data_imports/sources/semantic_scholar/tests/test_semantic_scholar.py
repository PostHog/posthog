from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.semanticscholar import (
    SemanticScholarSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semantic_scholar.semantic_scholar import (
    SemanticScholarResumeConfig,
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


def driver() -> SourceDriver:
    return SourceDriver(SemanticScholarSource(), CONFIG)


def page(json: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=json)


@pytest.mark.parametrize("incremental", [False, True])
@pytest.mark.parametrize("resume_token", [None, "saved-token"])
def test_bulk_pagination_auth_and_full_refresh(incremental: bool, resume_token: str | None) -> None:
    result = driver().run(
        "papers",
        [
            page({"total": 2, "token": "next-token", "data": [{"paperId": "a"}]}),
            page({"total": 2, "data": [{"paperId": "b"}]}),
        ],
        resume_state=SemanticScholarResumeConfig(paginator_state={"cursor": resume_token}) if resume_token else None,
        should_use_incremental_field=incremental,
        db_incremental_field_last_value="2025-01-01",
    )
    assert result.items == [[{"paperId": "a"}], [{"paperId": "b"}]]
    params = [parse_qs(urlsplit(request.url).query) for request in result.requests]
    assert [param.get("token") for param in params] == [[resume_token] if resume_token else None, ["next-token"]]
    for request, param in zip(result.requests, params):
        assert request.headers["x-api-key"] == "test-api-key"
        assert "test-api-key" not in request.url
        assert param["query"] == [CONFIG.query]
        assert param["sort"] == ["paperId:asc"]
        assert "publicationDateOrYear" not in param
        assert "limit" not in param
        assert "citationCount" in param["fields"][0]
    assert result.saved_states == [SemanticScholarResumeConfig(paginator_state={"cursor": "next-token"})]


@pytest.mark.parametrize(("endpoint", "related_field"), [("citations", "citingPaper"), ("references", "citedPaper")])
def test_edges_paginate_each_parent_and_keep_distinct_keys(endpoint: str, related_field: str) -> None:
    result = driver().run(
        endpoint,
        [
            page({"data": [{"paperId": "a"}, {"paperId": "b"}]}),
            page({"next": 1, "data": [{related_field: {"paperId": "shared"}}]}),
            page({"data": [{related_field: None}, {related_field: {"paperId": None}}]}),
            page({"data": [{related_field: {"paperId": "shared"}}]}),
        ],
    )
    rows = result.rows
    assert [(row["paper_id"], row["related_paper_id"]) for row in rows] == [("a", "shared"), ("b", "shared")]
    assert all("_papers_paperId" not in row for row in rows)
    params = [parse_qs(urlsplit(request.url).query) for request in result.requests]
    assert [param.get("offset") for param in params] == [None, None, ["1"], None]
    assert params[0]["fields"] == ["paperId"]
    for param in params[1:]:
        assert param["limit"] == ["1000"]
        assert "paper_id" not in param
        assert "query" not in param
    assert result.saved_states[-1].paginator_state["completed"] == [
        f"paper/a/{endpoint}",
        f"paper/b/{endpoint}",
    ]


def test_bulk_limit_fails_before_yielding_partial_results() -> None:
    result = driver().run("papers", [page({"total": 10_000_001, "data": [{"paperId": "a"}]})])
    assert isinstance(result.raised, ValueError)
    assert LIMIT_ERROR in str(result.raised)
    assert result.rows == []


@pytest.mark.parametrize(("status", "message"), [(401, AUTH_ERROR), (403, AUTH_ERROR), (400, QUERY_ERROR)])
def test_auth_and_query_errors_are_not_retryable(status: int, message: str) -> None:
    result = driver().run("papers", [page({"message": "rejected"}, status=status)])
    assert isinstance(result.raised, HTTPError)
    mapping = SemanticScholarSource().get_non_retryable_errors()
    assert next(value for key, value in mapping.items() if key in str(result.raised)) == message
    assert len(result.requests) == 1


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (400, QUERY_ERROR),
        (429, "Semantic Scholar is unavailable or has limited requests. Try again later."),
    ],
)
def test_validation_uses_one_call_and_maps_errors(status: int, message: str | None) -> None:
    with scripted_network(always(page({"data": []}, status=status))) as network:
        assert validate_credentials(CONFIG, "v1") == (status == 200, message)
    assert len(network.requests_log) == 1
    assert network.requests_log[0].headers["x-api-key"] == "test-api-key"
    assert parse_qs(urlsplit(network.requests_log[0].url).query)["fields"] == ["paperId"]


@pytest.mark.parametrize(("key", "query"), [("", "graph"), ("key\n", "graph"), ("é", "graph"), ("key", " ")])
def test_invalid_config_does_not_make_requests(key: str, query: str) -> None:
    with scripted_network([]) as network:
        valid, message = validate_credentials(SemanticScholarSourceConfig(api_key=key, query=query), "v1")
    assert not valid
    assert message
    assert len(network.requests_log) == 0
