import json
import datetime as dt
from typing import Any, Optional

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.bing_webmaster_tools import (
    BingWebmasterToolsError,
    _request,
    _stats_row,
    parse_site_urls,
    parse_wcf_date,
    select_site_urls,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.settings import BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.source import (
    BingWebmasterToolsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bingwebmastertools import (
    BingWebmasterToolsSourceConfig,
)

_SITES = [
    {
        "__type": "Site:#Microsoft.Bing.Webmaster.Api",
        "Url": "https://example.com/",
        "IsVerified": True,
        "AuthenticationCode": "258CAD36B9EEE22F1CFDEB4C239D26BB",
        "DnsVerificationCode": "258cad36b9eee22f1cfdeb4c239d26bb.example.com",
    },
    {
        "__type": "Site:#Microsoft.Bing.Webmaster.Api",
        "Url": "http://unverified.example.org",
        "IsVerified": False,
        "AuthenticationCode": "AAAA",
        "DnsVerificationCode": "aaaa.unverified.example.org",
    },
]

_QUERY_STATS = [
    {
        "__type": "QueryStats:#Microsoft.Bing.Webmaster.Api",
        "AvgClickPosition": 18,
        "AvgImpressionPosition": 17,
        "Clicks": 15,
        "Date": "/Date(1316156400000-0700)/",
        "Impressions": 100,
        "Query": "query",
    },
]


def _response(status: int = 200, body: Optional[Any] = None, json_error: bool = False) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    if json_error:
        resp.json.side_effect = ValueError("no json")
        resp.text = "<html>error</html>"
    else:
        resp.json.return_value = body
        resp.text = json.dumps(body)
    if not resp.ok:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error: Bad Request for url: {BASE_URL}/GetUserSites?apikey=super-secret-key",
            response=resp,
        )
    return resp


def _session(responses: dict[str, mock.MagicMock]) -> mock.MagicMock:
    """Fake tracked session routing by API method name in the request URL."""
    session = mock.MagicMock()

    def _get(url: str, params: Any = None, timeout: Any = None) -> mock.MagicMock:
        method = url.rsplit("/", 1)[-1]
        return responses[method]

    session.get.side_effect = _get
    return session


class TestParseWcfDate:
    @pytest.mark.parametrize(
        "value, expected",
        [
            # Doc sample: midnight Pacific serialized as UTC millis plus the local offset.
            ("/Date(1316156400000-0700)/", dt.date(2011, 9, 16)),
            # Without the offset the UTC calendar date is what the instant means.
            ("/Date(1316156400000)/", dt.date(2011, 9, 16)),
            # East-of-UTC offset pushes the local date past midnight; ignoring it would
            # yield the previous day.
            ("/Date(82800000+0200)/", dt.date(1970, 1, 2)),
        ],
    )
    def test_parses_wcf_dates(self, value, expected):
        assert parse_wcf_date(value) == expected

    @pytest.mark.parametrize(
        "value",
        ["2011-09-16", "", "/Date()/", "/Date(abc)/", None, 1316156400000, {"Date": "x"}],
    )
    def test_unparseable_returns_none(self, value):
        assert parse_wcf_date(value) is None


class TestStatsRow:
    def test_normalizes_keys_parses_date_and_stamps_site(self):
        row = _stats_row(_QUERY_STATS[0], "https://example.com/")

        assert row == {
            "avg_click_position": 18,
            "avg_impression_position": 17,
            "clicks": 15,
            "date": dt.date(2011, 9, 16),
            "impressions": 100,
            "query": "query",
            "site_url": "https://example.com/",
        }

    def test_missing_date_fails_loudly(self):
        item = {key: value for key, value in _QUERY_STATS[0].items() if key != "Date"}

        with pytest.raises(KeyError):
            _stats_row(item, "https://example.com/")


class TestSiteSelection:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, []),
            ("", []),
            ("  \n \n", []),
            ("https://example.com/", ["https://example.com/"]),
            ("https://a.com/\n\nhttps://b.com", ["https://a.com/", "https://b.com"]),
            # Duplicates (also with slash/case variance) are dropped so one site can't be
            # fanned out twice and seed duplicate primary keys within one sync.
            ("https://a.com/\nhttps://A.com", ["https://a.com/"]),
        ],
    )
    def test_parse_site_urls(self, raw, expected):
        assert parse_site_urls(raw) == expected

    def test_filter_matching_no_verified_site_raises(self):
        with pytest.raises(ValueError, match="not verified sites on the connected account"):
            select_site_urls(_SITES, ["http://unverified.example.org"])

    @pytest.mark.parametrize("filter_url", ["example.com", "example.com/", "EXAMPLE.COM"])
    def test_bare_hostname_resolves_to_the_verified_site(self, filter_url):
        # Bing lists sites with a scheme, so a hostname typed without one matches no site key even
        # though exactly one verified site carries that host.
        assert select_site_urls(_SITES, [filter_url]) == ["https://example.com/"]

    def test_two_spellings_of_one_site_are_not_synced_twice(self):
        assert select_site_urls(_SITES, ["example.com", "https://example.com/"]) == ["https://example.com/"]

    def test_ambiguous_bare_hostname_names_every_verified_form(self):
        # Both schemes are verified separately in Bing, so picking one would silently sync the
        # wrong site's stats.
        sites = [
            {"Url": "https://example.com/", "IsVerified": True},
            {"Url": "http://example.com/", "IsVerified": True},
        ]
        with pytest.raises(ValueError, match=r"'https://example.com/' and 'http://example.com/'"):
            select_site_urls(sites, ["example.com"])


class TestRequest:
    def test_api_fault_message_is_surfaced(self):
        session = _session({"GetUserSites": _response(400, {"ErrorCode": 3, "Message": "InvalidApiKey"})})

        with pytest.raises(BingWebmasterToolsError, match="InvalidApiKey"):
            _request(session, "key", "GetUserSites")

    def test_faultless_http_error_redacts_api_key(self):
        session = _session({"GetUserSites": _response(400, body=None, json_error=True)})

        with pytest.raises(requests.HTTPError) as exc_info:
            _request(session, "super-secret-key", "GetUserSites")

        assert "super-secret-key" not in str(exc_info.value)
        assert "apikey=REDACTED" in str(exc_info.value)

    @pytest.mark.parametrize("exc_type", [requests.ConnectionError, requests.ReadTimeout])
    def test_transport_error_redacts_api_key(self, exc_type):
        # Connection/timeout errors embed the request URL in their message; the stringified
        # error reaches logs and the schema's stored error, so the key must not survive.
        session = mock.MagicMock()
        session.get.side_effect = exc_type(
            "HTTPSConnectionPool(host='ssl.bing.com', port=443): Max retries exceeded with url: "
            "/webmaster/api.svc/json/GetUserSites?apikey=super-secret-key"
        )

        with pytest.raises(exc_type) as exc_info:
            _request(session, "super-secret-key", "GetUserSites")

        assert "super-secret-key" not in str(exc_info.value)
        assert "apikey=REDACTED" in str(exc_info.value)

    @pytest.mark.parametrize("body", [{"unexpected": True}, {"d": "not-a-list"}, [1, 2], None])
    def test_unexpected_response_shape_raises(self, body):
        session = _session({"GetUserSites": _response(200, body)})

        with pytest.raises(BingWebmasterToolsError, match="unexpected response shape"):
            _request(session, "key", "GetUserSites")


class TestGetRows:
    def _driver(self) -> SourceDriver:
        return SourceDriver(BingWebmasterToolsSource(), BingWebmasterToolsSourceConfig(api_key="key"))

    def test_sites_rows_keep_only_url_and_verification(self):
        # Ownership-verification tokens must not reach the warehouse.
        result = self._driver().run("sites", [ScriptedResponse(json={"d": _SITES})])

        assert result.raised is None
        assert result.items == [
            [
                {"url": "https://example.com/", "is_verified": True},
                {"url": "http://unverified.example.org", "is_verified": False},
            ]
        ]

    def test_stats_fan_out_over_verified_sites_only(self):
        result = self._driver().run(
            "query_stats",
            [ScriptedResponse(json={"d": _SITES}), ScriptedResponse(json={"d": _QUERY_STATS})],
        )

        assert result.raised is None
        assert result.paths == [
            "/webmaster/api.svc/json/GetUserSites",
            "/webmaster/api.svc/json/GetQueryStats",
        ]
        assert result.requests[1].param("siteUrl") == "https://example.com/"
        assert result.items == [
            [
                {
                    "avg_click_position": 18,
                    "avg_impression_position": 17,
                    "clicks": 15,
                    "date": dt.date(2011, 9, 16),
                    "impressions": 100,
                    "query": "query",
                    "site_url": "https://example.com/",
                }
            ]
        ]

    def test_page_query_stats_fan_out_over_distinct_top_pages(self):
        page_stats = [
            {**_QUERY_STATS[0], "Query": "https://example.com/a"},
            {**_QUERY_STATS[0], "Query": "https://example.com/a", "Date": "/Date(1316761200000-0700)/"},
            {**_QUERY_STATS[0], "Query": "https://example.com/b"},
        ]
        result = self._driver().run(
            "page_query_stats",
            [
                ScriptedResponse(json={"d": _SITES}),
                ScriptedResponse(json={"d": page_stats}),
                ScriptedResponse(json={"d": _QUERY_STATS}),
                ScriptedResponse(json={"d": []}),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/webmaster/api.svc/json/GetUserSites",
            "/webmaster/api.svc/json/GetPageStats",
            "/webmaster/api.svc/json/GetPageQueryStats",
            "/webmaster/api.svc/json/GetPageQueryStats",
        ]
        assert [r.param("page") for r in result.requests[2:]] == ['"https://example.com/a"', '"https://example.com/b"']
        assert [(row["page"], row["query"], row["site_url"]) for row in result.rows] == [
            ("https://example.com/a", "query", "https://example.com/")
        ]

    def test_page_query_stats_skips_a_page_bing_rejects_as_invalid(self):
        # GetPageStats and GetPageQueryStats can disagree about which pages are valid: Bing can
        # reject a page GetPageStats itself just listed. That page's stats should be skipped
        # without losing the other pages' data.
        page_stats = [
            {**_QUERY_STATS[0], "Query": "https://example.com/a"},
            {**_QUERY_STATS[0], "Query": "https://example.com/b"},
        ]
        result = self._driver().run(
            "page_query_stats",
            [
                ScriptedResponse(json={"d": _SITES}),
                ScriptedResponse(json={"d": page_stats}),
                ScriptedResponse(status=400, json={"ErrorCode": 38, "Message": "ERROR!!! InvalidUrl"}),
                ScriptedResponse(json={"d": _QUERY_STATS}),
            ],
        )

        assert result.raised is None
        assert [(row["page"], row["query"], row["site_url"]) for row in result.rows] == [
            ("https://example.com/b", "query", "https://example.com/")
        ]

    def test_link_counts_walk_every_page(self):
        def links_page(url: str) -> ScriptedResponse:
            return ScriptedResponse(
                json={
                    "d": {
                        "__type": "LinkCounts:#Microsoft.Bing.Webmaster.Api",
                        "Links": [{"__type": "LinkCount:#Microsoft.Bing.Webmaster.Api", "Count": 14, "Url": url}],
                        "TotalPages": 2,
                    }
                }
            )

        result = self._driver().run(
            "link_counts",
            [
                ScriptedResponse(json={"d": _SITES}),
                links_page("https://example.com/a"),
                links_page("https://example.com/b"),
            ],
        )

        assert result.raised is None
        assert [r.param("page") for r in result.requests[1:]] == ["0", "1"]
        assert result.rows == [
            {"count": 14, "url": "https://example.com/a", "site_url": "https://example.com/"},
            {"count": 14, "url": "https://example.com/b", "site_url": "https://example.com/"},
        ]

    def test_crawl_issues_rows_skip_entries_without_url(self):
        issues = [
            {
                "__type": "UrlWithCrawlIssues:#Microsoft.Bing.Webmaster.Api",
                "HttpCode": 200,
                "Issues": 32,
                "Url": "https://example.com/a",
                "InLinks": 10,
            },
            {
                "__type": "UrlWithCrawlIssues:#Microsoft.Bing.Webmaster.Api",
                "HttpCode": 404,
                "Issues": 4,
                "Url": None,
                "InLinks": 0,
            },
        ]
        result = self._driver().run(
            "crawl_issues", [ScriptedResponse(json={"d": _SITES}), ScriptedResponse(json={"d": issues})]
        )

        assert result.raised is None
        assert result.rows == [
            {
                "http_code": 200,
                "issues": 32,
                "url": "https://example.com/a",
                "in_links": 10,
                "site_url": "https://example.com/",
            }
        ]

    def test_rows_with_unparseable_dates_are_dropped(self):
        bad_row = {**_QUERY_STATS[0], "Date": "garbage", "Query": "other"}
        result = self._driver().run(
            "query_stats",
            [ScriptedResponse(json={"d": _SITES}), ScriptedResponse(json={"d": [*_QUERY_STATS, bad_row]})],
        )

        assert result.raised is None
        assert [row["query"] for row in result.rows] == ["query"]


class TestValidateCredentials:
    def _validate(self, response: ScriptedResponse, site_urls: str | None = None) -> tuple[bool, str | None]:
        with scripted_network([response]):
            return validate_credentials("key", site_urls)

    def test_valid_key_with_verified_site(self):
        assert self._validate(ScriptedResponse(json={"d": _SITES})) == (True, None)

    def test_invalid_api_key_fault_gives_key_guidance(self):
        ok, message = self._validate(ScriptedResponse(status=400, json={"ErrorCode": 3, "Message": "InvalidApiKey"}))

        assert ok is False
        assert message is not None and "API access" in message

    def test_faultless_400_gives_key_guidance(self):
        ok, message = self._validate(ScriptedResponse(status=400, body=b"<html>error</html>"))

        assert ok is False
        assert message is not None and "rejected the API key" in message

    def test_no_verified_sites_is_actionable(self):
        ok, message = self._validate(ScriptedResponse(json={"d": [_SITES[1]]}))

        assert ok is False
        assert message is not None and "no verified sites" in message

    def test_filter_matching_nothing_is_actionable(self):
        ok, message = self._validate(ScriptedResponse(json={"d": _SITES}), site_urls="https://other.example.net")

        assert ok is False
        assert message is not None and "not verified sites" in message
