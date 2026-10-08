import base64
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
from typing import Any, cast

import pytest
from time_machine import travel
from unittest.mock import MagicMock

import requests
import requests_mock

from products.warehouse_sources.backend.temporal.data_imports.sources.clip.clip import (
    ClipResumeConfig,
    clip_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clip.settings import AUTH_ERROR, PERMISSION_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.clip.source import ClipSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clip import ClipSourceConfig

BASE = "https://api-gw.payclip.com"
AUTH = "Basic " + base64.b64encode(b"test-key:test-secret").decode()
DEPOSIT_ID = "00000000-0000-4000-8000-000000000001"


def sync_items(response: SourceResponse) -> Iterable[list[dict[str, Any]]]:
    return cast(Iterable[list[dict[str, Any]]], response.items())


@pytest.fixture
def config() -> ClipSourceConfig:
    return ClipSourceConfig(api_key="test-key", secret_key="test-secret", start_date="2026-06-01")


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="transactions",
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field="created_at",
        incremental_field_type=None,
        job_id="job",
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


@travel("2026-07-03T12:00:00Z", tick=False)
@pytest.mark.parametrize(
    "incremental,watermark,expected",
    [
        (True, "2026-07-02T00:00:00Z", "2026-07-02t00:00:00+00:00"),
        (True, datetime(2026, 7, 2), "2026-07-02t00:00:00+00:00"),
        (True, None, "2026-06-01t00:00:00+00:00"),
        (False, "2026-07-02T00:00:00Z", "2026-06-01t00:00:00+00:00"),
    ],
)
def test_incremental_filter_and_full_refresh(
    config: ClipSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    incremental: bool,
    watermark: str | datetime | None,
    expected: str,
) -> None:
    inputs = replace(inputs, should_use_incremental_field=incremental, db_incremental_field_last_value=watermark)
    with requests_mock.Mocker() as http:
        http.get(f"{BASE}/payments", json={"items": [], "meta": {}})
        assert list(sync_items(clip_source(config, inputs, manager))) == []
        assert http.request_history[-1].qs["from"] == [expected]
        if len(http.request_history) > 1:
            manager.safe_point.assert_called()


@travel("2026-07-03T12:00:00Z", tick=False)
@pytest.mark.parametrize("status,message", [(200, None), (401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_credential_probe_and_error_mapping(config: ClipSourceConfig, status: int, message: str | None) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE}/payments", status_code=status, json={"message": "Unauthorized"})
        assert validate_credentials(config) == (status == 200, message)
        assert len(http.request_history) == 1
        assert http.request_history[0].headers["Authorization"] == AUTH
        assert http.request_history[0].qs["limit"] == ["1"]
        if message:
            assert ClipSource().get_non_retryable_errors()[f"{status} Client Error"] == message


@travel("2026-07-03T12:00:00Z", tick=False)
@pytest.mark.parametrize("status", [429, 500])
def test_probe_does_not_report_transient_errors_as_bad_credentials(config: ClipSourceConfig, status: int) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE}/payments", status_code=status)
        with pytest.raises(requests.HTTPError):
            validate_credentials(config)


@travel("2026-07-03T12:00:00Z", tick=False)
@pytest.mark.parametrize("href", ["https://example.com/steal", "/settlements/report-not-uuid", "/other/path"])
def test_invalid_parent_link_is_rejected(
    config: ClipSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    href: str,
) -> None:
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE}/settlements",
            json={
                "settlements": [
                    {"settlement_report_id": "report-1", "links": {"self": {"href": href}}},
                ]
            },
        )
        with pytest.raises(ValueError, match="invalid deposit link"):
            list(sync_items(clip_source(config, replace(inputs, schema_name="settlement_payments"), manager)))
        assert len(http.request_history) == 1


def test_unknown_table(config: ClipSourceConfig, inputs: SourceInputs, manager: MagicMock) -> None:
    with pytest.raises(UnknownResourceError):
        clip_source(config, replace(inputs, schema_name="unknown"), manager)


@travel("2026-07-04T12:00:00Z", tick=False)
def test_settlement_resume_skips_completed_parents_and_resumes_child_page(
    config: ClipSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
) -> None:
    completed_id = "00000000-0000-4000-8000-000000000002"
    manager.can_resume.return_value = True
    manager.load_state.return_value = ClipResumeConfig(
        start="2026-06-01T00:00:00+00:00",
        end="2026-07-03T12:00:00+00:00",
        paginator_state={
            "completed": [f"settlements/{completed_id}"],
            "current": f"settlements/{DEPOSIT_ID}",
            "child_state": {"next_url": f"{BASE}/settlements/{DEPOSIT_ID}?page=resume"},
        },
    )
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE}/settlements",
            json={
                "settlements": [
                    {
                        "settlement_report_id": "report-done",
                        "links": {"self": {"href": f"/settlements/{completed_id}"}},
                    },
                    {"settlement_report_id": "report-1", "links": {"self": {"href": f"/settlements/{DEPOSIT_ID}"}}},
                ]
            },
        )
        http.get(
            f"{BASE}/settlements/{DEPOSIT_ID}?page=resume",
            json={
                "settlement": {"details": [{"payments": [{"receipt_no": "b"}]}]},
                "links": {},
            },
        )
        assert list(sync_items(clip_source(config, replace(inputs, schema_name="settlement_payments"), manager))) == [
            [{"receipt_no": "b", "settlement_report_id": "report-1"}],
        ]
        assert len(http.request_history) == 2
        assert http.request_history[0].qs["to"] == ["2026-07-03"]
        assert http.request_history[1].qs == {"page": ["resume"]}
        assert set(manager.save_state.call_args.args[0].paginator_state["completed"]) == {
            f"settlements/{completed_id}",
            f"settlements/{DEPOSIT_ID}",
        }


@travel("2026-07-03T12:00:00Z", tick=False)
@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_errors_are_terminal(
    config: ClipSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    status: int,
) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE}/payments", status_code=status, reason="Unauthorized" if status == 401 else "Forbidden")
        with pytest.raises(requests.HTTPError) as error:
            list(sync_items(clip_source(config, inputs, manager)))
        assert len(http.request_history) == 1
        assert any(pattern in str(error.value) for pattern in ClipSource().get_non_retryable_errors())


@travel("2026-07-03T12:00:00Z", tick=False)
def test_repeated_cursor_fails_instead_of_looping(
    config: ClipSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE}/payments", json={"items": [{"receipt_no": "a"}], "meta": {"pagination_token": "same"}})
        with pytest.raises(ValueError, match="not advancing"):
            list(sync_items(clip_source(config, inputs, manager)))
        assert len(http.request_history) == 2
