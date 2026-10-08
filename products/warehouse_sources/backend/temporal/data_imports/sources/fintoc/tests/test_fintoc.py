import hmac
import json
import time
import hashlib
from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock

import pyarrow as pa
from requests import HTTPError, PreparedRequest

from posthog.cdp.validation import compile_hog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fintoc.fintoc import (
    FintocAPI,
    FintocResumeState,
    webhook_table,
    webhook_template,
)

from common.hogvm.python.execute import execute_bytecode


@pytest.mark.parametrize("complete", [False, True])
def test_resume_does_not_restart_completed_pages(
    http_mock: MagicMock,
    manager: MagicMock,
    inputs: MagicMock,
    complete: bool,
) -> None:
    url = "https://api.fintoc.com/v2/customers?starting_after=cus_saved"
    manager.can_resume.return_value = True
    manager.load_state.return_value = FintocResumeState(paginator={"next_url": url}, complete=complete)
    http_mock.return_value = (200, [], {})
    items = FintocAPI("sk_test_example", "2026-02-01").source("customers", [], inputs, manager).items()
    assert list(cast(Iterable[Any], items)) == []
    if complete:
        http_mock.assert_not_called()
    else:
        assert http_mock.call_args.args[0].url == url


@pytest.mark.parametrize("status,retryable", [(401, False), (403, False), (429, True), (500, True)])
def test_http_retry_classification(
    http_mock: MagicMock,
    manager: MagicMock,
    inputs: MagicMock,
    status: int,
    retryable: bool,
) -> None:
    http_mock.return_value = (status, {"error": {"code": "invalid_api_key"}}, {})
    with pytest.raises(RESTClientRetryableError if retryable else HTTPError):
        items = FintocAPI("sk_test_example", "2026-02-01").source("links", [], inputs, manager).items()
        list(cast(Iterable[Any], items))
    assert http_mock.call_count == (5 if retryable else 1)
    manager.save_state.assert_not_called()


def test_movements_fanout_keeps_account_keys_and_tokens_private(
    http_mock: MagicMock,
    manager: MagicMock,
    inputs: MagicMock,
) -> None:
    tokens = ["link_example_token_one", "link_example_token_two"]
    calls: list[tuple[str, dict[str, list[str]]]] = []

    def respond(request: PreparedRequest) -> tuple[int, object, dict[str, str]]:
        parts = urlsplit(request.url or "")
        query = parse_qs(parts.query)
        calls.append((parts.path, query))
        token = query["link_token"][0]
        assert request.headers["Authorization"] == "sk_test_example"
        if parts.path == "/v1/accounts":
            return 200, [{"id": "account_one"}, {"id": "account_two"}], {}
        account = parts.path.split("/")[3]
        if "page" not in query:
            return (
                200,
                [{"id": f"{token[-3:]}_{account}_first"}],
                {"Link": f'<https://api.fintoc.com{parts.path}?page=2&link_token={token}>; rel="next"'},
            )
        return 200, [{"id": f"{token[-3:]}_{account}_last"}], {}

    http_mock.side_effect = respond
    result = FintocAPI("sk_test_example", "2026-02-01").source("movements", tokens, inputs, manager)
    pages = list(cast(Iterable[Any], result.items()))
    assert len(pages) == 8
    assert {row["account_id"] for page in pages for row in page} == {"account_one", "account_two"}
    assert result.primary_keys == ["account_id", "id"]
    assert all("_accounts_id" not in row and "link_token" not in row for page in pages for row in page)
    assert {query["link_token"][0] for _, query in calls} == set(tokens)
    for token in tokens:
        state_calls = manager.with_namespace(hashlib.sha256(token.encode()).hexdigest()).save_state.call_args_list
        assert state_calls
        assert token not in repr(state_calls)
    assert all(
        query["confirmed_only"] == ["false"] for path, query in calls if "movements" in path and "page" not in query
    )


def test_movements_resume_restores_token_and_skips_finished_accounts(
    http_mock: MagicMock,
    manager: MagicMock,
    inputs: MagicMock,
) -> None:
    token = "link_example_token_one"
    child = manager.with_namespace(hashlib.sha256(token.encode()).hexdigest())
    child.can_resume.return_value = True
    child.load_state.return_value = FintocResumeState(
        paginator={
            "completed": ["/v1/accounts/account_one/movements"],
            "current": "/v1/accounts/account_two/movements",
            "child_state": {"next_url": "https://api.fintoc.com/v1/accounts/account_two/movements?page=2"},
        }
    )
    http_mock.side_effect = [
        (200, [{"id": "account_one"}, {"id": "account_two"}], {}),
        (200, [{"id": "movement_last"}], {}),
    ]
    items = FintocAPI("sk_test_example", "2026-02-01").source("movements", [token], inputs, manager).items()
    pages = list(cast(Iterable[Any], items))
    assert pages == [[{"id": "movement_last", "account_id": "account_two"}]]
    request = http_mock.call_args.args[0]
    assert urlsplit(request.url).path == "/v1/accounts/account_two/movements"
    assert parse_qs(urlsplit(request.url).query) == {"page": ["2"], "link_token": [token]}


def test_pagination_cannot_send_credentials_off_origin(
    http_mock: MagicMock, manager: MagicMock, inputs: MagicMock
) -> None:
    http_mock.return_value = (200, [{"id": "first"}], {"Link": '<https://example.com/steal>; rel="next"'})
    with pytest.raises(ValueError, match="disallowed host"):
        items = FintocAPI("sk_test_example", "2026-02-01").source("links", [], inputs, manager).items()
        list(cast(Iterable[Any], items))
    assert http_mock.call_count == 1


def test_webhook_batch_keeps_latest_object_and_ignores_invoice_preview() -> None:
    events: list[dict[str, Any]] = [
        {"created_at": "2026-01-02T00:00:00Z", "data": {"id": "invoice_one", "status": "paid"}},
        {"created_at": "2026-01-01T00:00:00Z", "data": {"id": "invoice_one", "status": "draft"}},
        {"created_at": "2026-01-03T00:00:00Z", "data": {"id": None, "status": "draft"}},
        {"created_at": None, "data": {"id": "invoice_two", "status": "draft"}},
    ]
    assert webhook_table(pa.Table.from_pylist(events)).to_pylist() == [
        {"id": "invoice_one", "status": "paid"},
        {"id": "invoice_two", "status": "draft"},
    ]


@pytest.mark.parametrize(
    "kind,status,delivered",
    [
        ("valid", 200, True),
        ("bad", 400, False),
        ("missing", 400, False),
        ("expired", 400, False),
        ("malformed_timestamp", 400, False),
        ("future", 400, False),
        ("multiple_signatures", 200, True),
        ("unconfigured", 503, False),
        ("unmapped", 200, False),
        ("preview", 200, False),
        ("get", 405, False),
    ],
)
def test_signed_webhook_routing(kind: str, status: int, delivered: bool) -> None:
    data: dict[str, Any] = {"id": "invoice_one", "object": "invoice"}
    body: dict[str, Any] = {
        "created_at": "2026-01-01T00:00:00Z",
        "data": data,
    }
    if kind == "preview":
        data["id"] = None
    payload = json.dumps(body)
    timestamp = str(int(time.time()) + {"expired": -1000, "future": 1000}.get(kind, 0))
    if kind == "malformed_timestamp":
        timestamp = "not-a-number"
    signature = hmac.new(b"test_signing_secret", f"{timestamp}.{payload}".encode(), hashlib.sha256).hexdigest()
    header = f"t={timestamp},v1={signature if kind != 'bad' else 'bad'}"
    if kind == "multiple_signatures":
        header += ",v1=another_signature"
    produce = MagicMock()
    template = webhook_template()
    result = execute_bytecode(
        compile_hog(template.code, template.type),
        {
            "request": {
                "method": "GET" if kind == "get" else "POST",
                "body": body,
                "stringBody": payload,
                "headers": {"fintoc-signature": "" if kind == "missing" else header},
            },
            "inputs": {
                "signing_secret": "" if kind == "unconfigured" else "test_signing_secret",
                "schema_mapping": {} if kind == "unmapped" else {"invoice": "schema_example"},
            },
        },
        functions={"produceToWarehouseWebhooks": produce},
    )
    assert result.result["httpResponse"]["status"] == status
    if delivered:
        produce.assert_called_once_with(body, "schema_example")
    else:
        produce.assert_not_called()
