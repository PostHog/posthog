from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
import time_machine
from unittest.mock import MagicMock

import responses
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mercadopago import (
    MercadoPagoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.mercado_pago import (
    MercadoPagoResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mercado_pago.source import MercadoPagoSource

TOKEN = "fake-mercado-pago-token"
NOW = datetime(2026, 6, 15, 12, tzinfo=UTC)


def _driver() -> SourceDriver:
    return SourceDriver(MercadoPagoSource(), MercadoPagoSourceConfig(access_token=TOKEN))


@pytest.fixture
def inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="payments",
        schema_id="schema-test",
        source_id="source-test",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field="date_last_updated",
        incremental_field_type=None,
        job_id="job-test",
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


def test_builds_resumable_source_manager(inputs: SourceInputs) -> None:
    manager = MercadoPagoSource().get_resumable_source_manager(inputs)

    assert manager._inputs is inputs
    assert manager._data_class is MercadoPagoResumeConfig


@pytest.mark.parametrize(
    ("name", "path"),
    [
        ("payments", "/v1/payments/search"),
        ("subscriptions", "/preapproval/search"),
        ("subscription_plans", "/preapproval_plan/search"),
    ],
)
@pytest.mark.parametrize("last_page_size", [0, 1, 20])
@responses.activate
def test_requests_and_pagination(
    inputs: SourceInputs, manager: MagicMock, name: str, path: str, last_page_size: int
) -> None:
    inputs.schema_name = name
    rows = [{"id": str(index)} for index in range(20 + last_page_size)]
    total = len(rows) if last_page_size else 100
    for page in [rows[:20], rows[20:]]:
        responses.get("https://api.mercadopago.com" + path, json={"results": page, "paging": {"total": total}})

    source = MercadoPagoSource().source_for_pipeline(MercadoPagoSourceConfig(access_token=TOKEN), manager, inputs)
    assert [row for page in cast(Iterable[Any], source.items()) for row in page] == rows
    assert len(responses.calls) == 2
    queries = [parse_qs(urlsplit(call.request.url).query) for call in responses.calls]
    assert [query["offset"] for query in queries] == [["0"], ["20"]]
    assert all(query["limit"] == ["20"] for query in queries)
    assert all(call.request.headers["Authorization"] == f"Bearer {TOKEN}" for call in responses.calls)
    assert manager.save_state.call_count == 1
    assert manager.save_state.call_args.args[0].offset == 20
    if name != "payments":
        assert all(set(query) == {"limit", "offset"} for query in queries)
    manager.clear_state.assert_not_called()
    assert source.on_complete is not None
    source.on_complete()
    manager.clear_state.assert_called_once()


@pytest.mark.parametrize(
    ("incremental", "cursor", "expected_begin"),
    [
        (False, "2026-06-01T00:00:00Z", None),
        (True, None, None),
        (True, "2026-06-01T00:00:00Z", datetime(2026, 6, 1, tzinfo=UTC)),
        (True, datetime(2026, 6, 1), datetime(2026, 6, 1, tzinfo=UTC)),
        (True, "2026-06-01T03:00:00+03:00", datetime(2026, 6, 1, tzinfo=UTC)),
        (True, "2020-01-01T00:00:00Z", None),
    ],
)
def test_payment_time_filters(
    incremental: bool,
    cursor: str | datetime | None,
    expected_begin: datetime | None,
) -> None:
    with time_machine.travel(NOW, tick=False):
        result = _driver().run(
            "payments",
            [ScriptedResponse(json={"results": [], "paging": {"total": 0}})],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=cursor,
        )
    assert result.raised is None
    assert result.rows == []
    assert len(result.requests) == 1
    request = result.requests[0]
    begin = datetime.fromisoformat(request.param("begin_date") or "")
    assert begin == (expected_begin or NOW - timedelta(days=365) + timedelta(milliseconds=1))
    assert datetime.fromisoformat(request.param("end_date") or "") == NOW
    assert request.param("range") == ("date_last_updated" if incremental else "date_created")
    assert request.param("sort") == ("date_last_updated" if incremental else "date_created")
    assert result.response is not None
    assert request.param("criteria") == result.response.sort_mode == "asc"
    assert result.response.partition_keys == ["date_created"]
    assert result.saved_states == []


@pytest.mark.parametrize("name", ["payments", "subscriptions", "subscription_plans"])
def test_resume_keeps_offset_and_payment_window(name: str) -> None:
    resume_state = MercadoPagoResumeConfig(
        offset=20, begin_date="2026-06-01T00:00:00.000+00:00", end_date="2026-06-02T00:00:00.000+00:00"
    )
    paths = {
        "payments": "/v1/payments/search",
        "subscriptions": "/preapproval/search",
        "subscription_plans": "/preapproval_plan/search",
    }
    with time_machine.travel(NOW, tick=False):
        result = _driver().run(
            name,
            [ScriptedResponse(json={"results": [{"id": "last"}], "paging": {"total": 21}})],
            resume_state=resume_state,
        )
    assert result.raised is None
    assert result.items == [[{"id": "last"}]]
    assert result.paths == [paths[name]]
    assert result.params("offset") == ["20"]
    if name == "payments":
        assert result.params("begin_date") == ["2026-06-01T00:00:00.000+00:00"]
        assert result.params("end_date") == ["2026-06-02T00:00:00.000+00:00"]
    assert result.saved_states == []


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_are_actionable(status: int) -> None:
    source = MercadoPagoSource()
    config = MercadoPagoSourceConfig(access_token=TOKEN)
    answer = ScriptedResponse(status=status, json={"error": "unauthorized"})
    with scripted_network([answer]) as network:
        valid, message = source.validate_credentials(config, team_id=1)
    assert valid is False
    assert message is not None and "access token" in message
    result = _driver().run("payments", [answer])
    assert isinstance(result.raised, HTTPError)
    assert any(
        pattern in str(result.raised) and mapped == message
        for pattern, mapped in source.get_non_retryable_errors().items()
    )
    assert len(network.requests_log) + len(result.requests) == 2


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, (True, None)),
        (400, HTTPError),
        (
            429,
            (
                False,
                "Couldn't reach Mercado Pago (Mercado Libre) to check your credentials. Try again in a few minutes.",
            ),
        ),
        (
            503,
            (
                False,
                "Couldn't reach Mercado Pago (Mercado Libre) to check your credentials. Try again in a few minutes.",
            ),
        ),
    ],
)
def test_credential_validation_uses_one_request(
    status: int, expected: type[Exception] | tuple[bool, str | None]
) -> None:
    body: dict[str, Any] = {"results": [], "paging": {"total": 0}} if status == 200 else {"error": "test_error"}
    source = MercadoPagoSource()
    config = MercadoPagoSourceConfig(access_token=TOKEN)
    with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
        if isinstance(expected, tuple):
            assert source.validate_credentials(config, team_id=1) == expected
        else:
            with pytest.raises(expected):
                source.validate_credentials(config, team_id=1)
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.query == {"limit": ("1",)}
