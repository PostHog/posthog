import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sanity import SanitySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sanity.sanity import SanityResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sanity.source import SanitySource


def driver() -> SourceDriver:
    return SourceDriver(
        SanitySource(),
        SanitySourceConfig(project_id="abc12345", dataset="production", api_token="test-sanity-token"),
    )


@pytest.mark.parametrize("incremental", [False, True])
def test_keyset_pagination_preserves_documents_with_equal_timestamps(incremental: bool) -> None:
    timestamp = "2026-01-01T00:00:00.000Z"
    first = [{"_id": f"article-{i:03}", "_updatedAt": timestamp} for i in range(100)]
    second = [{"_id": f"article-{i:03}", "_updatedAt": timestamp} for i in range(100, 200)]
    result = driver().run(
        "article",
        [
            ScriptedResponse(json={"result": first}),
            ScriptedResponse(json={"result": second}),
            ScriptedResponse(json={"result": []}),
        ],
        should_use_incremental_field=incremental,
        incremental_field="_updatedAt" if incremental else None,
        db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert result.raised is None
    assert result.rows == first + second
    assert result.params("$type") == ['"article"'] * 3
    assert result.params("$lastId") == [None, '"article-099"', '"article-199"']
    queries = result.params("query")
    assert all(query and "[0...100]" in query for query in queries)
    if incremental:
        assert result.params("$since") == [json.dumps(timestamp)] * 3
        assert result.params("$lastUpdatedAt") == [None, json.dumps(timestamp), json.dumps(timestamp)]
        assert queries[1] and "_updatedAt == $lastUpdatedAt && _id > $lastId" in queries[1]
        assert all(query and "order(_updatedAt asc, _id asc)" in query for query in queries)
    else:
        assert result.params("$since") == [None] * 3
        assert queries[1] and "_id > $lastId" in queries[1]
        assert all(query and "order(_id asc)" in query for query in queries)
    expected = [
        SanityResumeConfig(last_id="article-099", last_updated_at=timestamp if incremental else None),
        SanityResumeConfig(last_id="article-199", last_updated_at=timestamp if incremental else None),
    ]
    assert result.saved_states == expected
    assert result.committed_states == expected


@pytest.mark.parametrize("incremental", [False, True])
def test_resume_starts_after_the_committed_cursor_and_keeps_raw_fields(incremental: bool) -> None:
    timestamp = "2026-01-01T00:00:00.000Z"
    row = {
        "_id": "drafts.article-b",
        "_type": "article",
        "_createdAt": timestamp,
        "_updatedAt": timestamp,
        "author": {"_type": "reference", "_ref": "author-a"},
        "body": [{"_type": "block", "children": [{"text": "Example content"}]}],
        "optional": None,
    }
    result = driver().run(
        "article",
        [ScriptedResponse(json={"result": [row]})],
        resume_state=SanityResumeConfig(last_id="drafts.article-a", last_updated_at=timestamp if incremental else None),
        should_use_incremental_field=incremental,
        incremental_field="_updatedAt" if incremental else None,
    )

    assert result.raised is None
    assert result.rows == [row]
    assert result.params("$lastId") == ['"drafts.article-a"']
    assert result.params("perspective") == ["raw"]
    assert result.requests[0].headers["authorization"] == "Bearer test-sanity-token"
    assert result.response is not None
    assert result.response.name == "article"


@pytest.mark.parametrize(
    "watermark",
    [
        None,
        "2026-01-01 02:00:00+02:00",
        datetime(2026, 1, 1),
        datetime(2026, 1, 1, 2, tzinfo=timezone(timedelta(hours=2))),
    ],
)
def test_incremental_watermark_is_inclusive_and_normalized_to_utc(watermark: object) -> None:
    document_type = 'article" || true || _type == "other'
    result = driver().run(
        document_type,
        [ScriptedResponse(json={"result": []})],
        incremental_field="_updatedAt",
        db_incremental_field_last_value=watermark,
        api_version="2025-02-19",
    )

    assert result.raised is None
    request = result.requests[0]
    assert request.path == "/v2025-02-19/data/query/production"
    assert json.loads(request.param("$type") or "null") == document_type
    query = request.param("query")
    assert query and document_type not in query
    if watermark is None:
        assert request.param("$since") is None
        assert "$since" not in query
    else:
        assert request.param("$since") == '"2026-01-01T00:00:00.000Z"'
        assert "_updatedAt >= $since" in query


def test_a_failed_next_request_keeps_the_previous_batch_checkpoint() -> None:
    rows = [{"_id": f"article-{i:03}"} for i in range(100)]
    result = driver().run(
        "article",
        [ScriptedResponse(json={"result": rows}), ScriptedResponse(status=403, json={"error": "Forbidden"})],
    )

    assert isinstance(result.raised, HTTPError)
    assert result.rows == rows
    assert result.committed_states == [SanityResumeConfig(last_id="article-099")]


@pytest.mark.parametrize("body", [{}, {"result": None}, {"result": [None]}, {"result": [{}]}])
def test_malformed_query_results_fail_without_saving_a_cursor(body: dict[str, object]) -> None:
    result = driver().run("article", [ScriptedResponse(json=body)])

    assert isinstance(result.raised, ValueError)
    assert result.rows == []
    assert result.saved_states == []


@pytest.mark.parametrize(
    ("state", "incremental_field", "expected"),
    [
        (SanityResumeConfig(last_id="article-a"), "_updatedAt", "resume cursor has no update timestamp"),
        (None, "title", "requires the _updatedAt field"),
    ],
)
def test_invalid_incremental_settings_fail_before_fetching(
    state: SanityResumeConfig | None, incremental_field: str, expected: str
) -> None:
    result = driver().run("article", [], resume_state=state, incremental_field=incremental_field)

    assert isinstance(result.raised, ValueError)
    assert expected in str(result.raised)
    assert result.requests == []


def test_a_repeated_page_fails_instead_of_repeating_the_import() -> None:
    result = driver().run(
        "article",
        [ScriptedResponse(json={"result": [{"_id": "article-a"}]})],
        resume_state=SanityResumeConfig(last_id="article-a"),
    )

    assert isinstance(result.raised, ValueError)
    assert "did not advance" in str(result.raised)
    assert result.rows == []
