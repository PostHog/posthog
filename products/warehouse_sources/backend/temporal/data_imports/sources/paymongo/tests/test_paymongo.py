import json
import asyncio
from collections.abc import AsyncIterable, Iterator
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
from requests import PreparedRequest, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paymongo import (
    PaymongoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paymongo.paymongo import (
    PaymongoClient,
    PaymongoResumeConfig,
    paymongo_source,
    pull_rows,
    webhook_table,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paymongo.source import PaymongoSource


def source_inputs(name: str = "payments") -> SourceInputs:
    return SourceInputs(
        schema_name=name,
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=1900000000,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job",
        logger=MagicMock(),
        reset_pipeline=False,
    )


def row(identifier: str, **attributes: Any) -> dict[str, Any]:
    return {"id": identifier, "type": "payment", "attributes": {"created_at": 1700000000, **attributes}}


def driver() -> SourceDriver:
    return SourceDriver(PaymongoSource(), PaymongoSourceConfig(api_key="fake"))


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


@pytest.fixture
def http() -> Iterator[MagicMock]:
    with patch("requests.sessions.Session.send") as send:
        yield send


def respond(http: MagicMock, bodies: list[dict[str, Any]], statuses: list[int] | None = None) -> list[PreparedRequest]:
    sent: list[PreparedRequest] = []
    responses = iter(zip(statuses or [200] * len(bodies), bodies))

    def send(request: PreparedRequest, **kwargs: Any) -> Response:
        status, body = next(responses)
        sent.append(request)
        response = Response()
        response.status_code = status
        response.reason = HTTPStatus(status).phrase
        response.url = request.url or ""
        response.request = request
        response.headers["Content-Type"] = "application/json"
        response.headers["Retry-After"] = "0"
        response._content = json.dumps(body).encode()
        return response

    http.side_effect = send
    return sent


@pytest.mark.parametrize(
    "name,metadata,url,cursor_param",
    [
        ("payments", {"has_more": True}, "https://api.paymongo.com/v1/payments", "after"),
        ("webhooks", {"has_more": True}, "https://api.paymongo.com/v1/webhooks", "after"),
        ("payouts", {"pagination": {"next_cursor": "pay_1"}}, "https://api.paymongo.com/v1/payouts", "after"),
        ("invoices", {"has_more": True}, "https://invoices-api.paymongo.com/v1/invoices", "starting_after"),
    ],
)
def test_pagination_auth_normalization_and_checkpoint(
    http: MagicMock, manager: MagicMock, name: str, metadata: dict[str, Any], url: str, cursor_param: str
) -> None:
    sent = respond(
        http,
        [
            {"data": [row("pay_1", secret_key="fake-signing-secret")], **metadata},
            {"data": [row("pay_2")], "has_more": False},
        ],
    )
    pages = pull_rows("sk_test_fake", source_inputs(name), manager)
    first = next(pages)
    assert first == [{"id": "pay_1", "type": "payment", "created_at": datetime.fromtimestamp(1700000000, UTC)}]
    manager.save_state.assert_not_called()
    assert next(pages)[0]["id"] == "pay_2"
    assert manager.save_state.call_args.args[0].paginator_state == {"cursor": "pay_1"}
    assert list(pages) == []
    assert manager.save_state.call_args.args[0].finished
    assert sent[0].headers["Authorization"] == "Basic c2tfdGVzdF9mYWtlOg=="
    assert (sent[0].url or "").split("?")[0] == url
    assert parse_qs(urlsplit(sent[0].url or "").query) == {"limit": ["10"]}
    assert parse_qs(urlsplit(sent[1].url or "").query) == {"limit": ["10"], cursor_param: ["pay_1"]}


@pytest.mark.parametrize("finished", [False, True])
def test_resume_skips_completed_pages(http: MagicMock, manager: MagicMock, finished: bool) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = PaymongoResumeConfig(paginator_state={"cursor": "pay_saved"}, finished=finished)
    sent = respond(http, [{"data": [], "has_more": False}])
    assert list(pull_rows("fake", source_inputs(), manager)) == []
    if finished:
        assert sent == []
    else:
        assert parse_qs(urlsplit(sent[0].url or "").query)["after"] == ["pay_saved"]


def test_refund_fanout_keeps_payment_and_child_cursors() -> None:
    result = driver().run(
        "refunds",
        [
            ScriptedResponse(json={"data": [row("pay_one"), row("pay_two")], "has_more": False}),
            ScriptedResponse(json={"data": [row("ref_one", payment_id="pay_one")], "has_more": True}),
            ScriptedResponse(json={"data": [row("ref_two", payment_id="pay_one")], "has_more": False}),
            ScriptedResponse(json={"data": [row("ref_three", payment_id="pay_two")], "has_more": False}),
        ],
    )
    assert result.raised is None
    assert [item["id"] for item in result.rows] == ["ref_one", "ref_two", "ref_three"]
    queries = result.queries[1:]
    assert queries == [
        {"data.attributes.payment_id": ("pay_one",), "data.attributes.limit": ("10",)},
        {
            "data.attributes.payment_id": ("pay_one",),
            "data.attributes.limit": ("10",),
            "data.attributes.after": ("ref_one",),
        },
        {"data.attributes.payment_id": ("pay_two",), "data.attributes.limit": ("10",)},
    ]


def test_payout_transaction_fanout_keys_rows_by_payout() -> None:
    result = driver().run(
        "payout_transactions",
        [
            ScriptedResponse(json={"data": [row("po_one")], "pagination": {"next_cursor": "po_one"}}),
            ScriptedResponse(
                json={"data": [row("pay_one", payout_id="po_one")], "pagination": {"next_cursor": "pay_one"}}
            ),
            ScriptedResponse(json={"data": [row("ref_one", payout_id="po_one")], "pagination": {"next_cursor": None}}),
            ScriptedResponse(json={"data": [row("po_two")], "pagination": {"next_cursor": None}}),
            ScriptedResponse(json={"data": [row("pay_one", payout_id="po_two")], "pagination": {"next_cursor": None}}),
        ],
    )
    assert result.raised is None
    assert [(item["_payouts_id"], item["id"]) for item in result.rows] == [
        ("po_one", "pay_one"),
        ("po_one", "ref_one"),
        ("po_two", "pay_one"),
    ]
    assert result.paths == [
        "/v1/payouts",
        "/v1/payouts/po_one/transactions",
        "/v1/payouts/po_one/transactions",
        "/v1/payouts",
        "/v1/payouts/po_two/transactions",
    ]
    assert result.queries[2] == {"limit": ("10",), "after": ("pay_one",)}


@pytest.mark.parametrize(
    "body,message", [({"data": [row("pay_same")], "has_more": True}, "repeated"), ({"unexpected": []}, "data")]
)
def test_broken_pagination_fails_instead_of_looping_or_truncating(
    http: MagicMock, manager: MagicMock, body: dict[str, Any], message: str
) -> None:
    respond(http, [body, body])
    with pytest.raises(ValueError, match=message):
        list(pull_rows("fake", source_inputs(), manager))


@pytest.mark.parametrize("has_more", [False, True])
def test_links_use_new_api_and_reject_truncation(has_more: bool) -> None:
    result = driver().run(
        "links",
        [
            ScriptedResponse(
                json={"data": [{"id": "link_one", "created_at": "2026-01-01T00:00:00Z"}], "has_more": has_more}
            )
        ],
    )
    if has_more:
        assert isinstance(result.raised, ValueError)
        assert "more payment links" in str(result.raised)
    else:
        assert result.raised is None
        assert result.rows[0]["id"] == "link_one"
    assert result.urls == ["https://api.paymongo.com/v1/payment_links"]


@pytest.mark.parametrize(
    "status,schema,valid,message",
    [
        (403, None, True, None),
        (403, "payouts", False, "permissions"),
    ],
)
def test_credential_probe_status_mapping(status: int, schema: str | None, valid: bool, message: str | None) -> None:
    with scripted_network([ScriptedResponse(status=status, json={"data": []})]) as network:
        result, error = PaymongoClient("fake").validate_credentials(schema)
    assert result is valid
    if message:
        assert error is not None and message in error
    else:
        assert error is None
    assert network.requests_log[0].param("limit") == "1"


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_pull_retries_only_transient_statuses(http: MagicMock, manager: MagicMock, status: int) -> None:
    respond(http, [{}, {"data": [], "has_more": False}], [status, 200])
    if status in (401, 403):
        with pytest.raises(HTTPError) as error:
            list(pull_rows("fake", source_inputs(), manager))
        assert any(pattern in str(error.value) for pattern in PaymongoSource().get_non_retryable_errors())
        assert http.call_count == 1
    else:
        assert list(pull_rows("fake", source_inputs(), manager)) == []
        assert http.call_count == 2


def test_webhook_management_reuses_matching_url_and_disables_only_owned_endpoint() -> None:
    url = "https://example.com/hook"
    hook = {
        "id": "hook_one",
        "attributes": {"url": url, "status": "disabled", "events": [], "secret_key": "fake-secret"},
    }
    unrelated = {"id": "hook_other", "attributes": {"url": "https://example.com/other"}}
    with scripted_network(
        [
            ScriptedResponse(json={"data": [unrelated, hook], "has_more": False}),
            ScriptedResponse(json={}),
            ScriptedResponse(json={"data": hook}),
            ScriptedResponse(json={"data": [unrelated, hook], "has_more": False}),
            ScriptedResponse(json={}),
        ],
    ) as network:
        client = PaymongoClient("fake")
        result = client.create_webhook(url)
        assert client.delete_webhook(url).success
    assert result.success and result.extra_inputs == {"signing_secret": "fake-secret"}
    assert [(request.method, request.path) for request in network.requests_log] == [
        ("GET", "/v1/webhooks"),
        ("PUT", "/v1/webhooks/hook_one"),
        ("POST", "/v1/webhooks/hook_one/enable"),
        ("GET", "/v1/webhooks"),
        ("POST", "/v1/webhooks/hook_one/disable"),
    ]


@pytest.mark.parametrize("secret", ["fake-signing-secret", None])
def test_webhook_creation_saves_or_requests_signing_secret(secret: str | None) -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"data": [], "has_more": False}),
            ScriptedResponse(json={"data": {"attributes": {"secret_key": secret}}}),
        ]
    ) as network:
        result = PaymongoClient("fake").create_webhook("https://example.com/hook")
    assert result.success
    assert result.pending_inputs == ([] if secret else ["signing_secret"])
    assert result.extra_inputs == ({"signing_secret": secret} if secret else {})
    assert network.requests_log[1].json()["data"]["attributes"]["url"] == "https://example.com/hook"


def test_webhook_batch_deduplicates_and_matches_poll_shape() -> None:
    def event(timestamp: int, status: str) -> dict[str, Any]:
        return {"data": {"attributes": {"created_at": timestamp, "data": row("pay_one", status=status)}}}

    result = webhook_table(
        table_from_py_list([event(30, "refunded"), event(10, "paid"), event(30, "refunded")]), PaymongoClient("fake")
    )
    assert result.to_pylist() == [
        {
            "created_at": datetime.fromtimestamp(1700000000, UTC),
            "status": "refunded",
            "id": "pay_one",
            "type": "payment",
        }
    ]


def test_webhook_batch_skips_events_without_required_identifiers_or_timestamp() -> None:
    def event(item: dict[str, Any], created_at: int | None = 1700000100) -> dict[str, Any]:
        attributes: dict[str, Any] = {"data": item}
        if created_at is not None:
            attributes["created_at"] = created_at
        return {"data": {"attributes": attributes}}

    malformed = [
        event({"type": "payment"}),
        event({"id": "pay_one", "type": "payment"}, created_at=None),
        event({"id": "ref_one", "type": "refund", "attributes": {}}),
    ]

    assert webhook_table(table_from_py_list(malformed), PaymongoClient("fake")).num_rows == 0


def test_webhook_sync_does_not_poll(http: MagicMock, manager: MagicMock) -> None:
    webhook_manager = MagicMock()
    webhook_manager.webhook_enabled = AsyncMock(return_value=True)

    async def batches(**kwargs: Any) -> Any:
        yield pa.Table.from_pylist([{"id": "pay_one"}])

    webhook_manager.get_items = batches
    response = paymongo_source("fake", source_inputs(), manager, webhook_manager)

    async def collect() -> list[Any]:
        items = cast(AsyncIterable[Any], response.items())
        return [table async for table in items]

    assert asyncio.run(collect())[0].to_pylist() == [{"id": "pay_one"}]
    http.assert_not_called()


def test_refund_resume_continues_child_cursor() -> None:
    parents = {"data": [row("pay_one"), row("pay_two")], "has_more": False}
    first = driver().run(
        "refunds",
        [
            ScriptedResponse(json=parents),
            ScriptedResponse(json={"data": [row("ref_one")], "has_more": True}),
            ScriptedResponse(json={"data": [row("ref_two")], "has_more": False}),
        ],
    )
    assert [item["id"] for item in first.rows] == ["ref_one", "ref_two"]
    assert first.raised is not None
    saved = first.final_state
    assert isinstance(saved, PaymongoResumeConfig)
    resumed = driver().run(
        "refunds",
        [
            ScriptedResponse(json=parents),
            ScriptedResponse(json={"data": [row("ref_two")], "has_more": False}),
            ScriptedResponse(json={"data": [row("ref_three")], "has_more": False}),
        ],
        resume_state=saved,
    )
    assert resumed.raised is None
    assert [item["id"] for item in resumed.rows] == ["ref_two", "ref_three"]
    assert resumed.requests[1].param("data.attributes.after") == "ref_one"


def test_refund_webhooks_refresh_payment_once() -> None:
    event = {
        "data": {
            "attributes": {
                "created_at": 1700000100,
                "data": {"id": "ref_one", "type": "refund", "attributes": {"payment_id": "pay_one"}},
            }
        }
    }
    with scripted_network(
        [ScriptedResponse(json={"data": row("pay_one", status="refunded", refunds=[{"id": "ref_one"}])})]
    ) as network:
        table = webhook_table(table_from_py_list([event, event]), PaymongoClient("fake"))
    assert table.to_pylist()[0]["status"] == "refunded"
    assert json.loads(table.to_pylist()[0]["refunds"]) == [{"id": "ref_one"}]
    assert [request.url for request in network.requests_log] == ["https://api.paymongo.com/v1/payments/pay_one"]


@pytest.mark.parametrize("exists", [True, False])
def test_webhook_info_finds_matching_url_on_later_page(exists: bool) -> None:
    url = "https://example.com/hook"
    hook = {
        "id": "hook_one",
        "attributes": {"url": url, "events": ["payment.paid"], "status": "enabled", "secret_key": "fake-secret"},
    }
    with scripted_network(
        [
            ScriptedResponse(
                json={
                    "data": [{"id": "hook_other", "attributes": {"url": "https://example.com/other"}}],
                    "has_more": True,
                }
            ),
            ScriptedResponse(json={"data": [hook] if exists else [], "has_more": False}),
        ],
    ):
        info = PaymongoClient("fake").get_external_webhook_info(url)
    assert info.exists is exists
    if exists:
        assert info.status == "enabled"
        assert info.enabled_events == ["payment.paid"]
    assert "fake-secret" not in repr(info)


@pytest.mark.parametrize(
    "status,schema,parent_path,child_path,child_query",
    [
        (
            status,
            "refunds",
            "/v1/payments",
            "/v1/refunds",
            {"data.attributes.payment_id": ("pay_one",), "data.attributes.limit": ("1",)},
        )
        for status in (200, 403)
    ]
    + [
        (status, "payout_transactions", "/v1/payouts", "/v1/payouts/pay_one/transactions", {"limit": ("1",)})
        for status in (200, 403)
    ],
)
def test_child_permissions_probe_child_endpoint(
    status: int, schema: str, parent_path: str, child_path: str, child_query: dict[str, tuple[str, ...]]
) -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"data": [row("pay_one")]}),
            ScriptedResponse(status=status, json={"data": []}),
        ]
    ) as network:
        valid, message = PaymongoClient("fake").validate_credentials(schema)
    assert valid is (status == 200)
    if status == 200:
        assert message is None
    else:
        assert message is not None and "permissions" in message
    assert network.requests_log[0].path == parent_path
    assert network.requests_log[1].path == child_path
    assert network.requests_log[1].query == child_query
