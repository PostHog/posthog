from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, call

import responses
from responses import matchers

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.telli.telli import TelliResumeConfig, telli_source


@pytest.mark.parametrize(
    "endpoint,path,selector,primary_key,partition_key",
    [
        ("calls", "/v1/list-calls", "calls", "call_id", "triggered_at_iso"),
        ("contacts", "/v2/contacts", "data", "id", "createdAt"),
        ("agents", "/v2/agents", "data", "id", "createdAt"),
    ],
)
@pytest.mark.parametrize("resume_cursor", [None, "saved+/=cursor"])
def test_cursor_pages_and_resume(
    endpoint: str, path: str, selector: str, primary_key: str, partition_key: str, resume_cursor: str | None
) -> None:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_cursor is not None
    manager.load_state.return_value = TelliResumeConfig(cursor=resume_cursor)
    rows: list[dict[str, Any]] = [
        {primary_key: "record-1", partition_key: "2026-01-02T00:00:00Z", "properties": [{"key": "tier", "value": 2}]},
        {primary_key: "record-2", partition_key: "2025-12-01T00:00:00Z", "transcript": "Synthetic test conversation."},
    ]
    first_params = {"limit": "100", **({"cursor": resume_cursor} if resume_cursor else {})}
    with responses.RequestsMock() as http:
        for row, cursor, params in [
            (rows[0], "next+/=cursor", first_params),
            (rows[1], None, {"limit": "100", "cursor": "next+/=cursor"}),
        ]:
            pagination = (
                {"next_cursor": cursor}
                if endpoint == "calls"
                else {"pageInfo": {"nextCursor": cursor, "hasNextPage": cursor is not None}}
            )
            http.get(
                f"https://api.telli.com{path}",
                json={selector: [row], **pagination},
                match=[matchers.query_param_matcher(params)],
            )
        response = telli_source("test-telli-key", endpoint, 1, "test-job", manager)
        iterator = iter(cast(Iterable[list[dict[str, Any]]], response.items()))
        assert next(iterator) == [rows[0]]
        manager.save_state.assert_not_called()
        assert next(iterator) == [rows[1]]
        manager.save_state.assert_called_once_with(TelliResumeConfig(cursor="next+/=cursor"))
        assert list(iterator) == []
        assert manager.save_state.call_args_list == [
            call(TelliResumeConfig(cursor="next+/=cursor")),
            call(TelliResumeConfig(completed=True)),
        ]
        assert len(http.calls) == 2
        assert all(request.request.headers["Authorization"] == "Bearer test-telli-key" for request in http.calls)
        assert response.primary_keys == [primary_key]
        assert all(row[primary_key] for row in rows)
        assert response.partition_keys == [partition_key]


@pytest.mark.parametrize("body", [{"calls": [], "next_cursor": None}, {"unexpected": []}])
def test_empty_calls_and_missing_envelope(body: dict[str, Any]) -> None:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    with responses.RequestsMock() as http:
        http.get("https://api.telli.com/v1/list-calls", json=body)
        response = telli_source("test-telli-key", "calls", 1, "test-job", manager)
        if "calls" in body:
            assert list(cast(Iterable[object], response.items())) == []
            manager.save_state.assert_called_once_with(TelliResumeConfig(completed=True))
        else:
            with pytest.raises(ValueError, match="matched nothing"):
                list(cast(Iterable[object], response.items()))
            manager.save_state.assert_not_called()


def test_completed_resume_does_not_restart_listing() -> None:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = True
    manager.load_state.return_value = TelliResumeConfig(completed=True)
    with responses.RequestsMock() as http:
        response = telli_source("test-telli-key", "calls", 1, "test-job", manager)
        assert list(cast(Iterable[object], response.items())) == []
        assert not http.calls


@pytest.mark.parametrize(
    "endpoint,path,body",
    [
        ("calls", "/v1/list-calls", {"calls": [{"call_id": "call-1"}], "next_cursor": "stuck"}),
        (
            "contacts",
            "/v2/contacts",
            {"data": [{"id": "contact-1"}], "pageInfo": {"nextCursor": "stuck"}},
        ),
    ],
)
def test_repeated_cursor_raises_without_clearing_checkpoint(endpoint: str, path: str, body: dict[str, Any]) -> None:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    with responses.RequestsMock() as http:
        http.get(f"https://api.telli.com{path}", json=body)
        http.get(f"https://api.telli.com{path}", json=body)
        response = telli_source("test-telli-key", endpoint, 1, "test-job", manager)
        with pytest.raises(ValueError, match="not advancing"):
            list(cast(Iterable[object], response.items()))

    manager.save_state.assert_called_once_with(TelliResumeConfig(cursor="stuck"))
