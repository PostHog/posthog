import gzip
from datetime import date, timedelta
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.app_store_connect import (
    BASE_URL,
    JWT_AUDIENCE,
    JWT_LIFETIME_SECONDS,
    AppStoreConnectAuthError,
    AppStoreConnectResumeConfig,
    AppStoreConnectTokenProvider,
    AppStoreConnectUrlError,
    _flatten_resource,
    _get,
    _normalize_private_key,
    _normalize_report_column,
    _parse_report,
    _require_api_url,
    app_store_connect_source,
    check_credentials,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.settings import (
    APP_STORE_CONNECT_ENDPOINTS,
    ENDPOINTS,
    SALES_REPORT_LOOKBACK_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.app_store_connect"


def _make_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


PRIVATE_KEY_PEM = _make_pem()


class _FakeManager(ResumableSourceManager[AppStoreConnectResumeConfig]):
    """Minimal stand-in for ResumableSourceManager that records saved state in memory."""

    def __init__(self, state: AppStoreConnectResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[AppStoreConnectResumeConfig] = []
        self.cleared = 0

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> AppStoreConnectResumeConfig | None:
        return self._state

    def save_state(self, data: AppStoreConnectResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared += 1


class _FakeTokenProvider(AppStoreConnectTokenProvider):
    """Hands out a new token string every time a refresh is forced, so re-mints are observable."""

    def __init__(self) -> None:
        self.calls: list[bool] = []
        self._generation = 0

    def token(self, force_refresh: bool = False) -> str:
        self.calls.append(force_refresh)
        if force_refresh:
            self._generation += 1
        return f"token-{self._generation}"


def _json_response(body: dict[str, Any], status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = body
    response.text = ""
    return response


def _report_response(tsv: str | None, missing_status_code: int = 404) -> MagicMock:
    """A gzipped-TSV report response, or the 404 Apple returns for a date with no activity."""
    response = MagicMock()
    if tsv is None:
        response.status_code = missing_status_code
        response.ok = False
        response.text = '{"errors":[{"code":"NOT_FOUND"}]}'
        return response
    response.status_code = 200
    response.ok = True
    response.content = gzip.compress(tsv.encode())
    return response


def _resource(resource_type: str, resource_id: str, **attributes: Any) -> dict[str, Any]:
    return {
        "type": resource_type,
        "id": resource_id,
        "attributes": attributes,
        "relationships": {"app": {"links": {"related": "https://example.test"}}},
    }


def _page(resources: list[dict[str, Any]], next_url: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"data": resources, "meta": {"paging": {"total": len(resources)}}}
    if next_url:
        body["links"] = {"next": next_url}
    return body


class _FakeApi:
    """Routes JSON:API requests by URL to a canned body, recording every (url, params) pair."""

    def __init__(self, bodies: dict[str, dict[str, Any]]) -> None:
        self.bodies = bodies
        self.calls: list[tuple[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> MagicMock:
        self.calls.append((url, kwargs.get("params")))
        if url not in self.bodies:
            raise AssertionError(f"unexpected url {url}")
        return _json_response(self.bodies[url])


class _FakeReportApi:
    """Serves `/v1/salesReports` per requested report date; an unknown date 404s like Apple's does."""

    def __init__(self, tsv_by_date: dict[str, str], missing_status_code: int = 404) -> None:
        self.tsv_by_date = tsv_by_date
        self.missing_status_code = missing_status_code
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> MagicMock:
        params: dict[str, Any] = kwargs.get("params") or {}
        self.calls.append((url, params))
        return _report_response(self.tsv_by_date.get(params["filter[reportDate]"]), self.missing_status_code)


def _collect(
    endpoint: str,
    api: _FakeApi | _FakeReportApi,
    manager: _FakeManager,
    *,
    vendor_number: str | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    session = MagicMock()
    session.get.side_effect = api.get
    rows: list[dict[str, Any]] = []
    with patch(f"{MODULE}._make_session", return_value=session):
        for batch in get_rows(
            issuer_id="issuer",
            key_id="KEY123",
            private_key=PRIVATE_KEY_PEM,
            vendor_number=vendor_number,
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,
            **kwargs,
        ):
            rows.extend(batch)
    return rows


class TestNormalizePrivateKey:
    def test_pem_is_passed_through_unchanged(self) -> None:
        assert _normalize_private_key(f"\n  {PRIVATE_KEY_PEM}  \n") == PRIVATE_KEY_PEM.strip()

    def test_escaped_newlines_are_restored(self) -> None:
        flattened = PRIVATE_KEY_PEM.strip().replace("\n", "\\n")
        assert _normalize_private_key(flattened) == PRIVATE_KEY_PEM.strip()

    def test_bare_base64_body_is_wrapped_in_pem(self) -> None:
        body = "".join(line for line in PRIVATE_KEY_PEM.splitlines() if "-----" not in line)
        rebuilt = _normalize_private_key(body)
        assert rebuilt.startswith("-----BEGIN PRIVATE KEY-----\n")
        assert rebuilt.rstrip().endswith("-----END PRIVATE KEY-----")
        # A wrapped key must still be loadable, otherwise the convenience is a foot-gun.
        serialization.load_pem_private_key(rebuilt.encode(), password=None)

    @parameterized.expand([("empty", ""), ("whitespace", "   \n  ")])
    def test_missing_key_raises(self, _name: str, value: str) -> None:
        with pytest.raises(AppStoreConnectAuthError):
            _normalize_private_key(value)


class TestTokenProvider:
    def test_mints_es256_token_with_key_id_and_apple_claims(self) -> None:
        with freeze_time("2026-03-04 10:00:00"):
            token = AppStoreConnectTokenProvider("issuer-1", "KEY123", PRIVATE_KEY_PEM).token()

        header = jwt.get_unverified_header(token)
        claims = jwt.decode(token, options={"verify_signature": False})
        assert header["alg"] == "ES256"
        assert header["kid"] == "KEY123"
        assert claims["iss"] == "issuer-1"
        assert claims["aud"] == JWT_AUDIENCE
        # Apple rejects a token whose lifetime exceeds 20 minutes.
        assert claims["exp"] - claims["iat"] == JWT_LIFETIME_SECONDS
        assert claims["exp"] - claims["iat"] <= 1200

    def test_token_is_cached_until_it_nears_expiry(self) -> None:
        provider = AppStoreConnectTokenProvider("issuer-1", "KEY123", PRIVATE_KEY_PEM)
        with freeze_time("2026-03-04 10:00:00") as frozen:
            first = provider.token()
            frozen.tick(60)
            assert provider.token() == first
            # Past the refresh margin the provider mints a fresh token.
            frozen.tick(JWT_LIFETIME_SECONDS)
            assert provider.token() != first

    def test_force_refresh_mints_a_new_token(self) -> None:
        provider = AppStoreConnectTokenProvider("issuer-1", "KEY123", PRIVATE_KEY_PEM)
        with freeze_time("2026-03-04 10:00:00") as frozen:
            first = provider.token()
            frozen.tick(1)
            assert provider.token(force_refresh=True) != first

    def test_unusable_key_raises_auth_error(self) -> None:
        with pytest.raises(AppStoreConnectAuthError):
            AppStoreConnectTokenProvider("issuer-1", "KEY123", "not-a-key").token()


class TestGet:
    def test_401_forces_one_remint_and_retries(self) -> None:
        session = MagicMock()
        session.get.side_effect = [_json_response({}, status_code=401), _json_response({"data": []})]
        provider = _FakeTokenProvider()

        response = _get(session, f"{BASE_URL}/v1/apps", token_provider=provider, logger=MagicMock())

        assert response.status_code == 200
        assert provider.calls == [False, True]
        assert session.get.call_args_list[0].kwargs["headers"]["Authorization"] == "Bearer token-0"
        assert session.get.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer token-1"

    def test_persistent_401_raises(self) -> None:
        session = MagicMock()
        unauthorized = _json_response({}, status_code=401)
        unauthorized.raise_for_status.side_effect = Exception("401 Client Error: Unauthorized")
        session.get.side_effect = [unauthorized, unauthorized]

        with pytest.raises(Exception, match="401"):
            _get(session, f"{BASE_URL}/v1/apps", token_provider=_FakeTokenProvider(), logger=MagicMock())

    def test_tolerated_status_is_returned_without_raising(self) -> None:
        session = MagicMock()
        missing = _report_response(None)
        session.get.return_value = missing

        response = _get(
            session,
            f"{BASE_URL}/v1/salesReports",
            token_provider=_FakeTokenProvider(),
            logger=MagicMock(),
            tolerate=(404,),
        )

        assert response.status_code == 404
        missing.raise_for_status.assert_not_called()


class TestUrlPinning:
    @parameterized.expand(
        [
            ("base", BASE_URL),
            ("collection", f"{BASE_URL}/v1/apps"),
            ("pagination_cursor", f"{BASE_URL}/v1/apps?cursor=P2&limit=200"),
            ("explicit_default_port", f"https://{BASE_URL.split('//')[1]}:443/v1/apps"),
        ]
    )
    def test_apple_origin_urls_are_allowed(self, _name: str, url: str) -> None:
        assert _require_api_url(url) == url

    @parameterized.expand(
        [
            ("off_host", "https://evil.test/v1/apps"),
            ("look_alike_host", "https://api.appstoreconnect.apple.com.evil.test/v1/apps"),
            ("http_scheme", "http://api.appstoreconnect.apple.com/v1/apps"),
            ("non_default_port", "https://api.appstoreconnect.apple.com:8443/v1/apps"),
            ("scheme_relative", "//evil.test/v1/apps"),
        ]
    )
    def test_non_apple_urls_are_refused(self, _name: str, url: str) -> None:
        # A tampered `links.next` or a poisoned resume cursor could otherwise redirect a token-bearing
        # request off Apple's origin.
        with pytest.raises(AppStoreConnectUrlError):
            _require_api_url(url)

    def test_off_host_pagination_cursor_aborts_the_walk(self) -> None:
        # The pin runs inside `_get`, so an off-host `links.next` fails before the request is dispatched.
        api = _FakeApi(
            {f"{BASE_URL}/v1/apps": _page([_resource("apps", "1")], next_url="https://evil.test/v1/apps?cursor=P2")}
        )

        with pytest.raises(AppStoreConnectUrlError):
            _collect("apps", api, _FakeManager())

    def test_off_host_resume_url_is_refused(self) -> None:
        manager = _FakeManager(AppStoreConnectResumeConfig(next_url="https://evil.test/v1/apps?cursor=P9"))

        with pytest.raises(AppStoreConnectUrlError):
            _collect("apps", _FakeApi({}), manager)

    def test_unexpected_redirect_is_treated_as_a_failure(self) -> None:
        session = MagicMock()
        session.get.return_value = _json_response({}, status_code=302)

        with pytest.raises(AppStoreConnectUrlError):
            _get(session, f"{BASE_URL}/v1/apps", token_provider=_FakeTokenProvider(), logger=MagicMock())


class TestFlattenResource:
    def test_attributes_are_lifted_and_relationships_dropped(self) -> None:
        row = _flatten_resource(_resource("apps", "1234", name="Acme", bundleId="com.acme"))
        assert row == {"id": "1234", "type": "apps", "name": "Acme", "bundleId": "com.acme"}

    def test_missing_attributes_still_yields_identity(self) -> None:
        assert _flatten_resource({"id": "1", "type": "builds"}) == {"id": "1", "type": "builds"}


class TestCollectionEndpoints:
    def test_follows_links_next_until_absent(self) -> None:
        api = _FakeApi(
            {
                f"{BASE_URL}/v1/apps": _page(
                    [_resource("apps", "1", name="One")], next_url=f"{BASE_URL}/v1/apps?cursor=P2"
                ),
                f"{BASE_URL}/v1/apps?cursor=P2": _page([_resource("apps", "2", name="Two")]),
            }
        )
        manager = _FakeManager()

        rows = _collect("apps", api, manager)

        assert [row["id"] for row in rows] == ["1", "2"]
        # Page one carries the request params; the cursor URL is already fully formed, so re-sending
        # them would duplicate limit and cursor.
        assert api.calls[0][1] == {"limit": 200}
        assert api.calls[1][1] is None

    def test_saves_next_url_after_yielding_each_page(self) -> None:
        api = _FakeApi(
            {
                f"{BASE_URL}/v1/apps": _page([_resource("apps", "1")], next_url=f"{BASE_URL}/v1/apps?cursor=P2"),
                f"{BASE_URL}/v1/apps?cursor=P2": _page([_resource("apps", "2")]),
            }
        )
        manager = _FakeManager()

        _collect("apps", api, manager)

        assert [state.next_url for state in manager.saved] == [f"{BASE_URL}/v1/apps?cursor=P2"]

    def test_resumes_from_saved_next_url(self) -> None:
        api = _FakeApi({f"{BASE_URL}/v1/apps?cursor=P9": _page([_resource("apps", "9")])})
        manager = _FakeManager(AppStoreConnectResumeConfig(next_url=f"{BASE_URL}/v1/apps?cursor=P9"))

        rows = _collect("apps", api, manager)

        assert [row["id"] for row in rows] == ["9"]
        assert api.calls == [(f"{BASE_URL}/v1/apps?cursor=P9", None)]

    def test_checkpoint_is_cleared_once_the_walk_completes(self) -> None:
        api = _FakeApi({f"{BASE_URL}/v1/apps": _page([_resource("apps", "1")])})
        manager = _FakeManager()

        _collect("apps", api, manager)

        # A leftover checkpoint would resume a later attempt mid-stream instead of restarting cleanly.
        assert manager.cleared == 1

    def test_documented_sort_is_sent_for_builds(self) -> None:
        api = _FakeApi({f"{BASE_URL}/v1/builds": _page([_resource("builds", "1", version="42")])})

        _collect("builds", api, _FakeManager())

        assert api.calls[0][1] == {"sort": "uploadedDate", "limit": 200}


class TestAppFanoutEndpoints:
    def _api(self) -> _FakeApi:
        return _FakeApi(
            {
                f"{BASE_URL}/v1/apps": _page([_resource("apps", "A1"), _resource("apps", "A2")]),
                f"{BASE_URL}/v1/apps/A1/customerReviews": _page(
                    [_resource("customerReviews", "R1", rating=5)],
                    next_url=f"{BASE_URL}/v1/apps/A1/customerReviews?cursor=P2",
                ),
                f"{BASE_URL}/v1/apps/A1/customerReviews?cursor=P2": _page(
                    [_resource("customerReviews", "R2", rating=4)]
                ),
                f"{BASE_URL}/v1/apps/A2/customerReviews": _page([_resource("customerReviews", "R3", rating=1)]),
            }
        )

    def test_stamps_parent_app_id_on_every_row(self) -> None:
        rows = _collect("customer_reviews", self._api(), _FakeManager())

        assert [(row["app_id"], row["id"]) for row in rows] == [("A1", "R1"), ("A1", "R2"), ("A2", "R3")]

    def test_bookmark_tracks_page_then_advances_to_next_app(self) -> None:
        manager = _FakeManager()

        _collect("customer_reviews", self._api(), manager)

        assert [(state.app_id, state.next_url) for state in manager.saved] == [
            ("A1", f"{BASE_URL}/v1/apps/A1/customerReviews?cursor=P2"),
            ("A2", None),
        ]

    def test_resumes_mid_fanout_without_refetching_earlier_apps(self) -> None:
        api = self._api()
        manager = _FakeManager(
            AppStoreConnectResumeConfig(app_id="A1", next_url=f"{BASE_URL}/v1/apps/A1/customerReviews?cursor=P2")
        )

        rows = _collect("customer_reviews", api, manager)

        assert [(row["app_id"], row["id"]) for row in rows] == [("A1", "R2"), ("A2", "R3")]
        assert f"{BASE_URL}/v1/apps/A1/customerReviews" not in [url for url, _ in api.calls]

    def test_stale_bookmark_restarts_the_fanout(self) -> None:
        manager = _FakeManager(AppStoreConnectResumeConfig(app_id="DELETED", next_url="https://stale.test"))

        rows = _collect("customer_reviews", self._api(), manager)

        assert [row["id"] for row in rows] == ["R1", "R2", "R3"]


class TestReportColumnNames:
    @parameterized.expand(
        [
            ("spaces", "Developer Proceeds", "developer_proceeds"),
            ("acronym", "CMB", "cmb"),
            ("punctuation", "Provider Country", "provider_country"),
            ("parenthesis", "Units (Net)", "units_net"),
            ("dash", "Apple-Identifier", "apple_identifier"),
            ("padding", "  Begin Date  ", "begin_date"),
            ("unnamed", "  ", "column"),
        ]
    )
    def test_header_is_normalized_to_snake_case(self, _name: str, header: str, expected: str) -> None:
        assert _normalize_report_column(header) == expected


class TestParseReport:
    def test_gzipped_tsv_becomes_keyed_rows(self) -> None:
        tsv = "Provider\tSKU\tUnits\tDeveloper Proceeds\nAPPLE\tacme-pro\t3\t2.10\nAPPLE\tacme-lite\t1\t0.70\n"

        rows = _parse_report(gzip.compress(tsv.encode()), date(2026, 3, 4))

        assert rows == [
            {
                "provider": "APPLE",
                "sku": "acme-pro",
                "units": "3",
                "developer_proceeds": "2.10",
                "report_date": "2026-03-04",
                "_line": 1,
            },
            {
                "provider": "APPLE",
                "sku": "acme-lite",
                "units": "1",
                "developer_proceeds": "0.70",
                "report_date": "2026-03-04",
                "_line": 2,
            },
        ]

    def test_blank_lines_are_skipped_so_line_numbers_stay_dense(self) -> None:
        tsv = "SKU\tUnits\nacme-pro\t3\n\n \nacme-lite\t1\n"

        rows = _parse_report(gzip.compress(tsv.encode()), date(2026, 3, 4))

        assert [(row["sku"], row["_line"]) for row in rows] == [("acme-pro", 1), ("acme-lite", 2)]

    def test_short_rows_are_padded_with_none(self) -> None:
        tsv = "SKU\tUnits\tDevice\nacme-pro\t3\n"

        rows = _parse_report(gzip.compress(tsv.encode()), date(2026, 3, 4))

        assert rows[0]["device"] is None

    def test_uncompressed_payload_is_parsed_too(self) -> None:
        # urllib3 unwraps a `Content-Encoding: gzip` body before we see it.
        rows = _parse_report(b"SKU\tUnits\nacme-pro\t3\n", date(2026, 3, 4))

        assert rows[0]["sku"] == "acme-pro"

    @parameterized.expand([("empty", b""), ("header_only", b"SKU\tUnits\n")])
    def test_reports_without_data_rows_yield_nothing(self, _name: str, payload: bytes) -> None:
        assert _parse_report(payload, date(2026, 3, 4)) == []


class TestSalesReports:
    def _api(self, tsv_by_date: dict[str, str]) -> _FakeReportApi:
        return _FakeReportApi(tsv_by_date)

    def test_missing_vendor_number_fails_loudly(self) -> None:
        with pytest.raises(ValueError, match="vendor number"):
            _collect("sales_reports", _FakeApi({}), _FakeManager(), vendor_number=None)

    @freeze_time("2026-03-05 09:00:00")
    def test_walks_dates_forward_from_the_watermark_and_skips_empty_days(self) -> None:
        api = self._api({"2026-03-02": "SKU\tUnits\nacme\t1\n", "2026-03-04": "SKU\tUnits\nacme\t2\n"})

        rows = _collect(
            "sales_reports",
            api,
            _FakeManager(),
            vendor_number="85234567",
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 3, 2),
        )

        # Yesterday (2026-03-04) is the newest date Apple has published; 03-03 404s and is skipped.
        assert [(row["report_date"], row["units"]) for row in rows] == [("2026-03-02", "1"), ("2026-03-04", "2")]
        assert [params["filter[reportDate]"] for _, params in api.calls] == ["2026-03-02", "2026-03-03", "2026-03-04"]

    @freeze_time("2026-03-05 09:00:00")
    def test_subscription_report_tolerates_apples_misleading_400(self) -> None:
        # Apple 400s (instead of 404) a subscription-family report request for a date with no report
        # available yet — a documented Apple API quirk, not a real credentials failure. It must not
        # poison-pill the walk by raising on every retry of the same day.
        api = _FakeReportApi({"2026-03-04": "SKU\tUnits\nacme\t1\n"}, missing_status_code=400)

        rows = _collect(
            "subscription_reports",
            api,
            _FakeManager(),
            vendor_number="85234567",
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 3, 2),
        )

        assert [(row["report_date"], row["units"]) for row in rows] == [("2026-03-04", "1")]
        assert [params["filter[reportDate]"] for _, params in api.calls] == ["2026-03-02", "2026-03-03", "2026-03-04"]

    @freeze_time("2026-03-05 09:00:00")
    def test_sales_report_400_is_not_tolerated(self) -> None:
        # SALES reports don't carry the subscription-family quirk, so a 400 there is a real error and
        # must still surface rather than being silently treated as an empty day.
        session = MagicMock()
        bad_request = _report_response(None, missing_status_code=400)
        bad_request.raise_for_status.side_effect = Exception("400 Client Error: Bad Request")
        session.get.return_value = bad_request

        with patch(f"{MODULE}._make_session", return_value=session):
            with pytest.raises(Exception, match="400"):
                list(
                    get_rows(
                        issuer_id="issuer",
                        key_id="KEY123",
                        private_key=PRIVATE_KEY_PEM,
                        vendor_number="85234567",
                        endpoint="sales_reports",
                        logger=MagicMock(),
                        resumable_source_manager=_FakeManager(),
                    )
                )

    @freeze_time("2026-03-05 09:00:00")
    def test_sends_the_report_type_filters_from_settings(self) -> None:
        api = self._api({"2026-03-04": "SKU\tUnits\nacme\t1\n"})

        _collect(
            "subscription_event_reports",
            api,
            _FakeManager(),
            vendor_number="85234567",
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 3, 4),
        )

        _, params = api.calls[0]
        assert params["filter[reportType]"] == "SUBSCRIPTION_EVENT"
        assert params["filter[reportSubType]"] == "SUMMARY"
        assert params["filter[frequency]"] == "DAILY"
        assert params["filter[version]"] == "1_4"
        assert params["filter[vendorNumber]"] == "85234567"

    @freeze_time("2026-03-05 09:00:00")
    def test_first_sync_starts_one_retention_window_back(self) -> None:
        api = self._api({})

        _collect("sales_reports", api, _FakeManager(), vendor_number="85234567")

        first_requested = api.calls[0][1]["filter[reportDate]"]
        assert first_requested == (date(2026, 3, 5) - timedelta(days=SALES_REPORT_LOOKBACK_DAYS)).isoformat()

    @freeze_time("2026-03-05 09:00:00")
    def test_future_watermark_is_clamped_to_the_newest_published_date(self) -> None:
        api = self._api({})

        _collect(
            "sales_reports",
            api,
            _FakeManager(),
            vendor_number="85234567",
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2027, 1, 1),
        )

        assert [params["filter[reportDate]"] for _, params in api.calls] == ["2026-03-04"]

    @freeze_time("2026-03-05 09:00:00")
    def test_bookmark_advances_to_the_next_unfetched_date(self) -> None:
        api = self._api({"2026-03-02": "SKU\tUnits\nacme\t1\n"})
        manager = _FakeManager()

        _collect(
            "sales_reports",
            api,
            manager,
            vendor_number="85234567",
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 3, 2),
        )

        assert [state.report_date for state in manager.saved] == ["2026-03-03", "2026-03-04"]

    @freeze_time("2026-03-05 09:00:00")
    def test_resumes_from_the_saved_report_date(self) -> None:
        api = self._api({})
        manager = _FakeManager(AppStoreConnectResumeConfig(report_date="2026-03-04"))

        _collect(
            "sales_reports",
            api,
            manager,
            vendor_number="85234567",
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 3, 1),
        )

        assert [params["filter[reportDate]"] for _, params in api.calls] == ["2026-03-04"]

    @freeze_time("2026-03-05 09:00:00")
    def test_per_run_day_cap_stops_the_walk(self) -> None:
        api = self._api({})

        with patch(f"{MODULE}.SALES_REPORT_MAX_DAYS_PER_RUN", 2):
            _collect(
                "sales_reports",
                api,
                _FakeManager(),
                vendor_number="85234567",
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 3, 1),
            )

        assert [params["filter[reportDate]"] for _, params in api.calls] == ["2026-03-01", "2026-03-02"]


class TestCheckCredentials:
    @parameterized.expand([("ok", 200), ("unauthorized", 401), ("forbidden", 403), ("server_error", 500)])
    def test_returns_the_probe_status(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _json_response({}, status_code=status_code)

        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            status, message = check_credentials("issuer", "KEY123", PRIVATE_KEY_PEM)

        assert status == status_code
        assert message is None

    def test_unusable_key_reports_before_any_request(self) -> None:
        with patch(f"{MODULE}.make_tracked_session") as mocked:
            status, message = check_credentials("issuer", "KEY123", "not-a-key")

        assert status is None
        assert message is not None
        mocked.assert_not_called()

    def test_network_failure_reports_no_status(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")

        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            status, message = check_credentials("issuer", "KEY123", PRIVATE_KEY_PEM)

        assert status is None
        assert message is None


class TestSourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_response_matches_the_endpoint_catalog(self, endpoint: str) -> None:
        config = APP_STORE_CONNECT_ENDPOINTS[endpoint]

        response = app_store_connect_source(
            issuer_id="issuer",
            key_id="KEY123",
            private_key=PRIVATE_KEY_PEM,
            vendor_number="85234567",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None
