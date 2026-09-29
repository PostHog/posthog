from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests_mock
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lexware_office.lexware_office import (
    LexwareOfficeResumeConfig,
    lexware_office_source,
)

BASE = "https://api.lexware.io/v1"
CREATED = "2026-01-01T00:00:00Z"


def manager(state: LexwareOfficeResumeConfig | None = None) -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = state is not None
    result.load_state.return_value = state
    return result


def rows(endpoint: str, resume: MagicMock) -> Iterable[list[dict[str, Any]]]:
    response = lexware_office_source("fake-key", endpoint, 1, "job", resume)
    return cast(Iterable[list[dict[str, Any]]], response.items())


@pytest.mark.parametrize("endpoint", ["contacts", "articles", "voucherlist"])
def test_pages_and_resume_checkpoint_after_yield(endpoint: str) -> None:
    resume = manager()
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE}/{endpoint}",
            [
                {"json": {"content": [{"id": "a"}], "totalPages": 2, "last": False}},
                {"json": {"content": [{"id": "b"}], "totalPages": 2, "last": True}},
            ],
        )
        iterator = iter(rows(endpoint, resume))
        assert next(iterator) == [{"id": "a"}]
        resume.save_state.assert_not_called()
        assert next(iterator) == [{"id": "b"}]
        assert resume.save_state.call_args.args[0].paginator_state == {"page": 1}
        assert list(iterator) == []
        assert resume.save_state.call_args.args[0].completed
        assert [r.qs["page"] for r in http.request_history] == [["0"], ["1"]]
        assert http.last_request is not None
        assert http.last_request.headers["Authorization"] == "Bearer fake-key"
        assert "updateddatefrom" not in http.last_request.qs
        if endpoint == "voucherlist":
            assert http.last_request.qs["vouchertype"] == ["any"]
            assert http.last_request.qs["voucherstatus"] == ["any"]
            assert http.last_request.qs["sort"] == ["createddate,asc"]
        else:
            assert "sort" not in http.last_request.qs


@pytest.mark.parametrize("completed", [False, True])
def test_resume_starts_at_saved_page_or_stops(completed: bool) -> None:
    resume = manager(LexwareOfficeResumeConfig(paginator_state={"page": 3}, completed=completed))
    with requests_mock.Mocker() as http:
        http.get(f"{BASE}/contacts", json={"content": [{"id": "d"}], "totalPages": 4})
        assert list(rows("contacts", resume)) == ([] if completed else [[{"id": "d"}]])
        if completed:
            assert not http.called
        else:
            assert http.last_request is not None
            assert http.last_request.qs["page"] == ["3"]


@pytest.mark.parametrize("endpoint", ["contacts", "invoices"])
def test_empty_collection_and_search_window_limit(endpoint: str) -> None:
    url = f"{BASE}/contacts" if endpoint == "contacts" else f"{BASE}/voucherlist"
    with requests_mock.Mocker() as http:
        http.get(url, json={"content": [], "totalPages": 0, "totalElements": 0})
        assert not any(rows(endpoint, manager()))
        http.get(url, json={"content": [{"id": "a"}], "totalPages": 40, "totalElements": 10000})
        with pytest.raises(ValueError, match="10,000-record search limit"):
            list(rows(endpoint, manager()))


@pytest.mark.parametrize(
    "endpoint,path,voucher_type",
    [
        ("invoices", "invoices", "invoice"),
        ("credit_notes", "credit-notes", "creditnote"),
        ("quotations", "quotations", "quotation"),
        ("delivery_notes", "delivery-notes", "deliverynote"),
        ("order_confirmations", "order-confirmations", "orderconfirmation"),
        ("down_payment_invoices", "down-payment-invoices", "downpaymentinvoice"),
        ("vouchers", "vouchers", "salesinvoice,salescreditnote,purchaseinvoice,purchasecreditnote"),
    ],
)
def test_document_hydration_preserves_line_items_and_creation_date(endpoint: str, path: str, voucher_type: str) -> None:
    with requests_mock.Mocker() as http:
        http.get(f"{BASE}/voucherlist", json={"content": [{"id": "doc-a", "createdDate": CREATED}], "totalPages": 1})
        http.get(f"{BASE}/{path}/doc-a", json={"id": "doc-a", "lineItems": [{"quantity": 2}]})
        assert list(rows(endpoint, manager())) == [
            [{"id": "doc-a", "createdDate": CREATED, "lineItems": [{"quantity": 2}]}]
        ]
        assert http.request_history[0].qs["vouchertype"] == [voucher_type]
        assert http.request_history[0].qs["voucherstatus"] == ["any"]
        assert http.request_history[1].qs == {}


def test_payment_identity_and_unsupported_payment_skip() -> None:
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE}/voucherlist",
            json={
                "content": [
                    {"id": "linked-credit", "createdDate": CREATED},
                    {"id": "invoice-a", "createdDate": CREATED},
                ],
                "totalPages": 1,
            },
        )
        http.get(f"{BASE}/payments/linked-credit", status_code=406, json={})
        http.get(f"{BASE}/payments/invoice-a", json={"openAmount": 15, "paymentItems": [{"amount": 5}]})
        response = lexware_office_source("fake-key", "payments", 1, "job", manager())
        assert response.primary_keys == ["voucher_id"]
        assert list(cast(Iterable, response.items())) == [
            [
                {
                    "voucher_id": "invoice-a",
                    "createdDate": CREATED,
                    "openAmount": 15,
                    "paymentItems": [{"amount": 5}],
                }
            ]
        ]
        assert "draft" not in http.request_history[0].qs["voucherstatus"][0]


def test_fanout_resume_skips_completed_documents() -> None:
    resume = manager(
        LexwareOfficeResumeConfig(
            paginator_state={"completed": ["invoices/doc-a"], "current": None, "child_state": None}
        )
    )
    with requests_mock.Mocker() as http:
        http.get(
            f"{BASE}/voucherlist",
            json={
                "content": [
                    {"id": "doc-a", "createdDate": CREATED},
                    {"id": "doc-b", "createdDate": CREATED},
                ],
                "totalPages": 1,
            },
        )
        http.get(f"{BASE}/invoices/doc-b", json={"id": "doc-b"})
        assert list(rows("invoices", resume)) == [[{"id": "doc-b", "createdDate": CREATED}]]
        assert len(http.request_history) == 2
        states = [call.args[0] for call in resume.save_state.call_args_list]
        assert any(s.paginator_state and "invoices/doc-b" in s.paginator_state.get("completed", []) for s in states)
        assert states[-1].completed


@pytest.mark.parametrize("status", [429, 500, 503, 401, 403, 404])
def test_status_retries_are_owned_by_shared_transport(status: int) -> None:
    with requests_mock.Mocker() as http, patch.object(RESTClient._send_request.retry, "sleep"):
        http.get(
            f"{BASE}/contacts",
            [
                {"status_code": status, "json": {}, "headers": {"Retry-After": "0"}},
                {"json": {"content": [{"id": "a"}], "totalPages": 1}},
            ],
        )
        if status in (401, 403, 404):
            with pytest.raises(HTTPError):
                list(rows("contacts", manager()))
            assert len(http.request_history) == 1
        else:
            assert list(rows("contacts", manager())) == [[{"id": "a"}]]
            assert len(http.request_history) == 2
