import gzip
import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from freezegun import freeze_time
from unittest.mock import MagicMock, patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.app_store_connect.app_store_connect import (
    APP_STORE_CONNECT_ANALYTICS_CREATE_FORBIDDEN_ERROR,
    APP_STORE_CONNECT_ANALYTICS_INACTIVE_ERROR,
    APP_STORE_CONNECT_READ_FORBIDDEN_ERROR,
    BASE_URL,
    JWT_AUDIENCE,
    JWT_LIFETIME_SECONDS,
    AppStoreConnectAuthError,
    AppStoreConnectPermissionError,
    AppStoreConnectResumeConfig,
    AppStoreConnectTokenProvider,
    AppStoreConnectUrlError,
    _ensure_report_request,
    _find_analytics_report,
    _flatten_resource,
    _get,
    _normalize_private_key,
    _normalize_report_column,
    _Page,
    _parse_report,
    _ParseFailureCounter,
    _require_api_url,
    _typed_report_value,
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


def _page(
    resources: list[dict[str, Any]],
    next_url: str | None = None,
    included: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"data": resources, "meta": {"paging": {"total": len(resources)}}}
    if next_url:
        body["links"] = {"next": next_url}
    if included is not None:
        body["included"] = included
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
    logger: MagicMock | None = None,
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
            logger=logger if logger is not None else MagicMock(),
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


def _responded_review(review_id: str, response_id: str) -> dict[str, Any]:
    review = _resource("customerReviews", review_id, rating=5)
    review["relationships"]["response"] = {"data": {"type": "customerReviewResponses", "id": response_id}}
    return review


class TestReviewResponses:
    def _api(self) -> _FakeApi:
        reviews_url = f"{BASE_URL}/v1/apps/A1/customerReviews"
        return _FakeApi(
            {
                f"{BASE_URL}/v1/apps": _page([_resource("apps", "A1")]),
                reviews_url: _page(
                    [_responded_review("R1", "RESP1"), _responded_review("R2", "RESP2")],
                    included=[
                        _resource("customerReviewResponses", "RESP1", responseBody="thanks!", state="PUBLISHED"),
                        _resource("customerReviewResponses", "RESP2", responseBody="sorry!", state="PUBLISHED"),
                        # An included resource of another type (e.g. a review territory)
                        # must not leak into the responses table.
                        _resource("territories", "USA", currency="USD"),
                    ],
                ),
            }
        )

    def test_rows_come_from_included_responses_with_review_and_app_ids(self) -> None:
        rows = _collect("review_responses", self._api(), _FakeManager())

        assert [(row["app_id"], row["id"], row["review_id"], row["responseBody"]) for row in rows] == [
            ("A1", "RESP1", "R1", "thanks!"),
            ("A1", "RESP2", "R2", "sorry!"),
        ]

    def test_walk_requests_only_reviews_with_published_responses(self) -> None:
        # Dropping the include param loses every row; dropping the exists filter pages
        # through the full review history (mostly unresponded) on every sync.
        api = self._api()
        _collect("review_responses", api, _FakeManager())

        reviews_params = next(params for url, params in api.calls if url.endswith("/v1/apps/A1/customerReviews"))
        assert reviews_params["include"] == "response"
        assert reviews_params["exists[publishedResponse]"] == "true"

    def test_source_response_is_unpartitioned(self) -> None:
        # The only timestamp on a response is lastModifiedDate, which changes on edit;
        # partitioning on it would move rows between partitions.
        response = app_store_connect_source(
            issuer_id="issuer",
            key_id="KEY123",
            private_key=PRIVATE_KEY_PEM,
            vendor_number=None,
            endpoint="review_responses",
            logger=MagicMock(),
            resumable_source_manager=_FakeManager(),
        )
        assert response.primary_keys == ["app_id", "id"]
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestJsonApiDateTimeColumns:
    def test_iso_datetime_attributes_become_utc_datetimes(self) -> None:
        api = _FakeApi(
            {
                f"{BASE_URL}/v1/betaGroups": _page(
                    [
                        _resource("betaGroups", "1", name="Zulu", createdDate="2026-03-04T10:00:00Z"),
                        _resource("betaGroups", "2", name="Offset", createdDate="2026-03-04T12:30:00+02:00"),
                        _resource("betaGroups", "3", name="Fractional", createdDate="2026-03-04T10:00:00.123456-05:00"),
                    ]
                )
            }
        )

        rows = _collect("beta_groups", api, _FakeManager())

        # Apple emits varying local offsets; normalizing to UTC keeps one column in one zone.
        assert [row["createdDate"] for row in rows] == [
            datetime(2026, 3, 4, 10, 0, tzinfo=UTC),
            datetime(2026, 3, 4, 10, 30, tzinfo=UTC),
            datetime(2026, 3, 4, 15, 0, 0, 123456, tzinfo=UTC),
        ]
        assert [row["name"] for row in rows] == ["Zulu", "Offset", "Fractional"]

    def test_unparseable_datetime_is_nulled_rather_than_failing_the_sync(self) -> None:
        api = _FakeApi({f"{BASE_URL}/v1/betaGroups": _page([_resource("betaGroups", "1", createdDate="last Tuesday")])})

        rows = _collect("beta_groups", api, _FakeManager())

        assert rows[0]["createdDate"] is None
        assert rows[0]["id"] == "1"


APPS_URL = f"{BASE_URL}/v1/apps"
REQUESTS_URL = f"{BASE_URL}/v1/apps/A1/analyticsReportRequests"
CREATE_REQUEST_URL = f"{BASE_URL}/v1/analyticsReportRequests"
REPORTS_URL = f"{BASE_URL}/v1/analyticsReportRequests/REQ1/reports"
INSTANCES_URL = f"{BASE_URL}/v1/analyticsReports/REP1/instances"


def _segments_url(instance_id: str) -> str:
    return f"{BASE_URL}/v1/analyticsReportInstances/{instance_id}/segments"


def _gzip_csv(text: str) -> bytes:
    return gzip.compress(text.encode())


def _segment_response(content: bytes) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.ok = True
    response.iter_content.side_effect = lambda chunk_size: iter([content])
    return response


def _instance(instance_id: str, processing_date: str) -> dict[str, Any]:
    return _resource("analyticsReportInstances", instance_id, granularity="DAILY", processingDate=processing_date)


def _segment(segment_id: str, url: str, payload: bytes) -> dict[str, Any]:
    return _resource(
        "analyticsReportSegments",
        segment_id,
        checksum=hashlib.md5(payload).hexdigest(),
        sizeInBytes=len(payload),
        url=url,
    )


class _FakeAnalyticsApi(_FakeApi):
    """Extends _FakeApi with POST recording and presigned segment downloads served by URL."""

    def __init__(
        self,
        bodies: dict[str, dict[str, Any]],
        segment_payloads: dict[str, bytes] | None = None,
    ) -> None:
        super().__init__(bodies)
        self.segment_payloads = segment_payloads or {}
        self.posts: list[tuple[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> MagicMock:
        if url in self.segment_payloads:
            self.calls.append((url, None))
            return _segment_response(self.segment_payloads[url])
        return super().get(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> MagicMock:
        self.posts.append((url, kwargs.get("json")))
        body = {"data": {"type": "analyticsReportRequests", "id": "REQ-NEW", "attributes": {"accessType": "ONGOING"}}}
        return _json_response(body, status_code=201)


def _analytics_api(
    *,
    requests_page: list[dict[str, Any]] | None = None,
    reports: list[dict[str, Any]] | None = None,
    instances: list[dict[str, Any]] | None = None,
    segments_by_instance: dict[str, list[dict[str, Any]]] | None = None,
    segment_payloads: dict[str, bytes] | None = None,
) -> _FakeAnalyticsApi:
    bodies = {
        APPS_URL: _page([_resource("apps", "A1")]),
        REQUESTS_URL: _page(
            requests_page
            if requests_page is not None
            else [_resource("analyticsReportRequests", "REQ1", accessType="ONGOING", stoppedDueToInactivity=False)]
        ),
        REPORTS_URL: _page(
            reports
            if reports is not None
            else [_resource("analyticsReports", "REP1", name="App Sessions Standard", category="APP_USAGE")]
        ),
        INSTANCES_URL: _page(instances if instances is not None else []),
    }
    for instance_id, segment_resources in (segments_by_instance or {}).items():
        bodies[_segments_url(instance_id)] = _page(segment_resources)
    return _FakeAnalyticsApi(bodies, segment_payloads=segment_payloads)


def _collect_analytics(
    api: _FakeAnalyticsApi,
    manager: _FakeManager,
    endpoint: str = "analytics_app_sessions",
    **kwargs: Any,
) -> list[dict[str, Any]]:
    session = MagicMock()
    session.get.side_effect = api.get
    session.post.side_effect = api.post
    rows: list[dict[str, Any]] = []
    with (
        patch(f"{MODULE}._make_session", return_value=session),
        patch(f"{MODULE}._make_segment_download_session", return_value=session),
    ):
        for batch in get_rows(
            issuer_id="issuer",
            key_id="KEY123",
            private_key=PRIVATE_KEY_PEM,
            vendor_number=None,
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,
            **kwargs,
        ):
            rows.extend(batch)
    return rows


class TestAnalyticsReportStreams:
    def test_full_chain_parses_daily_instances_into_keyed_rows(self) -> None:
        segment_1 = _gzip_csv("Date,App Name,App Apple Identifier,Sessions\n2026-07-31,Example,123,5\n")
        segment_2 = _gzip_csv("Date,App Name,App Apple Identifier,Sessions\n2026-08-01,Example,123,7\n")
        segment_3 = _gzip_csv("Date,App Name,App Apple Identifier,Sessions\n2026-08-02,Example,123,2\n")
        api = _analytics_api(
            # Listed newest-first on purpose: the walk must process oldest-first anyway.
            instances=[_instance("I2", "2026-08-02"), _instance("I1", "2026-08-01")],
            segments_by_instance={
                "I1": [
                    _segment("S1a", "https://reports.example.s3.amazonaws.com/1a", segment_1),
                    _segment("S1b", "https://reports.example.s3.amazonaws.com/1b", segment_2),
                ],
                "I2": [_segment("S2", "https://reports.example.s3.amazonaws.com/2", segment_3)],
            },
            segment_payloads={
                "https://reports.example.s3.amazonaws.com/1a": segment_1,
                "https://reports.example.s3.amazonaws.com/1b": segment_2,
                "https://reports.example.s3.amazonaws.com/2": segment_3,
            },
        )
        manager = _FakeManager()

        rows = _collect_analytics(api, manager)

        # _line continues across an instance's segments; a restart per segment would give two
        # rows the same merge key and lose one of them.
        assert [(row["app_id"], row["processing_date"], row["_line"], row["sessions"]) for row in rows] == [
            ("A1", date(2026, 8, 1), 1, 5),
            ("A1", date(2026, 8, 1), 2, 7),
            ("A1", date(2026, 8, 2), 1, 2),
        ]
        assert rows[0]["app_apple_identifier"] == "123"
        assert api.posts == []

        params_by_url = dict(api.calls)
        assert params_by_url[REQUESTS_URL]["filter[accessType]"] == "ONGOING"
        assert params_by_url[REPORTS_URL]["filter[category]"] == "APP_USAGE"
        assert params_by_url[INSTANCES_URL]["filter[granularity]"] == "DAILY"

        assert [(state.app_id, state.processing_date) for state in manager.saved] == [
            (None, "2026-08-02"),
            (None, "2026-08-03"),
        ]

    def test_missing_request_is_created_once_and_the_app_skipped_this_run(self) -> None:
        api = _analytics_api(requests_page=[])

        rows = _collect_analytics(api, _FakeManager())

        assert rows == []
        assert [url for url, _ in api.posts] == [CREATE_REQUEST_URL]
        _, payload = api.posts[0]
        assert payload["data"]["attributes"]["accessType"] == "ONGOING"
        assert payload["data"]["relationships"]["app"]["data"] == {"type": "apps", "id": "A1"}
        # First reports generate in 1-2 days, so nothing further is polled for this app.
        assert REPORTS_URL not in [url for url, _ in api.calls]

    def test_request_stopped_due_to_inactivity_does_not_count_as_active(self) -> None:
        api = _analytics_api(
            requests_page=[
                _resource("analyticsReportRequests", "REQ1", accessType="ONGOING", stoppedDueToInactivity=True)
            ]
        )

        _collect_analytics(api, _FakeManager())

        assert [url for url, _ in api.posts] == [CREATE_REQUEST_URL]

    def test_incremental_walk_reads_from_the_watermark_day_inclusive(self) -> None:
        payload = _gzip_csv("Date,Sessions\n2026-08-02,5\n")
        api = _analytics_api(
            instances=[_instance("I1", "2026-08-01"), _instance("I2", "2026-08-02")],
            segments_by_instance={"I2": [_segment("S2", "https://r.s3.amazonaws.com/2", payload)]},
            segment_payloads={"https://r.s3.amazonaws.com/2": payload},
        )

        rows = _collect_analytics(
            api,
            _FakeManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 8, 2),
        )

        assert [row["processing_date"] for row in rows] == [date(2026, 8, 2)]
        assert _segments_url("I1") not in [url for url, _ in api.calls]

    def test_resume_bookmark_floors_the_walk(self) -> None:
        payload = _gzip_csv("Date,Sessions\n2026-08-02,5\n")
        api = _analytics_api(
            instances=[_instance("I1", "2026-08-01"), _instance("I2", "2026-08-02")],
            segments_by_instance={"I2": [_segment("S2", "https://r.s3.amazonaws.com/2", payload)]},
            segment_payloads={"https://r.s3.amazonaws.com/2": payload},
        )
        manager = _FakeManager(AppStoreConnectResumeConfig(processing_date="2026-08-02"))

        rows = _collect_analytics(api, manager)

        assert [row["processing_date"] for row in rows] == [date(2026, 8, 2)]
        assert _segments_url("I1") not in [url for url, _ in api.calls]

    def test_unavailable_report_degrades_the_table_without_failing(self) -> None:
        api = _analytics_api(
            reports=[_resource("analyticsReports", "REPX", name="Some Other Report", category="APP_USAGE")]
        )

        assert _collect_analytics(api, _FakeManager()) == []

    def test_instance_without_segments_stops_the_walk_at_that_date(self) -> None:
        # Emitting a later date past a not-ready gap would let the table watermark advance
        # beyond data that never landed.
        payload = _gzip_csv("Date,Sessions\n2026-08-02,5\n")
        api = _analytics_api(
            instances=[_instance("I1", "2026-08-01"), _instance("I2", "2026-08-02")],
            segments_by_instance={"I1": [], "I2": [_segment("S2", "https://r.s3.amazonaws.com/2", payload)]},
            segment_payloads={"https://r.s3.amazonaws.com/2": payload},
        )
        manager = _FakeManager()

        rows = _collect_analytics(api, manager)

        assert rows == []
        assert _segments_url("I2") not in [url for url, _ in api.calls]
        assert manager.saved[-1].processing_date == "2026-08-01"

    def test_checksum_mismatch_is_not_fatal(self) -> None:
        # The checksum algorithm is undocumented; a wrong guess must degrade to a warning,
        # not brick the table on every segment forever.
        payload = _gzip_csv("Date,Sessions\n2026-08-01,5\n")
        segment = _resource(
            "analyticsReportSegments",
            "S1",
            checksum="0000",
            sizeInBytes=len(payload),
            url="https://r.s3.amazonaws.com/1",
        )
        api = _analytics_api(
            instances=[_instance("I1", "2026-08-01")],
            segments_by_instance={"I1": [segment]},
            segment_payloads={"https://r.s3.amazonaws.com/1": payload},
        )

        assert len(_collect_analytics(api, _FakeManager())) == 1

    def test_off_host_segment_url_is_refused(self) -> None:
        payload = _gzip_csv("Date,Sessions\n2026-08-01,5\n")
        segment = _segment("S1", "https://attacker.example/steal", payload)
        api = _analytics_api(
            instances=[_instance("I1", "2026-08-01")],
            segments_by_instance={"I1": [segment]},
            segment_payloads={"https://attacker.example/steal": payload},
        )

        with pytest.raises(AppStoreConnectUrlError):
            _collect_analytics(api, _FakeManager())

    def test_tab_delimited_segments_parse_too(self) -> None:
        # Apple names the objects .csv.gz but its docs never state the delimiter, so both
        # must parse.
        payload = _gzip_csv("Date\tSessions\n2026-08-01\t5\n")
        api = _analytics_api(
            instances=[_instance("I1", "2026-08-01")],
            segments_by_instance={"I1": [_segment("S1", "https://r.s3.amazonaws.com/1", payload)]},
            segment_payloads={"https://r.s3.amazonaws.com/1": payload},
        )

        rows = _collect_analytics(api, _FakeManager())

        assert [(row["date"], row["sessions"]) for row in rows] == [(date(2026, 8, 1), 5)]

    def test_per_run_instance_cap_saves_a_resumable_bookmark(self) -> None:
        payload = _gzip_csv("Date,Sessions\n2026-08-01,5\n")
        api = _analytics_api(
            instances=[_instance("I1", "2026-08-01"), _instance("I2", "2026-08-02")],
            segments_by_instance={"I1": [_segment("S1", "https://r.s3.amazonaws.com/1", payload)]},
            segment_payloads={"https://r.s3.amazonaws.com/1": payload},
        )
        manager = _FakeManager()

        with patch(f"{MODULE}.ANALYTICS_MAX_INSTANCES_PER_RUN", 1):
            rows = _collect_analytics(api, manager)

        assert [row["processing_date"] for row in rows] == [date(2026, 8, 1)]
        assert manager.saved[-1].processing_date == "2026-08-02"

    def test_dates_walk_in_order_across_apps(self) -> None:
        # App-major order would yield app A1's newest dates before app A2's older ones, and
        # the per-batch ascending watermark checkpoint would then skip A2's backlog after a
        # crash. Date-major order is what makes the checkpoint safe.
        seg_1 = _gzip_csv("Date,Sessions\n2026-08-01,1\n")
        seg_2 = _gzip_csv("Date,Sessions\n2026-08-02,2\n")
        seg_3 = _gzip_csv("Date,Sessions\n2026-08-03,3\n")
        api = _analytics_api(
            instances=[_instance("I1", "2026-08-01"), _instance("I3", "2026-08-03")],
            segments_by_instance={
                "I1": [_segment("S1", "https://r.s3.amazonaws.com/1", seg_1)],
                "I2": [_segment("S2", "https://r.s3.amazonaws.com/2", seg_2)],
                "I3": [_segment("S3", "https://r.s3.amazonaws.com/3", seg_3)],
            },
            segment_payloads={
                "https://r.s3.amazonaws.com/1": seg_1,
                "https://r.s3.amazonaws.com/2": seg_2,
                "https://r.s3.amazonaws.com/3": seg_3,
            },
        )
        api.bodies[APPS_URL] = _page([_resource("apps", "A1"), _resource("apps", "A2")])
        api.bodies[f"{BASE_URL}/v1/apps/A2/analyticsReportRequests"] = _page(
            [_resource("analyticsReportRequests", "REQ2", accessType="ONGOING", stoppedDueToInactivity=False)]
        )
        api.bodies[f"{BASE_URL}/v1/analyticsReportRequests/REQ2/reports"] = _page(
            [_resource("analyticsReports", "REP2", name="App Sessions Standard", category="APP_USAGE")]
        )
        api.bodies[f"{BASE_URL}/v1/analyticsReports/REP2/instances"] = _page([_instance("I2", "2026-08-02")])

        rows = _collect_analytics(api, _FakeManager())

        assert [(row["app_id"], row["processing_date"]) for row in rows] == [
            ("A1", date(2026, 8, 1)),
            ("A2", date(2026, 8, 2)),
            ("A1", date(2026, 8, 3)),
        ]

    def test_columns_are_typed_by_name_and_attribution_columns_stay_text(self) -> None:
        # Typing is column-name-driven rather than per-endpoint: Apple publishes Standard and
        # Detailed variants of each report with differing column sets, so any stream carrying a
        # known date or metric column gets it typed, while the Detailed-only attribution columns
        # (campaign, page_title, source_info) stay text by omission from the mapping.
        payload = _gzip_csv(
            "Date,App Name,App Download Date,Campaign,Page Title,Source Info,"
            "Sessions,Total Session Duration,Unique Devices\n"
            "2026-08-01,Example,2026-07-15,summer-launch,Alternate page,com.example.social,5,321.5,4\n"
        )
        api = _analytics_api(
            instances=[_instance("I1", "2026-08-01")],
            segments_by_instance={"I1": [_segment("S1", "https://r.s3.amazonaws.com/1", payload)]},
            segment_payloads={"https://r.s3.amazonaws.com/1": payload},
        )

        row = _collect_analytics(api, _FakeManager())[0]

        assert row["processing_date"] == date(2026, 8, 1)
        assert row["date"] == date(2026, 8, 1)
        assert row["app_download_date"] == date(2026, 7, 15)
        assert row["sessions"] == 5 and isinstance(row["sessions"], int)
        assert row["total_session_duration"] == 321.5
        assert row["unique_devices"] == 4
        assert (row["campaign"], row["page_title"], row["source_info"]) == (
            "summer-launch",
            "Alternate page",
            "com.example.social",
        )
        assert row["app_name"] == "Example"

    def test_detailed_stream_syncs_rows_with_the_attribution_columns(self) -> None:
        payload = _gzip_csv(
            "Date,App Name,App Apple Identifier,Source Type,Source Info,Campaign,Page Type,Page Title,Sessions\n"
            "2026-08-01,Example,123,App referrer,com.example.social,summer-launch,Product page,Alternate page,5\n"
        )
        api = _analytics_api(
            reports=[_resource("analyticsReports", "REP1", name="App Sessions Detailed", category="APP_USAGE")],
            instances=[_instance("I1", "2026-08-01")],
            segments_by_instance={"I1": [_segment("S1", "https://r.s3.amazonaws.com/1", payload)]},
            segment_payloads={"https://r.s3.amazonaws.com/1": payload},
        )

        rows = _collect_analytics(api, _FakeManager(), endpoint="analytics_app_sessions_detailed")

        # The attribution headers exist only in Detailed files and must land as the three
        # documented snake_case columns. Metric columns are typed by name in every variant.
        assert [(row["campaign"], row["page_title"], row["source_info"], row["sessions"]) for row in rows] == [
            ("summer-launch", "Alternate page", "com.example.social", 5)
        ]

    def test_analytics_source_response_checkpoints_ascending(self) -> None:
        response = app_store_connect_source(
            issuer_id="issuer",
            key_id="KEY123",
            private_key=PRIVATE_KEY_PEM,
            vendor_number=None,
            endpoint="analytics_app_sessions",
            logger=MagicMock(),
            resumable_source_manager=_FakeManager(),
        )
        assert response.primary_keys == ["app_id", "processing_date", "_line"]
        assert response.partition_keys == ["processing_date"]
        # The walk is date-major across apps, so ascending per-batch checkpoints are safe.
        assert response.sort_mode == "asc"


class TestFindAnalyticsReport:
    def _resolve(self, endpoint: str, *apple_names: str) -> str | None:
        config = APP_STORE_CONNECT_ENDPOINTS[endpoint]
        page = _Page(
            resources=[
                _resource("analyticsReports", f"REP{index + 1}", name=name, category=config.analytics_report_category)
                for index, name in enumerate(apple_names)
            ],
            included=[],
            next_url=None,
        )
        with patch(f"{MODULE}._iter_pages", return_value=iter([page])):
            return _find_analytics_report(MagicMock(), MagicMock(), MagicMock(), config, "REQ1")

    @parameterized.expand(
        [
            ("analytics_app_store_downloads", "App Downloads Standard"),
            ("analytics_installations_deletions", "App Store Installation and Deletion Standard"),
            ("analytics_app_store_preorders", "App Store Pre-Orders Standard"),
        ]
    )
    def test_configured_names_resolve_the_report_apple_actually_returns(self, endpoint: str, apple_name: str) -> None:
        # These three streams asked for names Apple never returns, so the lookup resolved nothing and
        # the stream synced an empty table without failing. Fixtures elsewhere use "App Sessions
        # Standard", spelled the same here and at Apple, so they never exercised the mismatch.
        assert self._resolve(endpoint, apple_name) == "REP1"

    def test_match_tolerates_case_and_hyphen_drift(self) -> None:
        # Apple's casing of "Pre-Orders" has drifted before; normalization must resolve it without a
        # config change so a cosmetic rename can't silently blank the stream again.
        assert self._resolve("analytics_app_store_preorders", "App Store Pre-orders Standard") == "REP1"

    @parameterized.expand(
        [
            ("analytics_app_sessions", "analytics_app_sessions_detailed", "App Sessions"),
            ("analytics_app_store_downloads", "analytics_app_store_downloads_detailed", "App Downloads"),
            (
                "analytics_installations_deletions",
                "analytics_installations_deletions_detailed",
                "App Store Installation and Deletion",
            ),
            (
                "analytics_discovery_engagement",
                "analytics_discovery_engagement_detailed",
                "App Store Discovery and Engagement",
            ),
        ]
    )
    def test_standard_and_detailed_variants_resolve_their_own_reports(
        self, standard_endpoint: str, detailed_endpoint: str, base_name: str
    ) -> None:
        # Apple lists both variants of a report under the same request and category, so each config
        # picks from the same page. Resolving the sibling would silently fill one table with the
        # other variant's rows — for the detailed table, rows missing the attribution columns.
        variants = (f"{base_name} Standard", f"{base_name} Detailed")

        assert self._resolve(standard_endpoint, *variants) == "REP1"
        assert self._resolve(detailed_endpoint, *variants) == "REP2"


def _failures() -> _ParseFailureCounter:
    return _ParseFailureCounter(MagicMock(), "sales_reports")


class TestTypedReportValues:
    @parameterized.expand(
        [
            ("month_first_date", "begin_date", "03/04/2026", date(2026, 3, 4)),
            ("single_digit_month_and_day", "begin_date", "3/4/2026", date(2026, 3, 4)),
            ("iso_analytics_date", "date", "2026-03-04", date(2026, 3, 4)),
            # 02/03/2026 must read as February 3, never March 2: the parse is month-first by
            # Apple's report spec, independent of any locale or dayfirst heuristic.
            ("ambiguous_date_reads_month_first", "event_date", "02/03/2026", date(2026, 2, 3)),
            ("padded_date", "end_date", " 03/04/2026 ", date(2026, 3, 4)),
            ("count", "units", "3", 3),
            ("negative_refund_count", "units", "-2", -2),
            ("count_with_thousands_separator", "units", "1,234", 1234),
            ("whole_valued_float_count", "units", "3.0", 3),
            ("price", "customer_price", "0.99", 0.99),
            ("price_with_thousands_separator", "customer_price", "1,234.56", 1234.56),
            ("unmapped_column_untouched", "promo_code", "0099", "0099"),
            ("identifier_stays_text", "apple_identifier", "123456789", "123456789"),
        ]
    )
    def test_mapped_columns_parse_and_unmapped_stay_text(
        self, _name: str, column: str, value: str, expected: Any
    ) -> None:
        failures = _failures()

        parsed = _typed_report_value(column, value, failures)

        assert parsed == expected
        assert type(parsed) is type(expected)
        assert failures.counts == {}

    @parameterized.expand([("empty", "begin_date", ""), ("whitespace", "units", "  ")])
    def test_blank_cells_are_null_but_not_counted_as_failures(self, _name: str, column: str, value: str) -> None:
        failures = _failures()

        assert _typed_report_value(column, value, failures) is None
        assert failures.counts == {}

    @parameterized.expand(
        [
            # A heuristic parser would read 13/01/2026 as January 13 once the month overflows;
            # rejecting it keeps a mis-formatted file loud instead of silently day-first.
            ("day_first_date", "begin_date", "13/01/2026"),
            ("nonsense_date", "begin_date", "garbage"),
            ("out_of_range_date", "begin_date", "04/31/2026"),
            ("non_numeric_count", "units", "N/A"),
            ("fractional_count", "units", "2.5"),
            ("currency_prefixed_price", "customer_price", "USD 0.99"),
            ("non_finite_price", "customer_price", "inf"),
        ]
    )
    def test_unparseable_values_are_null_and_counted(self, _name: str, column: str, value: str) -> None:
        failures = _failures()

        assert _typed_report_value(column, value, failures) is None
        assert failures.counts == {column: 1}


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
    def test_gzipped_tsv_becomes_keyed_and_typed_rows(self) -> None:
        tsv = (
            "Provider\tSKU\tUnits\tCustomer Price\tDeveloper Proceeds\tBegin Date\tEnd Date\tApple Identifier\n"
            "APPLE\tacme-pro\t3\t2.99\t2.10\t03/04/2026\t03/04/2026\t123456789\n"
            "APPLE\tacme-lite\t1\t0.99\t0.70\t03/04/2026\t03/04/2026\t123456789\n"
        )

        rows = _parse_report(gzip.compress(tsv.encode()), date(2026, 3, 4), _failures())

        # Dates and quantities arrive typed; identifier-like numeric columns stay text because
        # they are join keys, not quantities.
        assert rows == [
            {
                "provider": "APPLE",
                "sku": "acme-pro",
                "units": 3,
                "customer_price": 2.99,
                "developer_proceeds": 2.10,
                "begin_date": date(2026, 3, 4),
                "end_date": date(2026, 3, 4),
                "apple_identifier": "123456789",
                "report_date": date(2026, 3, 4),
                "_line": 1,
            },
            {
                "provider": "APPLE",
                "sku": "acme-lite",
                "units": 1,
                "customer_price": 0.99,
                "developer_proceeds": 0.70,
                "begin_date": date(2026, 3, 4),
                "end_date": date(2026, 3, 4),
                "apple_identifier": "123456789",
                "report_date": date(2026, 3, 4),
                "_line": 2,
            },
        ]

    def test_blank_lines_are_skipped_so_line_numbers_stay_dense(self) -> None:
        tsv = "SKU\tUnits\nacme-pro\t3\n\n \nacme-lite\t1\n"

        rows = _parse_report(gzip.compress(tsv.encode()), date(2026, 3, 4), _failures())

        assert [(row["sku"], row["_line"]) for row in rows] == [("acme-pro", 1), ("acme-lite", 2)]

    def test_short_rows_are_padded_with_none(self) -> None:
        tsv = "SKU\tUnits\tDevice\nacme-pro\t3\n"

        rows = _parse_report(gzip.compress(tsv.encode()), date(2026, 3, 4), _failures())

        assert rows[0]["device"] is None

    def test_uncompressed_payload_is_parsed_too(self) -> None:
        # urllib3 unwraps a `Content-Encoding: gzip` body before we see it.
        rows = _parse_report(b"SKU\tUnits\nacme-pro\t3\n", date(2026, 3, 4), _failures())

        assert rows[0]["sku"] == "acme-pro"

    @parameterized.expand([("empty", b""), ("header_only", b"SKU\tUnits\n")])
    def test_reports_without_data_rows_yield_nothing(self, _name: str, payload: bytes) -> None:
        assert _parse_report(payload, date(2026, 3, 4), _failures()) == []


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
        assert [(row["report_date"], row["units"]) for row in rows] == [
            (date(2026, 3, 2), 1),
            (date(2026, 3, 4), 2),
        ]
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

        assert [(row["report_date"], row["units"]) for row in rows] == [(date(2026, 3, 4), 1)]
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
    def test_unparseable_values_are_nulled_with_counted_warnings(self) -> None:
        # Three bad units and one bad date must produce one first-occurrence warning per column
        # plus one end-of-run summary, never one log line per value.
        tsv = "SKU\tUnits\tBegin Date\nsku-1\tN/A\t03/04/2026\nsku-2\tN/A\t04/31/2026\nsku-3\tN/A\t03/04/2026\n"
        api = self._api({"2026-03-04": tsv})
        logger = MagicMock()

        rows = _collect(
            "sales_reports",
            api,
            _FakeManager(),
            vendor_number="85234567",
            logger=logger,
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 3, 4),
        )

        assert [row["units"] for row in rows] == [None, None, None]
        assert [row["begin_date"] for row in rows] == [date(2026, 3, 4), None, date(2026, 3, 4)]
        warning_messages = [call.args[0] for call in logger.warning.call_args_list]
        assert len(warning_messages) == 3
        assert "'units': 3" in warning_messages[-1]
        assert "'begin_date': 1" in warning_messages[-1]

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


def _forbidden_response(**fields: str) -> MagicMock:
    return _json_response({"errors": [fields]}, status_code=403)


class TestForbiddenErrors:
    def test_read_403_carries_apples_words_and_the_read_message(self) -> None:
        session = MagicMock()
        session.get.return_value = _forbidden_response(
            code="FORBIDDEN_ERROR", detail="The role of this API key cannot read this resource"
        )

        with pytest.raises(AppStoreConnectPermissionError) as exc:
            _get(session, f"{BASE_URL}/v1/salesReports", token_provider=_FakeTokenProvider(), logger=MagicMock())

        message = str(exc.value)
        assert APP_STORE_CONNECT_READ_FORBIDDEN_ERROR in message
        assert "FORBIDDEN_ERROR" in message
        assert "The role of this API key cannot read this resource" in message

    @parameterized.expand(
        [
            ("fresh_create", [], APP_STORE_CONNECT_ANALYTICS_CREATE_FORBIDDEN_ERROR),
            (
                "stopped_for_inactivity",
                [_resource("analyticsReportRequests", "REQ1", accessType="ONGOING", stoppedDueToInactivity=True)],
                APP_STORE_CONNECT_ANALYTICS_INACTIVE_ERROR,
            ),
        ]
    )
    def test_create_403_reports_the_create_role_not_a_read_role(
        self, _name: str, requests_page: list[dict[str, Any]], expected: str
    ) -> None:
        session = MagicMock()
        session.get.return_value = _json_response(_page(requests_page))
        session.post.return_value = _forbidden_response(code="FORBIDDEN_ERROR", detail="Admin role required")

        with pytest.raises(AppStoreConnectPermissionError) as exc:
            _ensure_report_request(session, _FakeTokenProvider(), MagicMock(), "A1")

        message = str(exc.value)
        assert expected in message
        # Apple's own words reach the raised message, and the create case never blames Finance or
        # Sales — the read roles the key demonstrably uses on the sales_reports table.
        assert "Admin role required" in message
        assert "Finance" not in message and "Sales" not in message
