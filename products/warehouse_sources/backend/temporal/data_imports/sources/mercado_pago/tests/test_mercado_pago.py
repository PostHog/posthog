from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
import time_machine
from unittest.mock import MagicMock

import responses
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
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
@responses.activate
def test_payment_time_filters(
    inputs: SourceInputs,
    manager: MagicMock,
    incremental: bool,
    cursor: str | datetime | None,
    expected_begin: datetime | None,
) -> None:
    inputs.should_use_incremental_field = incremental
    inputs.db_incremental_field_last_value = cursor
    responses.get("https://api.mercadopago.com/v1/payments/search", json={"results": [], "paging": {"total": 0}})
    with time_machine.travel(NOW, tick=False):
        source = MercadoPagoSource().source_for_pipeline(MercadoPagoSourceConfig(access_token=TOKEN), manager, inputs)
        list(cast(Iterable[Any], source.items()))
    query = parse_qs(urlsplit(responses.calls[0].request.url).query)
    begin = datetime.fromisoformat(query["begin_date"][0])
    assert begin == (expected_begin or NOW - timedelta(days=365) + timedelta(milliseconds=1))
    assert datetime.fromisoformat(query["end_date"][0]) == NOW
    assert query["range"] == ["date_last_updated" if incremental else "date_created"]
    assert query["sort"] == ["date_last_updated" if incremental else "date_created"]
    assert query["criteria"] == [source.sort_mode] == ["asc"]
    assert source.partition_keys == ["date_created"]
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("name", ["payments", "subscriptions", "subscription_plans"])
@responses.activate
def test_resume_keeps_offset_and_payment_window(inputs: SourceInputs, manager: MagicMock, name: str) -> None:
    inputs.schema_name = name
    manager.can_resume.return_value = True
    manager.load_state.return_value = MercadoPagoResumeConfig(
        offset=20, begin_date="2026-06-01T00:00:00.000+00:00", end_date="2026-06-02T00:00:00.000+00:00"
    )
    paths = {
        "payments": "/v1/payments/search",
        "subscriptions": "/preapproval/search",
        "subscription_plans": "/preapproval_plan/search",
    }
    responses.get(
        "https://api.mercadopago.com" + paths[name], json={"results": [{"id": "last"}], "paging": {"total": 21}}
    )
    with time_machine.travel(NOW, tick=False):
        source = MercadoPagoSource().source_for_pipeline(MercadoPagoSourceConfig(access_token=TOKEN), manager, inputs)
        assert list(cast(Iterable[Any], source.items())) == [[{"id": "last"}]]
    query = parse_qs(urlsplit(responses.calls[0].request.url).query)
    assert query["offset"] == ["20"]
    if name == "payments":
        assert query["begin_date"] == ["2026-06-01T00:00:00.000+00:00"]
        assert query["end_date"] == ["2026-06-02T00:00:00.000+00:00"]
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("status", [401, 403])
@responses.activate
def test_auth_errors_are_actionable(inputs: SourceInputs, manager: MagicMock, status: int) -> None:
    responses.get("https://api.mercadopago.com/v1/payments/search", status=status, json={"error": "unauthorized"})
    source = MercadoPagoSource()
    config = MercadoPagoSourceConfig(access_token=TOKEN)
    valid, message = source.validate_credentials(config, team_id=1)
    assert valid is False
    assert message is not None and "access token" in message
    response = source.source_for_pipeline(config, manager, inputs)
    with pytest.raises(HTTPError) as error:
        list(cast(Iterable[Any], response.items()))
    assert any(
        pattern in str(error.value) and mapped == message
        for pattern, mapped in source.get_non_retryable_errors().items()
    )
    assert len(responses.calls) == 2


@pytest.mark.parametrize("status", [200, 400, 429, 503])
@responses.activate
def test_credential_validation_uses_one_request(status: int) -> None:
    body: dict[str, Any] = {"results": [], "paging": {"total": 0}} if status == 200 else {"error": "test_error"}
    responses.get("https://api.mercadopago.com/v1/payments/search", status=status, json=body)
    source = MercadoPagoSource()
    config = MercadoPagoSourceConfig(access_token=TOKEN)
    if status == 200:
        assert source.validate_credentials(config, team_id=1) == (True, None)
    else:
        with pytest.raises(RESTClientRetryableError if status >= 429 else HTTPError):
            source.validate_credentials(config, team_id=1)
    assert len(responses.calls) == 1
    request = responses.calls[0].request
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert parse_qs(urlsplit(request.url).query) == {"limit": ["1"]}
