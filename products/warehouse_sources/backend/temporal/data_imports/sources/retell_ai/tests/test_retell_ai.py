import json
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.retellai import (
    RetellAISourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.retell_ai.retell_ai import RetellAIResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.retell_ai.source import RetellAISource
from products.warehouse_sources.backend.temporal.data_imports.sources.retell_ai.tests.conftest import response


@pytest.mark.parametrize(
    "name,path,method,location,key",
    [
        ("calls", "/v3/list-calls", "POST", "json", "call_id"),
        ("chats", "/v3/list-chats", "POST", "json", "chat_id"),
        ("agents", "/v2/list-agents", "POST", "query", "agent_id"),
        ("phone_numbers", "/v2/list-phone-numbers", "GET", "query", "phone_number"),
    ],
)
def test_cursor_pages_and_terminal_page(
    name: str,
    path: str,
    method: str,
    location: str,
    key: str,
    inputs: SourceInputs,
    http: MagicMock,
    redis_client: MagicMock,
) -> None:
    http.side_effect = [
        response({"items": [{key: "record-one"}], "has_more": True, "pagination_key": "next-page"}),
        response({"items": [{key: "record-two"}], "has_more": False, "pagination_key": "unused-terminal-key"}),
    ]
    source = RetellAISource()
    inputs = replace(inputs, schema_name=name)
    manager = source.get_resumable_source_manager(inputs)
    result = source.source_for_pipeline(RetellAISourceConfig(api_key="fake-key"), manager, inputs)
    iterator = iter(result.items())
    assert next(iterator) == [{key: "record-one"}]
    assert not manager.has_staged_state()
    assert next(iterator) == [{key: "record-two"}]
    assert manager.has_staged_state()
    manager.commit()
    assert manager.load_state() == RetellAIResumeConfig(cursor="next-page")
    with pytest.raises(StopIteration):
        next(iterator)
    manager.commit()
    assert manager.load_state() == RetellAIResumeConfig(completed=True)
    assert result.primary_keys == [key]
    requests = [call.args[1] for call in http.call_args_list]
    assert len(requests) == 2
    assert all(request.method == method and urlsplit(request.url).path == path for request in requests)
    assert all(request.headers["Authorization"] == "Bearer fake-key" for request in requests)
    params = [
        json.loads(request.body) if location == "json" else parse_qs(urlsplit(request.url).query)
        for request in requests
    ]
    assert "pagination_key" not in params[0]
    assert params[1]["pagination_key"] == ("next-page" if location == "json" else ["next-page"])
    if location == "json":
        assert all("pagination_key" not in parse_qs(urlsplit(request.url).query) for request in requests)
    else:
        assert all(request.body is None for request in requests)


@pytest.mark.parametrize("name", ["calls", "chats"])
@pytest.mark.parametrize("incremental", [False, True])
@pytest.mark.parametrize("watermark", [None, datetime(2026, 1, 1, tzinfo=UTC), "2026-01-01T01:00:00+01:00"])
def test_incremental_filters_and_timestamp_units(
    name: str,
    incremental: bool,
    watermark: datetime | str | None,
    inputs: SourceInputs,
    http: MagicMock,
    redis_client: MagicMock,
) -> None:
    http.side_effect = [
        response(
            {
                "items": [{"start_timestamp": 1767225600123, "end_timestamp": None}],
                "has_more": True,
                "pagination_key": "next",
            }
        ),
        response({"items": [{"start_timestamp": 1767225660123}], "has_more": False}),
    ]
    source = RetellAISource()
    inputs = replace(
        inputs, schema_name=name, should_use_incremental_field=incremental, db_incremental_field_last_value=watermark
    )
    result = source.source_for_pipeline(
        RetellAISourceConfig(api_key="fake-key"), source.get_resumable_source_manager(inputs), inputs
    )
    rows = list(result.items())
    assert rows[0][0]["start_timestamp"] == datetime(2026, 1, 1, 0, 0, 0, 123000, tzinfo=UTC)
    assert rows[0][0]["end_timestamp"] is None
    assert result.partition_keys == ["start_timestamp"]
    assert result.partition_mode == "datetime"
    bodies = [json.loads(call.args[1].body) for call in http.call_args_list]
    assert all(body["sort_order"] == "ascending" for body in bodies)
    if incremental and watermark is not None:
        assert all(
            body["filter_criteria"] == {"start_timestamp": {"type": "number", "op": "ge", "value": 1767225600000}}
            for body in bodies
        )
    else:
        assert all("filter_criteria" not in body for body in bodies)


@pytest.mark.parametrize("completed", [False, True])
@pytest.mark.parametrize("name,location", [("calls", "json"), ("agents", "query")])
def test_resume_skips_written_pages(
    completed: bool, name: str, location: str, inputs: SourceInputs, http: MagicMock, redis_client: MagicMock
) -> None:
    source = RetellAISource()
    inputs = replace(inputs, schema_name=name)
    manager = source.get_resumable_source_manager(inputs)
    manager.save_state(RetellAIResumeConfig(cursor="saved-cursor", completed=completed))
    manager.commit()
    http.return_value = response({"items": [{"record": "remaining"}], "has_more": False})
    result = source.source_for_pipeline(RetellAISourceConfig(api_key="fake-key"), manager, inputs)
    assert list(result.items()) == ([] if completed else [[{"record": "remaining"}]])
    if completed:
        http.assert_not_called()
    else:
        request = http.call_args.args[1]
        params = json.loads(request.body) if location == "json" else parse_qs(urlsplit(request.url).query)
        assert params["pagination_key"] == ("saved-cursor" if location == "json" else ["saved-cursor"])


def test_voices_are_an_unpaginated_array(inputs: SourceInputs, http: MagicMock) -> None:
    http.return_value = response([{"voice_id": "voice-example", "provider": "example"}])
    source = RetellAISource()
    inputs = replace(inputs, schema_name="voices")
    result = source.source_for_pipeline(
        RetellAISourceConfig(api_key="fake-key"), source.get_resumable_source_manager(inputs), inputs
    )
    assert list(result.items()) == [[{"voice_id": "voice-example", "provider": "example"}]]
    assert result.supports_resume is False
    assert result.partition_keys is None
    assert http.call_count == 1
    assert urlsplit(http.call_args.args[1].url).path == "/list-voices"


@pytest.mark.parametrize(
    "body",
    [
        {"items": [], "has_more": True},
        {"items": [], "has_more": "true", "pagination_key": "next"},
        {"items": []},
        {"wrong_items": [], "has_more": False},
    ],
)
def test_malformed_responses_fail_instead_of_truncating(
    body: dict[str, object], inputs: SourceInputs, http: MagicMock, redis_client: MagicMock
) -> None:
    http.return_value = response(body)
    source = RetellAISource()
    result = source.source_for_pipeline(
        RetellAISourceConfig(api_key="fake-key"), source.get_resumable_source_manager(inputs), inputs
    )
    with pytest.raises(ValueError):
        list(result.items())
    assert http.call_count == 1


def test_repeated_cursor_fails_instead_of_looping(
    inputs: SourceInputs, http: MagicMock, redis_client: MagicMock
) -> None:
    http.return_value = response(
        {"items": [{"call_id": "call-example"}], "has_more": True, "pagination_key": "same-cursor"}
    )
    source = RetellAISource()
    result = source.source_for_pipeline(
        RetellAISourceConfig(api_key="fake-key"), source.get_resumable_source_manager(inputs), inputs
    )
    with pytest.raises(ValueError, match="repeated cursor"):
        list(result.items())
    assert http.call_count == 2


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_match_terminal_error_policy(
    status: int, inputs: SourceInputs, http: MagicMock, redis_client: MagicMock
) -> None:
    http.return_value = response({"message": "fake-key must not appear in the error"}, status)
    source = RetellAISource()
    result = source.source_for_pipeline(
        RetellAISourceConfig(api_key="fake-key"), source.get_resumable_source_manager(inputs), inputs
    )
    with pytest.raises(HTTPError) as raised:
        list(result.items())
    assert any(pattern in str(raised.value) for pattern in source.get_non_retryable_errors())
    assert "fake-key" not in str(raised.value)
    assert http.call_count == 1


@pytest.mark.parametrize("status", [429, 500])
def test_transient_errors_use_framework_retries(
    status: int, inputs: SourceInputs, http: MagicMock, redis_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    http.side_effect = [response({}, status), response({"items": [{"call_id": "call-recovered"}], "has_more": False})]
    source = RetellAISource()
    result = source.source_for_pipeline(
        RetellAISourceConfig(api_key="fake-key"), source.get_resumable_source_manager(inputs), inputs
    )
    assert list(result.items()) == [[{"call_id": "call-recovered"}]]
    assert http.call_count == 2


def test_invalid_watermark_is_not_silently_ignored(
    inputs: SourceInputs, http: MagicMock, redis_client: MagicMock
) -> None:
    source = RetellAISource()
    inputs = replace(inputs, should_use_incremental_field=True, db_incremental_field_last_value="invalid-date")
    result = source.source_for_pipeline(
        RetellAISourceConfig(api_key="fake-key"), source.get_resumable_source_manager(inputs), inputs
    )
    with pytest.raises(ValueError, match="watermark"):
        list(result.items())
    http.assert_not_called()
