import datetime as dt

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools import (
    bing_webmaster_tools as bwt,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.bing_webmaster_tools import (
    BingWebmasterToolsError,
    _crawl_row,
    _parse_ms_date,
    _rank_and_traffic_row,
    _request,
    _sorted_by_date,
    _traffic_row,
    bing_webmaster_tools_source,
    normalize_site_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bingwebmastertools import (
    BingWebmasterToolsSourceConfig,
)


def _config() -> BingWebmasterToolsSourceConfig:
    return BingWebmasterToolsSourceConfig(api_key="secret-key", site_url="https://example.com")


def _response(payload: object) -> mock.Mock:
    resp = mock.Mock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Epoch millis with a trailing timezone offset (Bing's usual shape).
        ("/Date(1399100400000-0700)/", dt.date(2014, 5, 3)),
        # Epoch millis without an offset.
        ("/Date(1316156400000)/", dt.date(2011, 9, 16)),
        # Unparseable inputs degrade to None rather than raising.
        ("not a date", None),
        (None, None),
        (1399100400000, None),
    ],
)
def test_parse_ms_date(raw, expected):
    assert _parse_ms_date(raw) == expected


def test_traffic_row_pins_metric_types():
    # Bing returns an exact-zero average position as a JSON int; coercing to float keeps the
    # stored Delta column type stable across days (the drift the GSC source also guards).
    row = _traffic_row(
        {
            "Query": "posthog",
            "Date": "/Date(1399100400000-0700)/",
            "Clicks": "2",
            "Impressions": 100,
            "AvgClickPosition": 0,
            "AvgImpressionPosition": 27,
        }
    )
    assert row == {
        "Query": "posthog",
        "Date": dt.date(2014, 5, 3),
        "Clicks": 2,
        "Impressions": 100,
        "AvgClickPosition": 0.0,
        "AvgImpressionPosition": 27.0,
    }
    assert isinstance(row["AvgClickPosition"], float)
    assert isinstance(row["Clicks"], int)


def test_rank_and_traffic_row_shape():
    row = _rank_and_traffic_row({"Date": "/Date(1399100400000-0700)/", "Clicks": 5, "Impressions": 900})
    assert row == {"Date": dt.date(2014, 5, 3), "Clicks": 5, "Impressions": 900}


def test_crawl_row_fills_missing_counters():
    # A sparse payload (Bing omits zero counters) still yields every declared column, defaulted to 0.
    row = _crawl_row({"Date": "/Date(1316156400000-0700)/", "CrawledPages": 10, "Code2xx": "9998"})
    assert row["Date"] == dt.date(2011, 9, 16)
    assert row["CrawledPages"] == 10
    assert row["Code2xx"] == 9998
    assert row["Code5xx"] == 0
    assert row["ContainsMalware"] == 0


def test_sorted_by_date_orders_ascending():
    rows = [
        {"Date": dt.date(2024, 3, 2)},
        {"Date": dt.date(2024, 3, 1)},
        {"Date": None},
    ]
    assert [r["Date"] for r in _sorted_by_date(rows)] == [None, dt.date(2024, 3, 1), dt.date(2024, 3, 2)]


def test_request_returns_d_array():
    session = mock.Mock()
    session.get.return_value = _response({"d": [{"Clicks": 1}]})
    assert _request(session, "GetRankAndTrafficStats", "k", {"siteUrl": "https://example.com"}) == [{"Clicks": 1}]
    # The API key rides in the query string alongside the other params.
    called_url = session.get.call_args.args[0]
    assert "apikey=k" in called_url
    assert "GetRankAndTrafficStats" in called_url


@pytest.mark.parametrize("payload", [{"d": None}, {"ErrorCode": 2, "Message": "bad"}, [1, 2, 3]])
def test_request_raises_on_fault(payload):
    session = mock.Mock()
    session.get.return_value = _response(payload)
    with pytest.raises(BingWebmasterToolsError):
        _request(session, "GetQueryStats", "k", {})


def test_request_propagates_http_error():
    session = mock.Mock()
    resp = mock.Mock()
    resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error")
    session.get.return_value = resp
    with pytest.raises(requests.HTTPError):
        _request(session, "GetQueryStats", "k", {})


def test_source_for_pipeline_shape_and_ordering():
    raw = [
        {"Query": "b", "Date": "/Date(1399186800000-0700)/", "Clicks": 1, "Impressions": 2},
        {"Query": "a", "Date": "/Date(1399100400000-0700)/", "Clicks": 3, "Impressions": 4},
    ]
    with mock.patch.object(bwt, "bing_session", return_value=mock.Mock()) as session_factory:
        with mock.patch.object(bwt, "_request", return_value=raw) as request:
            response = bing_webmaster_tools_source(_config(), "query_stats", team_id=1)
            batches = list(response.items())

    assert response.name == "query_stats"
    assert response.primary_keys == ["Query", "Date"]
    assert response.partition_mode == "datetime"
    assert response.partition_keys == ["Date"]
    assert response.sort_mode == "asc"
    # One batch, sorted oldest-first so the incremental watermark advances correctly.
    assert [row["Date"] for row in batches[0]] == [dt.date(2014, 5, 3), dt.date(2014, 5, 4)]
    session_factory.assert_called_once_with("secret-key")
    request.assert_called_once()
    assert request.call_args.args[1] == "GetQueryStats"


def test_source_for_pipeline_unknown_resource():
    with pytest.raises(ValueError):
        bing_webmaster_tools_source(_config(), "not_a_table", team_id=1)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("HTTPS://Example.com/", "https://example.com"),
        ("https://example.com", "https://example.com"),
        ("  http://Example.COM/  ", "http://example.com"),
        ("sc-domain:example.com", "sc-domain:example.com"),
    ],
)
def test_normalize_site_url(raw, expected):
    assert normalize_site_url(raw) == expected
