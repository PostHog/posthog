import base64
from datetime import datetime

import pytest
from time_machine import travel

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.clip.clip import (
    ClipResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clip.source import ClipSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clip import ClipSourceConfig

BASE = "https://api-gw.payclip.com"
AUTH = "Basic " + base64.b64encode(b"test-key:test-secret").decode()
DEPOSIT_ID = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def config() -> ClipSourceConfig:
    return ClipSourceConfig(api_key="test-key", secret_key="test-secret", start_date="2026-06-01")


def driver(config: ClipSourceConfig) -> SourceDriver:
    return SourceDriver(ClipSource(), config)


@travel("2026-07-03T12:00:00Z", tick=False)
@pytest.mark.parametrize(
    "incremental,watermark,expected",
    [
        (True, "2026-07-02T00:00:00Z", "2026-07-02T00:00:00+00:00"),
        (True, datetime(2026, 7, 2), "2026-07-02T00:00:00+00:00"),
        (True, None, "2026-06-01T00:00:00+00:00"),
        (False, "2026-07-02T00:00:00Z", "2026-06-01T00:00:00+00:00"),
    ],
)
def test_incremental_filter_and_full_refresh(
    config: ClipSourceConfig,
    incremental: bool,
    watermark: str | datetime | None,
    expected: str,
) -> None:
    result = driver(config).run(
        "transactions",
        always(ScriptedResponse(json={"items": [], "meta": {}})),
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert result.items == []
    assert result.params("from")[-1] == expected
    if len(result.requests) > 1:
        assert result.saved_states


@travel("2026-07-03T12:00:00Z", tick=False)
@pytest.mark.parametrize(
    "status,message",
    [
        (200, None),
    ],
)
def test_credential_probe_and_error_mapping(config: ClipSourceConfig, status: int, message: str | None) -> None:
    with scripted_network([ScriptedResponse(status=status, json={"message": "Unauthorized"})]) as network:
        assert validate_credentials(config) == (status == 200, message)

    assert len(network.requests_log) == 1
    assert network.requests_log[0].headers["authorization"] == AUTH
    assert network.requests_log[0].param("limit") == "1"
    if message:
        assert ClipSource().get_non_retryable_errors()[f"{status} Client Error"] == message


@travel("2026-07-03T12:00:00Z", tick=False)
@pytest.mark.parametrize("status", [429, 500])
def test_probe_does_not_report_transient_errors_as_bad_credentials(config: ClipSourceConfig, status: int) -> None:
    with scripted_network(always(ScriptedResponse(status=status))):
        with pytest.raises(requests.HTTPError):
            validate_credentials(config)


@travel("2026-07-03T12:00:00Z", tick=False)
@pytest.mark.parametrize("href", ["https://example.com/steal", "/settlements/report-not-uuid", "/other/path"])
def test_invalid_parent_link_is_rejected(config: ClipSourceConfig, href: str) -> None:
    result = driver(config).run(
        "settlement_payments",
        [
            ScriptedResponse(
                json={"settlements": [{"settlement_report_id": "report-1", "links": {"self": {"href": href}}}]}
            )
        ],
    )

    assert isinstance(result.raised, ValueError)
    assert "invalid deposit link" in str(result.raised)
    assert result.paths == ["/settlements"]


@travel("2026-07-04T12:00:00Z", tick=False)
def test_settlement_resume_skips_completed_parents_and_resumes_child_page(config: ClipSourceConfig) -> None:
    completed_id = "00000000-0000-4000-8000-000000000002"
    resume_state = ClipResumeConfig(
        start="2026-06-01T00:00:00+00:00",
        end="2026-07-03T12:00:00+00:00",
        paginator_state={
            "completed": [f"settlements/{completed_id}"],
            "current": f"settlements/{DEPOSIT_ID}",
            "child_state": {"next_url": f"{BASE}/settlements/{DEPOSIT_ID}?page=resume"},
        },
    )
    result = driver(config).run(
        "settlement_payments",
        [
            ScriptedResponse(
                json={
                    "settlements": [
                        {
                            "settlement_report_id": "report-done",
                            "links": {"self": {"href": f"/settlements/{completed_id}"}},
                        },
                        {
                            "settlement_report_id": "report-1",
                            "links": {"self": {"href": f"/settlements/{DEPOSIT_ID}"}},
                        },
                    ]
                }
            ),
            ScriptedResponse(json={"settlement": {"details": [{"payments": [{"receipt_no": "b"}]}]}, "links": {}}),
        ],
        resume_state=resume_state,
    )

    assert result.raised is None
    assert result.items == [[{"receipt_no": "b", "settlement_report_id": "report-1"}]]
    assert result.paths == ["/settlements", f"/settlements/{DEPOSIT_ID}"]
    assert result.requests[0].param("to") == "2026-07-03"
    assert result.queries[1] == {"page": ("resume",)}
    assert set(result.saved_states[-1].paginator_state["completed"]) == {
        f"settlements/{completed_id}",
        f"settlements/{DEPOSIT_ID}",
    }


@travel("2026-07-03T12:00:00Z", tick=False)
@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_errors_are_terminal(config: ClipSourceConfig, status: int) -> None:
    result = driver(config).run("transactions", [ScriptedResponse(status=status)])

    assert isinstance(result.raised, requests.HTTPError)
    assert result.paths == ["/payments"]
    assert any(pattern in str(result.raised) for pattern in ClipSource().get_non_retryable_errors())


@travel("2026-07-03T12:00:00Z", tick=False)
def test_repeated_cursor_fails_instead_of_looping(config: ClipSourceConfig) -> None:
    page = ScriptedResponse(json={"items": [{"receipt_no": "a"}], "meta": {"pagination_token": "same"}})
    result = driver(config).run("transactions", [page, page])

    assert isinstance(result.raised, ValueError)
    assert "not advancing" in str(result.raised)
    assert result.paths == ["/payments", "/payments"]
