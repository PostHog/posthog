import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import activate_safe_point
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.scrunch import (
    ScrunchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scrunch.scrunch import (
    ScrunchResumeConfig,
    scrunch_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scrunch.settings import (
    AUTH_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scrunch.source import ScrunchSource


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="brands",
        schema_id="test-schema",
        source_id="test-source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="test-job",
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock()
    result.can_resume.return_value = False
    return result


@pytest.fixture
def transport() -> Iterator[MagicMock]:
    session = Session()
    with (
        patch.object(session, "send") as send,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
            return_value=session,
        ) as tracked,
        patch("products.warehouse_sources.backend.temporal.data_imports.sources.scrunch.scrunch.PAGE_SIZE", 2),
        activate_safe_point(lambda: None, covers_framework_checkpoints=True),
    ):
        yield send
        assert tracked.call_args.kwargs["redact_values"] == ("test-key",)


def page(rows: list[dict[str, Any]], total: int, status: int = 200) -> Response:
    response = Response()
    response.status_code = status
    response.url = "https://api.scrunchai.com/v1/brands"
    response._content = json.dumps({"items": rows, "total": total}).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def params(transport: MagicMock, index: int) -> dict[str, list[str]]:
    return parse_qs(urlsplit(transport.call_args_list[index].args[0].url).query)


def sync_batches(response: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], response.items())


@pytest.mark.parametrize("terminal", [[], [{"id": 3}], [{"id": 3}, {"id": 4}]])
def test_brand_pagination(
    terminal: list[dict[str, Any]], inputs: SourceInputs, manager: MagicMock, transport: MagicMock
) -> None:
    total = 2 + len(terminal) if terminal else 5
    transport.side_effect = [page([{"id": 1}, {"id": 2}], total), page(terminal, total)]
    result = scrunch_source("test-key", inputs, manager)
    iterator = iter(sync_batches(result))
    assert next(iterator) == [{"id": 1}, {"id": 2}]
    assert manager.save_state.call_args.args[0].paginator_state == {"offset": 2}
    remaining = list(iterator)
    assert [row for batch in remaining for row in batch] == terminal
    assert manager.save_state.call_args.args[0].complete is True
    assert transport.call_count == 2
    assert [params(transport, index) for index in range(2)] == [
        {"offset": ["0"], "limit": ["2"]},
        {"offset": ["2"], "limit": ["2"]},
    ]
    for call in transport.call_args_list:
        assert call.args[0].headers["Authorization"] == "Bearer test-key"
        assert urlsplit(call.args[0].url).path == "/v1/brands"


@pytest.mark.parametrize(
    "table,path",
    [
        ("prompts", "/v1/11/prompts"),
        ("competitors", "/v1/brands/11/competitors"),
        ("personas", "/v1/brands/11/personas"),
        ("responses", "/v1/11/responses"),
    ],
)
def test_children_keep_brand_identity_and_reset_offsets(
    table: str, path: str, inputs: SourceInputs, manager: MagicMock, transport: MagicMock
) -> None:
    inputs.schema_name = table
    transport.side_effect = [
        page([{"id": 11}, {"id": 22}], 2),
        page([{"id": 1}, {"id": 2}], 3),
        page([{"id": 3}], 3),
        page([{"id": 1}], 1),
    ]
    result = scrunch_source("test-key", inputs, manager)
    rows = [row for batch in sync_batches(result) for row in batch]
    assert rows == [
        {"id": 1, "brand_id": 11},
        {"id": 2, "brand_id": 11},
        {"id": 3, "brand_id": 11},
        {"id": 1, "brand_id": 22},
    ]
    assert result.primary_keys == ["brand_id", "id"]
    assert [params(transport, index)["offset"] for index in range(4)] == [["0"], ["0"], ["2"], ["0"]]
    assert urlsplit(transport.call_args_list[1].args[0].url).path == path
    assert urlsplit(transport.call_args_list[3].args[0].url).path == path.replace("11", "22")
    for index in range(1, 4):
        assert "brand_id" not in params(transport, index)
        if table == "prompts":
            assert params(transport, index)["status"] == ["all"]
        if table != "responses":
            assert "start_date" not in params(transport, index)
            assert "end_date" not in params(transport, index)


def test_child_requests_reject_off_host_brand_ids(
    inputs: SourceInputs, manager: MagicMock, transport: MagicMock
) -> None:
    inputs.schema_name = "prompts"
    transport.return_value = page([{"id": "https://attacker.example/collect"}], 1)

    with pytest.raises(ValueError, match="disallowed host"):
        list(sync_batches(scrunch_source("test-key", inputs, manager)))

    assert transport.call_count == 1


@pytest.mark.parametrize(
    "incremental,watermark,expected_start",
    [
        (False, "2026-08-01T10:00:00Z", None),
        (True, None, None),
        (True, "2026-08-01T10:00:00Z", "2026-08-01"),
        (True, datetime(2026, 8, 1, 10, tzinfo=UTC), "2026-08-01"),
        (True, "2026-08-01T23:30:00-05:00", "2026-08-02"),
    ],
)
def test_response_date_filters(
    incremental: bool,
    watermark: str | datetime | None,
    expected_start: str | None,
    inputs: SourceInputs,
    manager: MagicMock,
    transport: MagicMock,
) -> None:
    inputs.schema_name = "responses"
    inputs.should_use_incremental_field = incremental
    inputs.db_incremental_field_last_value = watermark
    transport.side_effect = [
        page([{"id": 11}], 1),
        page([{"id": 1}, {"id": 2}], 3),
        page([{"id": 3}], 3),
    ]
    today = datetime.now(UTC).date().isoformat()
    result = scrunch_source("test-key", inputs, manager)
    list(sync_batches(result))
    assert result.sort_mode == "desc"
    assert result.partition_keys == ["created_at"]
    for index in (1, 2):
        query = params(transport, index)
        assert query["end_date"] == [today]
        assert query.get("start_date") == ([expected_start] if expected_start else None)
    assert "start_date" not in params(transport, 0)


@pytest.mark.parametrize("terminal", [False, True])
def test_child_resume_keeps_window_and_skips_completed_brands(
    terminal: bool, inputs: SourceInputs, manager: MagicMock, transport: MagicMock
) -> None:
    inputs.schema_name = "responses"
    manager.can_resume.return_value = True
    manager.load_state.return_value = ScrunchResumeConfig(
        paginator_state={
            "completed": ["11/responses"],
            "current": None if terminal else "22/responses",
            "child_state": None if terminal else {"offset": 2},
        },
        start_date="2026-08-01",
        end_date="2026-08-03",
    )
    transport.side_effect = [page([{"id": 11}, {"id": 22}], 2), page([{"id": 9}], 3 if not terminal else 1)]
    result = scrunch_source("test-key", inputs, manager)
    iterator = iter(sync_batches(result))
    assert next(iterator) == [{"id": 9, "brand_id": 22}]
    assert manager.save_state.call_args.args[0].paginator_state == {
        "completed": ["11/responses", "22/responses"],
        "current": None,
        "child_state": None,
    }
    assert list(iterator) == []
    assert transport.call_count == 2
    assert params(transport, 1) == {
        "offset": ["0" if terminal else "2"],
        "limit": ["2"],
        "start_date": ["2026-08-01"],
        "end_date": ["2026-08-03"],
    }
    assert urlsplit(transport.call_args_list[1].args[0].url).path == "/v1/22/responses"


@pytest.mark.parametrize("complete", [False, True])
def test_brand_resume(inputs: SourceInputs, manager: MagicMock, transport: MagicMock, complete: bool) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = ScrunchResumeConfig(
        paginator_state=None if complete else {"offset": 2},
        start_date=None,
        end_date=None,
        complete=complete,
    )
    transport.return_value = page([{"id": 3}], 3)
    rows = [row for batch in sync_batches(scrunch_source("test-key", inputs, manager)) for row in batch]
    assert rows == ([] if complete else [{"id": 3}])
    assert transport.call_count == (0 if complete else 1)
    if not complete:
        assert params(transport, 0)["offset"] == ["2"]


@pytest.mark.parametrize("has_brands", [False, True])
def test_empty_children_do_not_stop_parent_pagination(
    has_brands: bool, inputs: SourceInputs, manager: MagicMock, transport: MagicMock
) -> None:
    inputs.schema_name = "personas"
    transport.side_effect = (
        [
            page([{"id": 11}, {"id": 22}], 3),
            page([], 0),
            page([], 0),
            page([{"id": 33}], 3),
            page([{"id": 1}], 1),
        ]
        if has_brands
        else [page([], 0)]
    )
    safe_point = MagicMock()
    with activate_safe_point(safe_point, covers_framework_checkpoints=True):
        result = scrunch_source("test-key", inputs, manager)
        assert [row for batch in sync_batches(result) for row in batch] == (
            [{"id": 1, "brand_id": 33}] if has_brands else []
        )
    assert transport.call_count == (5 if has_brands else 1)
    if has_brands:
        assert params(transport, 3)["offset"] == ["2"]
        assert manager.save_state.call_args.args[0].paginator_state["completed"] == [
            "brands/11/personas",
            "brands/22/personas",
            "brands/33/personas",
        ]
        safe_point.assert_called()


@pytest.mark.parametrize(
    "status,message", [(200, None), (401, AUTH_ERROR), (403, PERMISSION_ERROR), (402, PERMISSION_ERROR)]
)
def test_credentials_and_error_mapping(status: int, message: str | None, transport: MagicMock) -> None:
    transport.return_value = page([], 0, status=status)
    source = ScrunchSource()
    assert source.validate_credentials(ScrunchSourceConfig(api_key="test-key"), 1) == (status == 200, message)
    assert transport.call_count == 1
    assert params(transport, 0) == {"limit": ["1"]}
    assert transport.call_args.args[0].headers["Authorization"] == "Bearer test-key"
    if status != 200:
        with pytest.raises(HTTPError) as error:
            transport.return_value.raise_for_status()
        assert any(
            pattern in str(error.value) and value == message
            for pattern, value in source.get_non_retryable_errors().items()
        )


def test_unexpected_validation_failure_propagates(transport: MagicMock) -> None:
    transport.return_value = page([], 0, status=404)
    with pytest.raises(HTTPError):
        ScrunchSource().validate_credentials(ScrunchSourceConfig(api_key="test-key"), 1)


def test_invalid_watermark_fails_before_requests(inputs: SourceInputs, manager: MagicMock) -> None:
    inputs.schema_name = "responses"
    inputs.should_use_incremental_field = True
    inputs.db_incremental_field_last_value = "not-a-date"
    with pytest.raises(ValueError, match="watermark"):
        scrunch_source("test-key", inputs, manager)
