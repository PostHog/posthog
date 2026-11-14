import json
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.sources.sdk import UnknownResourceError
from products.warehouse_sources.sources.trustradius.source import TrustradiusSource
from products.warehouse_sources.sources.trustradius.trustradius import trustradius_source, validate_credentials

TRANSPORT = "products.warehouse_sources.sources.trustradius.trustradius"


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result.url = "https://api.trustradius.com/v1/product-ids"
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


@pytest.mark.parametrize(
    ("endpoint", "path", "row", "params"),
    [
        ("products", "product-ids", {"_id": "product-example", "slug": "example-product"}, {}),
        ("product_scores", "product-scores", {"id": "product-example", "reviewCount": 42}, {}),
        (
            "trustquotes",
            "trustquotes",
            {"id": "quote-example", "text": "An invented quote.", "created": "2025-01-01"},
            {"include-anonymous": ["true"]},
        ),
        ("tags", "tags", {"id": "tag-example", "name": "Example tag"}, {}),
    ],
)
@pytest.mark.parametrize("empty", [False, True])
def test_full_refresh_selects_rows_and_stops_after_one_request(
    endpoint: str, path: str, row: dict[str, Any], params: dict[str, list[str]], empty: bool
) -> None:
    rows = [] if empty else [row]
    body = {"products": rows} if endpoint == "product_scores" else rows
    with patch("requests.adapters.HTTPAdapter.send", return_value=response(body)) as send:
        result = trustradius_source("example-secret", endpoint, 1, "test-job")
        assert [item for page in cast(Iterable[Any], result.items()) for item in page] == rows

    send.assert_called_once()
    request = send.call_args.args[0]
    assert request.method.upper() == "GET"
    assert urlsplit(request.url).path == f"/v1/{path}"
    assert parse_qs(urlsplit(request.url).query) == params
    assert request.headers["x-api-key"] == "example-secret"
    assert request.headers["Accept"] == "application/json"
    assert "example-secret" not in request.url
    first_try = send.call_args.kwargs["timeout"].clone()
    first_try.start_connect()
    assert (first_try.connect_timeout, first_try.read_timeout) == (10, 60)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, [], (True, None)),
        (
            401,
            {
                "name": "NotAuthorized",
                "status": 401,
                "message": "You are not authorized to access Unable to verify your identity, please check that your API key is valid",
            },
            (
                False,
                "TrustRadius rejected your API key. Check the key with your TrustRadius Client Success Manager.",
            ),
        ),
        (
            403,
            {"message": "Forbidden"},
            (
                False,
                "TrustRadius denied access. Ask your Client Success Manager to check your API license and permissions.",
            ),
        ),
    ],
)
def test_validate_credentials_uses_one_request_and_maps_auth_errors(
    status: int, body: object, expected: tuple[bool, str | None]
) -> None:
    with patch("requests.adapters.HTTPAdapter.send", return_value=response(body, status)) as send:
        assert validate_credentials("example-secret") == expected
    send.assert_called_once()
    request = send.call_args.args[0]
    assert request.url == "https://api.trustradius.com/v1/product-ids"
    assert request.headers["x-api-key"] == "example-secret"


@pytest.mark.parametrize("status", [400, 404])
def test_validation_does_not_mislabel_other_errors(status: int) -> None:
    with patch("requests.adapters.HTTPAdapter.send", return_value=response({}, status)) as send:
        with pytest.raises(HTTPError):
            validate_credentials("example-secret")
    send.assert_called_once()


@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_errors_match_terminal_messages(status: int) -> None:
    with patch("requests.adapters.HTTPAdapter.send", return_value=response({}, status)) as send:
        with pytest.raises(HTTPError) as error:
            list(cast(Iterable[Any], trustradius_source("example-secret", "products", 1, "test-job").items()))
    send.assert_called_once()
    messages = TrustradiusSource().get_non_retryable_errors()
    assert len([message for pattern, message in messages.items() if pattern in str(error.value)]) == 1


def routed_send(routes: Callable[[str, dict[str, list[str]]], object], requests: list[tuple[str, dict]]):
    def send(request: Any, **kwargs: Any) -> Response:
        url = urlsplit(request.url)
        params = parse_qs(url.query)
        requests.append((url.path, params))
        return response(routes(url.path, params))

    return send


def read_rows(endpoint: str, **kwargs: Any) -> list[dict[str, Any]]:
    result = trustradius_source("example-secret", endpoint, 1, "test-job", **kwargs)
    return [row for page in cast(Iterable[Any], result.items()) for row in page]


@time_machine.travel("2026-03-10T12:00:00Z", tick=False)
@patch(f"{TRANSPORT}.PRODUCT_IDS_PER_REQUEST", 2)
@patch(f"{TRANSPORT}.REPORT_PAGE_SIZE", 2)
def test_traffic_products_batches_product_ids_and_walks_pages() -> None:
    def routes(path: str, params: dict[str, list[str]]) -> object:
        if path == "/v1/product-ids":
            return [{"_id": "p1"}, {"_id": "p2"}, {"_id": "p3"}]
        skip = int(params["skip"][0])
        if params["products"] == ["p1,p2"]:
            return [{"date": "2026-03-01", "productId": "p1", "n": skip + i} for i in range(2 if skip == 0 else 1)]
        return [{"date": "2026-03-01", "productId": "p3", "n": skip}] if skip == 0 else []

    requests: list[tuple[str, dict]] = []
    with patch("requests.adapters.HTTPAdapter.send", side_effect=routed_send(routes, requests)):
        rows = read_rows("traffic_products")

    assert [(row["productId"], row["n"]) for row in rows] == [("p1", 0), ("p1", 1), ("p1", 2), ("p3", 0)]
    report_params = {
        "start-date": ["2025-03-10"],
        "end-date": ["2026-03-10"],
        "group": ["day"],
        "sort": ["date,productId,categoryId"],
        "format": ["json"],
        "limit": ["2"],
    }
    assert requests == [
        ("/v1/product-ids", {}),
        ("/v1/reports/traffic/products", {**report_params, "products": ["p1,p2"], "skip": ["0"]}),
        ("/v1/reports/traffic/products", {**report_params, "products": ["p1,p2"], "skip": ["2"]}),
        # A short first page ends the batch without an extra request.
        ("/v1/reports/traffic/products", {**report_params, "products": ["p3"], "skip": ["0"]}),
    ]


@time_machine.travel("2026-03-10T12:00:00Z", tick=False)
def test_traffic_products_without_products_makes_no_report_request() -> None:
    requests: list[tuple[str, dict]] = []
    with patch("requests.adapters.HTTPAdapter.send", side_effect=routed_send(lambda path, params: [], requests)):
        assert read_rows("traffic_products") == []
    assert [path for path, _ in requests] == ["/v1/product-ids"]


@time_machine.travel("2026-03-10T12:00:00Z", tick=False)
@pytest.mark.parametrize(
    ("should_use_incremental_field", "last_value", "expected_start"),
    [
        (False, None, "2025-03-10"),
        (False, "2026-03-01", "2025-03-10"),
        (True, None, "2025-03-10"),
        (True, "2026-03-01", "2026-03-01"),
        (True, "2026-03-01T00:00:00.000Z", "2026-03-01"),
        (True, datetime(2026, 3, 2, 5, 30), "2026-03-02"),
        (True, date(2026, 3, 3), "2026-03-03"),
        (True, "2020-01-01", "2025-03-10"),
    ],
)
@pytest.mark.parametrize(
    ("endpoint", "path", "sort"),
    [
        ("visitor_insights_companies", "/v1/reports/visitor-insights/companies", "date,productId,companyName"),
        ("visitor_insights_pages", "/v1/reports/visitor-insights/pages", "date,productId,companyName,url"),
    ],
)
def test_visitor_insights_date_range_follows_sync_mode(
    endpoint: str, path: str, sort: str, should_use_incremental_field: bool, last_value: Any, expected_start: str
) -> None:
    row = {"date": "2026-03-05T00:00:00.000Z", "productId": "p1", "companyName": "Example Co", "url": "/x"}
    requests: list[tuple[str, dict]] = []
    with patch("requests.adapters.HTTPAdapter.send", side_effect=routed_send(lambda p, q: [row], requests)):
        rows = read_rows(endpoint, should_use_incremental_field=should_use_incremental_field, last_value=last_value)

    assert rows == [row]
    assert requests == [
        (
            path,
            {
                "start-date": [expected_start],
                "end-date": ["2026-03-10"],
                "group": ["day"],
                "sort": [sort],
                "format": ["json"],
                "skip": ["0"],
                "limit": ["1000"],
            },
        )
    ]


def days(first: str, count: int) -> list[str]:
    start = date.fromisoformat(first)
    return [(start + timedelta(days=offset)).isoformat() for offset in range(count)]


@time_machine.travel("2026-03-10T12:00:00Z", tick=False)
@pytest.mark.parametrize(
    ("should_use_incremental_field", "last_value", "expected_days"),
    [
        (True, "2026-03-07", days("2026-03-07", 3)),
        (True, date(2026, 3, 9), days("2026-03-09", 1)),
        (True, "2026-03-10", []),
        # The API serves 45 days back at most, and today is not complete yet.
        (True, "2025-12-01", days("2026-01-25", 44)),
        (False, "2026-03-07", days("2026-01-25", 44)),
    ],
)
def test_intent_requests_one_full_day_at_a_time(
    should_use_incremental_field: bool, last_value: Any, expected_days: list[str]
) -> None:
    requests: list[tuple[str, dict]] = []
    body = {"accounts": [], "more": False}
    with patch("requests.adapters.HTTPAdapter.send", side_effect=routed_send(lambda p, q: body, requests)):
        rows = read_rows("intent", should_use_incremental_field=should_use_incremental_field, last_value=last_value)

    assert rows == []
    assert requests == [
        ("/v1/intent", {"start-date": [day], "end-date": days(day, 2)[1:], "detailed": ["true"]})
        for day in expected_days
    ]


@time_machine.travel("2026-03-10T12:00:00Z", tick=False)
def test_intent_adds_the_day_to_each_account_and_warns_on_truncation() -> None:
    def routes(path: str, params: dict[str, list[str]]) -> object:
        if params["start-date"] == ["2026-03-08"]:
            return {"start_date": "2026-03-08", "accounts": [{"id": "a1", "visitorCount": 2}], "more": True}
        return {"start_date": params["start-date"][0], "accounts": [{"id": "a1", "visitorCount": 1}], "more": False}

    logger = MagicMock()
    requests: list[tuple[str, dict]] = []
    with patch("requests.adapters.HTTPAdapter.send", side_effect=routed_send(routes, requests)):
        rows = read_rows("intent", should_use_incremental_field=True, last_value="2026-03-08", logger=logger)

    assert rows == [
        {"id": "a1", "visitorCount": 2, "date": "2026-03-08"},
        {"id": "a1", "visitorCount": 1, "date": "2026-03-09"},
    ]
    logger.warning.assert_called_once_with("TrustRadius intent data for one day is incomplete", day="2026-03-08")


@time_machine.travel("2026-03-10T12:00:00Z", tick=False)
@pytest.mark.parametrize("body", [{"unexpected": []}, {"accounts": None}, []])
def test_intent_unexpected_response_shape_fails(body: object) -> None:
    with patch("requests.adapters.HTTPAdapter.send", return_value=response(body)) as send:
        with pytest.raises(ValueError, match="no accounts list"):
            read_rows("intent", should_use_incremental_field=True, last_value="2026-03-09")
    send.assert_called_once()


@pytest.mark.parametrize(
    "endpoint",
    ["products", "product_scores", "trustquotes", "tags", "visitor_insights_companies", "visitor_insights_pages"],
)
def test_unexpected_response_shape_fails_instead_of_erasing_table(endpoint: str) -> None:
    with patch("requests.adapters.HTTPAdapter.send", return_value=response({"unexpected": []})) as send:
        with pytest.raises(ValueError, match="Required"):
            list(cast(Iterable[Any], trustradius_source("example-secret", endpoint, 1, "test-job").items()))
    send.assert_called_once()


def test_unknown_endpoint_fails_before_request() -> None:
    with patch("requests.adapters.HTTPAdapter.send") as send:
        with pytest.raises(UnknownResourceError):
            trustradius_source("example-secret", "unknown", 1, "test-job")
    send.assert_not_called()
