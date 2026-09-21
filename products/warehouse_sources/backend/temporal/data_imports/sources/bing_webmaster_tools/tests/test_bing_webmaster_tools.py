import json
import datetime as dt
from typing import Any, Optional

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.bing_webmaster_tools import (
    BingWebmasterToolsError,
    _request,
    _stats_row,
    bing_webmaster_tools_source,
    get_rows,
    parse_site_urls,
    parse_wcf_date,
    select_site_urls,
    suggest_verified_site,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.settings import (
    BASE_URL,
    ENDPOINT_CONFIGS,
    ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.bing_webmaster_tools.bing_webmaster_tools"

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

    def test_unparseable_date_skips_row(self):
        item = {**_QUERY_STATS[0], "Date": "not-a-date"}

        assert _stats_row(item, "https://example.com/") is None

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

    def test_no_filter_selects_only_verified_sites(self):
        assert select_site_urls(_SITES, []) == ["https://example.com/"]

    @pytest.mark.parametrize(
        "filter_url",
        ["https://example.com/", "https://example.com", "HTTPS://EXAMPLE.COM/"],
    )
    def test_filter_matches_leniently_but_returns_registered_form(self, filter_url):
        assert select_site_urls(_SITES, [filter_url]) == ["https://example.com/"]

    def test_filter_matching_no_verified_site_raises(self):
        with pytest.raises(ValueError, match="not verified sites on the connected account"):
            select_site_urls(_SITES, ["http://unverified.example.org"])

    @pytest.mark.parametrize(
        "filter_url,expected",
        [
            # A bare hostname can never match Bing's scheme-prefixed site key, so it resolves to the
            # verified site sharing that host, with or without a trailing slash and regardless of case.
            ("example.com", "https://example.com/"),
            ("example.com/", "https://example.com/"),
            ("EXAMPLE.COM", "https://example.com/"),
            # An entry that already carries a scheme is matched exactly, so no suggestion is offered.
            ("https://example.com/", None),
            # A host that isn't verified has nothing to suggest.
            ("unknown.example.net", None),
        ],
    )
    def test_suggest_verified_site(self, filter_url, expected):
        assert suggest_verified_site(filter_url, ["https://example.com/"]) == expected

    def test_bare_hostname_error_names_the_verified_form(self):
        with pytest.raises(ValueError, match=r"'example.com' is verified as 'https://example.com/'"):
            select_site_urls(_SITES, ["example.com"])


class TestRequest:
    def test_returns_unwrapped_list(self):
        session = _session({"GetUserSites": _response(200, {"d": _SITES})})

        assert _request(session, "key", "GetUserSites") == _SITES

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
    def setup_method(self):
        self.logger = structlog.get_logger()

    def test_sites_rows_keep_only_url_and_verification(self):
        # Ownership-verification tokens must not reach the warehouse.
        session = _session({"GetUserSites": _response(200, {"d": _SITES})})

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("key", "sites", None, self.logger))

        assert batches == [
            [
                {"url": "https://example.com/", "is_verified": True},
                {"url": "http://unverified.example.org", "is_verified": False},
            ]
        ]

    def test_stats_fan_out_over_verified_sites_only(self):
        session = _session(
            {
                "GetUserSites": _response(200, {"d": _SITES}),
                "GetQueryStats": _response(200, {"d": _QUERY_STATS}),
            }
        )

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("key", "query_stats", None, self.logger))

        stats_calls = [call for call in session.get.call_args_list if "GetQueryStats" in call.args[0]]
        assert [call.kwargs["params"]["siteUrl"] for call in stats_calls] == ["https://example.com/"]
        assert batches == [
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

    def test_rows_with_unparseable_dates_are_dropped(self):
        bad_row = {**_QUERY_STATS[0], "Date": "garbage", "Query": "other"}
        session = _session(
            {
                "GetUserSites": _response(200, {"d": _SITES}),
                "GetQueryStats": _response(200, {"d": [*_QUERY_STATS, bad_row]}),
            }
        )

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("key", "query_stats", None, self.logger))

        assert [row["query"] for batch in batches for row in batch] == ["query"]


class TestValidateCredentials:
    def _validate(self, response: mock.MagicMock, site_urls: str | None = None) -> tuple[bool, str | None]:
        session = _session({"GetUserSites": response})
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            return validate_credentials("key", site_urls)

    def test_valid_key_with_verified_site(self):
        assert self._validate(_response(200, {"d": _SITES})) == (True, None)

    def test_invalid_api_key_fault_gives_key_guidance(self):
        ok, message = self._validate(_response(400, {"ErrorCode": 3, "Message": "InvalidApiKey"}))

        assert ok is False
        assert message is not None and "API access" in message

    def test_faultless_400_gives_key_guidance(self):
        ok, message = self._validate(_response(400, body=None, json_error=True))

        assert ok is False
        assert message is not None and "rejected the API key" in message

    def test_no_verified_sites_is_actionable(self):
        ok, message = self._validate(_response(200, {"d": [_SITES[1]]}))

        assert ok is False
        assert message is not None and "no verified sites" in message

    def test_filter_matching_nothing_is_actionable(self):
        ok, message = self._validate(_response(200, {"d": _SITES}), site_urls="https://other.example.net")

        assert ok is False
        assert message is not None and "not verified sites" in message

    def test_unreachable_api(self):
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            ok, message = validate_credentials("key", None)

        assert ok is False
        assert message is not None and "Could not reach" in message


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_primary_keys_match_endpoint_catalog(self, endpoint):
        response = bing_webmaster_tools_source("key", endpoint, None, structlog.get_logger())

        assert response.name == endpoint
        assert response.primary_keys == ENDPOINT_CONFIGS[endpoint].primary_keys
        # Bing documents no response ordering and the multi-site fan-out interleaves date ranges,
        # so no sort mode may be claimed: "asc" would checkpoint a corrupt incremental watermark.
        assert response.sort_mode is None

    def test_stats_tables_partition_on_date(self):
        response = bing_webmaster_tools_source("key", "query_stats", None, structlog.get_logger())

        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]

    def test_sites_table_has_no_partitioning(self):
        response = bing_webmaster_tools_source("key", "sites", None, structlog.get_logger())

        assert response.partition_mode is None
