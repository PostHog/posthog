import json
import base64
from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest

from requests import PreparedRequest
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.alegra.source import AlegraSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.alegra import AlegraSourceConfig


def rows(response: SourceResponse) -> list[Any]:
    return list(cast(Iterable[Any], response.items()))


def response_for(config: AlegraSourceConfig, inputs: SourceInputs) -> SourceResponse:
    source = AlegraSource()
    return source.source_for_pipeline(config, source.get_resumable_source_manager(inputs), inputs)


@pytest.mark.parametrize(
    "schema, path, extra_params",
    [
        ("invoices", "invoices", {"order_field": ["id"], "order_direction": ["ASC"]}),
        ("contacts", "contacts", {"order_field": ["id"], "order_direction": ["ASC"], "mode": ["advanced"]}),
        ("items", "items", {"order_field": ["id"], "order_direction": ["ASC"], "mode": ["advanced"]}),
        ("incoming_payments", "payments", {"order_field": ["id"], "order_direction": ["ASC"], "type": ["in"]}),
        ("outgoing_payments", "payments", {"order_field": ["id"], "order_direction": ["ASC"], "type": ["out"]}),
        ("bills", "bills", {"order_field": ["date"], "order_direction": ["ASC"]}),
        ("estimates", "estimates", {"order_field": ["id"], "order_direction": ["ASC"]}),
        ("credit_notes", "credit-notes", {}),
        ("debit_notes", "debit-notes", {}),
    ],
)
def test_endpoint_requests_preserve_raw_rows_and_omit_watermarks(
    config: AlegraSourceConfig,
    inputs: SourceInputs,
    http_boundary: Callable[..., list[PreparedRequest]],
    redis_boundary: dict[str, str],
    schema: str,
    path: str,
    extra_params: dict[str, list[str]],
) -> None:
    row = {"id": "00000000-0000-4000-8000-000000000001", "items": [{"id": "line-test", "price": "12.50"}]}
    sent = http_boundary([(200, [row])])
    response = response_for(config, replace(inputs, schema_name=schema))
    assert rows(response) == [[row]]
    url = urlsplit(sent[0].url or "")
    assert url.scheme == "https"
    assert url.netloc == "api.alegra.com"
    assert url.path == f"/api/v1/{path}"
    assert parse_qs(url.query) == {"start": ["0"], "limit": ["30"], **extra_params}
    assert (
        sent[0].headers["Authorization"]
        == "Basic " + base64.b64encode(b"warehouse@example.com:fake-alegra-token").decode()
    )


@pytest.mark.parametrize("terminal_rows", [[], [{"id": "last-test"}]])
def test_offset_pagination_and_checkpoint_resume(
    config: AlegraSourceConfig,
    inputs: SourceInputs,
    http_boundary: Callable[..., list[PreparedRequest]],
    redis_boundary: dict[str, str],
    terminal_rows: list[dict[str, str]],
) -> None:
    first_page = [{"id": f"invoice-test-{index}"} for index in range(30)]
    sent = http_boundary([(200, first_page), (200, terminal_rows)])
    source = AlegraSource()
    manager = source.get_resumable_source_manager(inputs)
    response = source.source_for_pipeline(config, manager, inputs)
    pages = iter(cast(Iterable[list[dict[str, Any]]], response.items()))
    assert next(pages) == first_page
    manager.confirm()
    assert not manager.has_staged_state()
    assert list(pages) == ([terminal_rows] if terminal_rows else [])
    assert [parse_qs(urlsplit(request.url or "").query)["start"] for request in sent] == [["0"], ["30"]]
    manager.confirm()
    manager.commit()
    assert [json.loads(value) for value in redis_boundary.values()] == [{"offset": 30}]

    resumed_requests = http_boundary([(200, [{"id": "resumed-test"}])])
    assert rows(response_for(config, inputs)) == [[{"id": "resumed-test"}]]
    assert parse_qs(urlsplit(resumed_requests[0].url or "").query)["start"] == ["30"]


@pytest.mark.parametrize("body", [{"message": "unexpected response"}, {"data": [{"id": "wrong-envelope"}]}])
def test_unexpected_envelope_fails_instead_of_replacing_with_garbage(
    config: AlegraSourceConfig,
    inputs: SourceInputs,
    http_boundary: Callable[..., list[PreparedRequest]],
    redis_boundary: dict[str, str],
    body: dict[str, Any],
) -> None:
    http_boundary([(200, body)])
    with pytest.raises(ValueError, match="Required a list response body"):
        rows(response_for(config, inputs))


@pytest.mark.parametrize("status", [401, 403])
def test_pipeline_auth_errors_match_terminal_errors(
    config: AlegraSourceConfig,
    inputs: SourceInputs,
    http_boundary: Callable[..., list[PreparedRequest]],
    redis_boundary: dict[str, str],
    status: int,
) -> None:
    sent = http_boundary([(status, {"code": "AUTH_TEST"})])
    with pytest.raises(HTTPError) as error:
        rows(response_for(config, inputs))
    assert error_message_matches(str(error.value), AlegraSource().get_non_retryable_errors())
    assert len(sent) == 1


@pytest.mark.parametrize("status", [429, 500])
def test_transient_failures_retry_through_framework(
    config: AlegraSourceConfig,
    inputs: SourceInputs,
    http_boundary: Callable[..., list[PreparedRequest]],
    redis_boundary: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    delays: list[float] = []
    monkeypatch.setattr(RESTClient._send_request.retry, "sleep", delays.append)  # type: ignore[attr-defined]
    sent = http_boundary([(status, {})] * 7 + [(200, [{"id": "recovered-test"}])], {"Retry-After": "10"})
    assert rows(response_for(config, inputs)) == [[{"id": "recovered-test"}]]
    assert len(sent) == 8
    assert delays == [10.0] * 7


def test_unknown_table_fails_before_network(
    config: AlegraSourceConfig, inputs: SourceInputs, http_boundary: Callable[..., list[PreparedRequest]]
) -> None:
    sent = http_boundary([])
    with pytest.raises(UnknownResourceError):
        response_for(config, replace(inputs, schema_name="missing_table"))
    assert sent == []
