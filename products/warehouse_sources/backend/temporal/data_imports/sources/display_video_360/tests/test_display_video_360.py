import datetime as dt
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from django.test import override_settings

import requests
from google.oauth2.credentials import Credentials as OAuthCredentials

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import TrackedHTTPAdapter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.display_video_360 import display_video_360 as dv
from products.warehouse_sources.backend.temporal.data_imports.sources.display_video_360.display_video_360 import (
    DisplayVideo360CredentialsError,
    DisplayVideo360ReportError,
    DisplayVideo360ReportTimeoutError,
    DisplayVideo360ResumeConfig,
    display_video_360_source,
    format_update_time,
    normalize_report_column,
    parse_advertiser_ids,
    parse_report_csv,
    parse_report_date,
    parse_service_account_key,
    report_windows,
    resolve_report_start_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.display_video_360.settings import (
    DISPLAY_VIDEO_360_ENDPOINTS,
    REPORT_LOOKBACK_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.displayvideo360 import (
    DisplayVideo360AuthTypeConfig,
    DisplayVideo360SourceConfig,
)

SERVICE_ACCOUNT_KEY = '{"type": "service_account", "client_email": "sa@example.iam.gserviceaccount.com", "private_key": "-----BEGIN PRIVATE KEY-----"}'


def _service_account_config(**overrides: Any) -> DisplayVideo360SourceConfig:
    defaults: dict[str, Any] = {"partner_id": "1234", "advertiser_ids": None}
    defaults.update(overrides)
    return DisplayVideo360SourceConfig(
        auth_type=DisplayVideo360AuthTypeConfig(selection="service_account", service_account_key=SERVICE_ACCOUNT_KEY),
        **defaults,
    )


def _oauth_config(**auth_overrides: Any) -> DisplayVideo360SourceConfig:
    auth: dict[str, Any] = {"selection": "oauth", "display_video_360_integration_id": 42}
    auth.update(auth_overrides)
    return DisplayVideo360SourceConfig(
        auth_type=DisplayVideo360AuthTypeConfig(**auth), partner_id="1234", advertiser_ids=None
    )


def _integration(**token_overrides: Any) -> Integration:
    # Unsaved on purpose: the transport only reads the token fields off the row.
    tokens: dict[str, Any] = {"access_token": "access-token", "refresh_token": "refresh-token"}
    tokens.update(token_overrides)
    return Integration(kind="display-video-360", sensitive_config=tokens)


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        json_body: Any = None,
        text: str = "",
        url: str = "https://displayvideo.googleapis.com/v4/probe",
    ) -> None:
        self.status_code = status_code
        self._json_body = {} if json_body is None else json_body
        self.text = text
        self.url = url

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._json_body

    def raise_for_status(self) -> None:
        if not self.ok:
            kind = "Client Error" if self.status_code < 500 else "Server Error"
            raise requests.HTTPError(f"{self.status_code} {kind}: for url: {self.url}", response=cast(Any, self))

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def iter_content(self, chunk_size: int = 1) -> Iterable[bytes]:
        data = self.text.encode("utf-8")
        for start in range(0, len(data), chunk_size or len(data) or 1):
            yield data[start : start + (chunk_size or len(data) or 1)]


class FakeSession:
    """Stand-in for the authorized/tracked session, replaying queued responses in order."""

    def __init__(
        self, get_responses: list[FakeResponse] | None = None, post_responses: list[FakeResponse] | None = None
    ) -> None:
        self.get_responses = list(get_responses or [])
        self.post_responses = list(post_responses or [])
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.delete_calls: list[str] = []

    def get(self, url: str, timeout: Any = None, **kwargs: Any) -> FakeResponse:
        self.get_calls.append(url)
        return self.get_responses.pop(0)

    def post(self, url: str, json: Any = None, timeout: Any = None, **kwargs: Any) -> FakeResponse:
        self.post_calls.append((url, json or {}))
        return self.post_responses.pop(0)

    def delete(self, url: str, timeout: Any = None, **kwargs: Any) -> FakeResponse:
        self.delete_calls.append(url)
        return FakeResponse()


class FakeResumeManager(ResumableSourceManager[DisplayVideo360ResumeConfig]):
    def __init__(self, state: DisplayVideo360ResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[DisplayVideo360ResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> DisplayVideo360ResumeConfig | None:
        return self.state

    def save_state(self, data: DisplayVideo360ResumeConfig) -> None:
        self.saved.append(data)


def _rows(
    endpoint: str,
    session: FakeSession,
    manager: FakeResumeManager,
    config: DisplayVideo360SourceConfig | None = None,
    **kwargs: Any,
) -> list[list[dict[str, Any]]]:
    with mock.patch.object(dv, "display_video_360_session", return_value=session):
        return list(
            dv.get_rows(
                config=config or _service_account_config(),
                endpoint_name=endpoint,
                api_version="v4",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                **kwargs,
            )
        )


class TestServiceAccountKeyParsing:
    def test_valid_key_is_parsed(self) -> None:
        assert parse_service_account_key(SERVICE_ACCOUNT_KEY)["client_email"].endswith("gserviceaccount.com")

    @pytest.mark.parametrize(
        ("raw", "expected_fragment"),
        [
            (None, "empty"),
            ("", "empty"),
            ("   ", "empty"),
            ("not json", "not valid JSON"),
            ("[1, 2]", "JSON object"),
            ('{"client_email": "a"}', "private_key"),
            ('{"private_key": "a"}', "client_email"),
        ],
    )
    def test_unusable_keys_are_rejected(self, raw: str | None, expected_fragment: str) -> None:
        with pytest.raises(DisplayVideo360CredentialsError, match=expected_fragment):
            parse_service_account_key(raw)

    def test_custom_token_uri_is_rejected(self) -> None:
        # A tampered key pointing token_uri at an internal host is an SSRF vector via the JWT
        # refresh; it must be refused before any credential is built or request is made.
        raw = (
            '{"client_email": "sa@example.iam.gserviceaccount.com", "private_key": "-----BEGIN PRIVATE KEY-----", '
            '"token_uri": "http://169.254.169.254/token"}'
        )
        with pytest.raises(DisplayVideo360CredentialsError, match="token_uri"):
            parse_service_account_key(raw)

    def test_absent_token_uri_is_pinned_to_google(self) -> None:
        assert parse_service_account_key(SERVICE_ACCOUNT_KEY)["token_uri"] == dv.GOOGLE_TOKEN_URI


class TestCredentials:
    def test_oauth_credentials_come_from_the_connected_integration(self) -> None:
        with override_settings(
            DISPLAY_VIDEO_360_APP_CLIENT_ID="posthog-client-id",
            DISPLAY_VIDEO_360_APP_CLIENT_SECRET="posthog-client-secret",
        ):
            credentials = cast(OAuthCredentials, dv._credentials(_oauth_config(), _integration()))

        # The user never supplies a client: the refresh rides PostHog's registered OAuth app.
        assert credentials.refresh_token == "refresh-token"
        assert credentials.client_id == "posthog-client-id"
        assert credentials.client_secret == "posthog-client-secret"
        assert credentials.token_uri == dv.GOOGLE_TOKEN_URI
        # Pinning scopes on a refresh-token grant makes Google reject the refresh with
        # `invalid_scope` whenever the consent granted a different set.
        assert not credentials.scopes

    @pytest.mark.parametrize(
        "integration", [None, _integration(refresh_token=None), _integration(refresh_token="")], ids=str
    )
    def test_oauth_without_a_usable_integration_is_rejected(self, integration: Integration | None) -> None:
        with pytest.raises(DisplayVideo360CredentialsError, match="No Google account is connected"):
            dv._credentials(_oauth_config(), integration)

    def test_missing_auth_block_is_rejected(self) -> None:
        config = DisplayVideo360SourceConfig(auth_type=cast(Any, None), partner_id="1234", advertiser_ids=None)
        with pytest.raises(DisplayVideo360CredentialsError):
            dv._credentials(config)

    def test_secrets_are_redacted_from_the_transport(self) -> None:
        assert set(dv.redact_values(_oauth_config(), _integration())) == {"access-token", "refresh-token"}
        assert dv.redact_values(_service_account_config()) == (SERVICE_ACCOUNT_KEY,)

    def test_service_account_credentials_are_built_from_the_pinned_key(self) -> None:
        with mock.patch.object(dv.service_account.Credentials, "from_service_account_info") as from_info:
            credentials = dv._credentials(_service_account_config())

        assert credentials is from_info.return_value
        info, kwargs = from_info.call_args[0][0], from_info.call_args[1]
        # The key is the parsed one, so the token exchange stays pinned to Google.
        assert info["token_uri"] == dv.GOOGLE_TOKEN_URI
        assert info["client_email"] == "sa@example.iam.gserviceaccount.com"
        # Both APIs are needed: entity reads and Bid Manager reports.
        assert kwargs["scopes"] == list(dv.DISPLAY_VIDEO_SCOPES)

    @pytest.mark.parametrize(
        "error", [ValueError("bad key"), dv.GoogleAuthError("bad key")], ids=["value-error", "google-auth-error"]
    )
    def test_a_key_google_auth_refuses_is_reported_as_a_credentials_error(self, error: Exception) -> None:
        with mock.patch.object(dv.service_account.Credentials, "from_service_account_info", side_effect=error):
            with pytest.raises(DisplayVideo360CredentialsError, match="service account key could not be loaded"):
                dv._credentials(_service_account_config())


class TestSessions:
    def test_the_authorized_session_rides_the_tracked_adapter_on_both_schemes(self) -> None:
        with override_settings(
            DISPLAY_VIDEO_360_APP_CLIENT_ID="posthog-client-id",
            DISPLAY_VIDEO_360_APP_CLIENT_SECRET="posthog-client-secret",
        ):
            session = dv.display_video_360_session(_oauth_config(), _integration())

        assert isinstance(session, dv.AuthorizedSession)
        for scheme in ("https://", "http://"):
            adapter = session.adapters[scheme]
            assert isinstance(adapter, TrackedHTTPAdapter)
            # The refresh token must never reach a log line or a captured sample.
            assert "refresh-token" in adapter._redact_values

    def test_the_report_download_session_carries_no_credential(self) -> None:
        session = dv.report_download_session()

        # Bid Manager hands back a pre-signed Cloud Storage URL: sending the bearer token there
        # would leak it to a host that has no need for it.
        assert not isinstance(session, dv.AuthorizedSession)
        assert "Authorization" not in session.headers
        assert isinstance(session.adapters["https://"], TrackedHTTPAdapter)


class TestAdvertiserIds:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, []),
            ("", []),
            ("  ", []),
            ("123", ["123"]),
            ("2, 10 , 1", ["1", "2", "10"]),
            ("5\n7;9", ["5", "7", "9"]),
            ("4,4,4", ["4"]),
            ("abc,10", ["10", "abc"]),
        ],
    )
    def test_parse_advertiser_ids(self, raw: str | None, expected: list[str]) -> None:
        # Numeric ordering matters: the fan-out resume bookmark is an advertiser id, so the order
        # has to be identical across runs.
        assert parse_advertiser_ids(raw) == expected


class TestFormatUpdateTime:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (dt.datetime(2026, 3, 4, 2, 58, 14, tzinfo=dt.UTC), "2026-03-04T02:58:14Z"),
            (dt.datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (dt.date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ],
    )
    def test_format_update_time(self, value: Any, expected: str) -> None:
        assert format_update_time(value) == expected

    def test_offset_is_normalized_to_utc(self) -> None:
        aware = dt.datetime(2026, 3, 4, 12, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
        assert format_update_time(aware) == "2026-03-04T10:00:00Z"


class TestReportColumnNames:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Date", "date"),
            ("Advertiser ID", "advertiser_id"),
            ("  line  item  id ", "line_item_id"),
            ("Click Rate (CTR)", "click_rate"),
            ("Revenue (Adv Currency)", "revenue_advertiser_currency"),
            ("Some New Metric", "some_new_metric"),
            ("Weird/Label (x)", "weird_label_x"),
            ("", "column"),
        ],
    )
    def test_normalize_report_column(self, label: str, expected: str) -> None:
        assert normalize_report_column(label) == expected


class TestParseReportCsv:
    def test_data_rows_are_parsed_and_the_footer_is_dropped(self) -> None:
        csv_body = (
            "Date,Advertiser,Advertiser ID,Line Item ID,Impressions,Click Rate (CTR),Revenue (Adv Currency)\n"
            "2026/01/15,Acme,111,222,1000,0.05,12.34\n"
            "2026/01/16,Acme,111,222,2000,0.06,-\n"
            "\n"
            "Report Time:,2026/01/17 10:00\n"
            "Date Range:,2026/01/15 to 2026/01/16\n"
        )

        rows = parse_report_csv(csv_body)

        assert len(rows) == 2
        assert rows[0]["date"] == dt.date(2026, 1, 15)
        assert rows[0]["advertiser"] == "Acme"
        # Entity ids stay strings so they line up with the entity tables' ids.
        assert rows[0]["advertiser_id"] == "111"
        assert rows[0]["line_item_id"] == "222"
        # Every measure is a float so the Delta schema can't drift between report windows.
        assert rows[0]["impressions"] == 1000.0
        assert isinstance(rows[0]["impressions"], float)
        assert rows[0]["revenue_advertiser_currency"] == 12.34
        # "-" means the measure doesn't apply to the row.
        assert rows[1]["revenue_advertiser_currency"] is None

    def test_thousands_separators_are_parsed(self) -> None:
        rows = parse_report_csv('Date,Impressions\n2026-01-15,"1,234"\n')
        assert rows[0]["impressions"] == 1234.0

    def test_short_rows_pad_with_none(self) -> None:
        rows = parse_report_csv("Date,Advertiser ID,Impressions\n2026-01-15,111\n")
        assert rows[0]["impressions"] is None

    @pytest.mark.parametrize("body", ["", "\n"])
    def test_empty_body_yields_no_rows(self, body: str) -> None:
        assert parse_report_csv(body) == []

    def test_header_only_yields_no_rows(self) -> None:
        assert parse_report_csv("Date,Impressions\n") == []

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("2026/01/15", dt.date(2026, 1, 15)), ("2026-01-15", dt.date(2026, 1, 15)), ("not a date", None)],
    )
    def test_parse_report_date(self, value: str, expected: dt.date | None) -> None:
        assert parse_report_date(value) == expected


class TestReportWindows:
    @pytest.mark.parametrize(
        ("start", "end", "window_days", "expected"),
        [
            (dt.date(2026, 1, 1), dt.date(2026, 1, 1), 30, [(dt.date(2026, 1, 1), dt.date(2026, 1, 1))]),
            (dt.date(2026, 1, 2), dt.date(2026, 1, 1), 30, []),
            (
                dt.date(2026, 1, 1),
                dt.date(2026, 1, 5),
                2,
                [
                    (dt.date(2026, 1, 1), dt.date(2026, 1, 2)),
                    (dt.date(2026, 1, 3), dt.date(2026, 1, 4)),
                    (dt.date(2026, 1, 5), dt.date(2026, 1, 5)),
                ],
            ),
        ],
    )
    def test_windows_tile_the_range_without_gaps_or_overlap(
        self, start: dt.date, end: dt.date, window_days: int, expected: list[tuple[dt.date, dt.date]]
    ) -> None:
        assert report_windows(start, end, window_days) == expected


class TestResolveReportStartDate:
    TODAY = dt.date(2026, 6, 1)

    def test_first_sync_uses_the_lookback_window(self) -> None:
        assert resolve_report_start_date(self.TODAY, False, None) == self.TODAY - dt.timedelta(
            days=REPORT_LOOKBACK_DAYS
        )

    def test_incremental_off_ignores_a_stored_cursor(self) -> None:
        assert resolve_report_start_date(self.TODAY, False, dt.date(2026, 5, 20)) == self.TODAY - dt.timedelta(
            days=REPORT_LOOKBACK_DAYS
        )

    @pytest.mark.parametrize(
        "cursor",
        [dt.date(2026, 5, 20), dt.datetime(2026, 5, 20, 6, 0, tzinfo=dt.UTC), "2026-05-20", "2026-05-20T06:00:00Z"],
    )
    def test_incremental_resumes_from_the_cursor_day(self, cursor: Any) -> None:
        # Inclusive of the watermark day: DV360 restates recent days and merge dedupes.
        assert resolve_report_start_date(self.TODAY, True, cursor) == dt.date(2026, 5, 20)

    def test_unparseable_cursor_falls_back_to_the_lookback_window(self) -> None:
        assert resolve_report_start_date(self.TODAY, True, "garbage") == self.TODAY - dt.timedelta(
            days=REPORT_LOOKBACK_DAYS
        )

    def test_future_cursor_is_clamped_to_today(self) -> None:
        assert resolve_report_start_date(self.TODAY, True, dt.date(2027, 1, 1)) == self.TODAY


class TestReportRowBatching:
    def test_rows_are_yielded_grouped_by_ascending_date(self) -> None:
        rows: list[dict[str, Any]] = [
            {"date": dt.date(2026, 1, 3), "advertiser_id": "1"},
            {"date": dt.date(2026, 1, 1), "advertiser_id": "2"},
            {"date": dt.date(2026, 1, 1), "advertiser_id": "3"},
            {"date": None, "advertiser_id": "4"},
        ]

        batches = list(dv._report_row_batches(rows))

        # Batch order drives the incremental watermark, so it has to be date-ascending.
        assert [batch[0]["date"] for batch in batches] == [dt.date(2026, 1, 1), dt.date(2026, 1, 3), None]
        assert len(batches[0]) == 2


class TestEntityParams:
    def test_advertisers_are_scoped_to_the_partner(self) -> None:
        params = dv._entity_params(DISPLAY_VIDEO_360_ENDPOINTS["advertisers"], "1234", None)
        assert params["partnerId"] == "1234"
        assert params["orderBy"] == "updateTime"
        assert "filter" not in params

    def test_incremental_endpoints_filter_and_order_on_update_time(self) -> None:
        params = dv._entity_params(DISPLAY_VIDEO_360_ENDPOINTS["line_items"], "1234", "2026-01-01T00:00:00Z")
        assert params["orderBy"] == "updateTime"
        assert params["filter"] == 'updateTime>="2026-01-01T00:00:00Z"'

    @pytest.mark.parametrize("endpoint", ["partners", "creatives"])
    def test_full_refresh_endpoints_never_order_or_filter_on_update_time(self, endpoint: str) -> None:
        params = dv._entity_params(DISPLAY_VIDEO_360_ENDPOINTS[endpoint], "1234", "2026-01-01T00:00:00Z")
        assert "orderBy" not in params
        assert "filter" not in params


class TestPartnerScope:
    def test_only_the_configured_partner_is_read(self) -> None:
        # `partners.list` would return every partner the credential can see, which can reach outside
        # the connection's configured scope, so the table reads `partners/{partnerId}` instead.
        session = FakeSession(get_responses=[FakeResponse(json_body={"partnerId": "1234", "displayName": "Acme"})])

        batches = _rows("partners", session, FakeResumeManager())

        assert batches == [[{"partnerId": "1234", "displayName": "Acme"}]]
        assert session.get_calls == ["https://displayvideo.googleapis.com/v4/partners/1234"]

    def test_an_empty_partner_body_yields_nothing(self) -> None:
        session = FakeSession(get_responses=[FakeResponse(json_body={})])

        assert _rows("partners", session, FakeResumeManager()) == []

    @pytest.mark.parametrize("status", [401, 403, 404])
    def test_client_errors_bubble_up_for_non_retryable_matching(self, status: int) -> None:
        session = FakeSession(get_responses=[FakeResponse(status_code=status)])

        with pytest.raises(requests.HTTPError, match=f"{status} Client Error"):
            _rows("partners", session, FakeResumeManager())


class TestEntityPagination:
    def test_pagination_terminates_and_saves_state_after_each_page(self) -> None:
        session = FakeSession(
            get_responses=[
                FakeResponse(json_body={"advertisers": [{"advertiserId": "1"}], "nextPageToken": "tok-2"}),
                FakeResponse(json_body={"advertisers": [{"advertiserId": "2"}]}),
            ]
        )
        manager = FakeResumeManager()

        batches = _rows("advertisers", session, manager)

        assert [row["advertiserId"] for batch in batches for row in batch] == ["1", "2"]
        # Saved after yielding, so a crash re-yields the last page instead of skipping it.
        assert [state.page_token for state in manager.saved] == ["tok-2"]
        assert "pageToken=tok-2" in session.get_calls[1]
        assert len(session.get_calls) == 2

    def test_resume_starts_from_the_saved_page_token(self) -> None:
        session = FakeSession(get_responses=[FakeResponse(json_body={"advertisers": [{"advertiserId": "9"}]})])
        manager = FakeResumeManager(DisplayVideo360ResumeConfig(page_token="saved-token"))

        _rows("advertisers", session, manager)

        assert "pageToken=saved-token" in session.get_calls[0]

    def test_empty_page_is_not_yielded(self) -> None:
        session = FakeSession(get_responses=[FakeResponse(json_body={"advertisers": []})])

        assert _rows("advertisers", session, FakeResumeManager()) == []

    def test_non_dict_items_are_skipped(self) -> None:
        session = FakeSession(get_responses=[FakeResponse(json_body={"advertisers": [{"advertiserId": "1"}, "junk"]})])

        batches = _rows("advertisers", session, FakeResumeManager())

        assert batches == [[{"advertiserId": "1"}]]

    @pytest.mark.parametrize("status", [401, 403, 404])
    def test_client_errors_bubble_up_for_non_retryable_matching(self, status: int) -> None:
        session = FakeSession(get_responses=[FakeResponse(status_code=status)])

        with pytest.raises(requests.HTTPError, match=f"{status} Client Error"):
            _rows("advertisers", session, FakeResumeManager())


class TestAdvertiserFanOut:
    def _fan_out_session(self) -> FakeSession:
        return FakeSession(
            get_responses=[
                # Advertiser discovery.
                FakeResponse(json_body={"advertisers": [{"advertiserId": "20"}, {"advertiserId": "10"}]}),
                # Advertiser 10, two pages.
                FakeResponse(json_body={"lineItems": [{"lineItemId": "a"}], "nextPageToken": "tok"}),
                FakeResponse(json_body={"lineItems": [{"lineItemId": "b"}]}),
                # Advertiser 20, one page.
                FakeResponse(json_body={"lineItems": [{"lineItemId": "c", "advertiserId": "20"}]}),
            ]
        )

    def test_fan_out_visits_every_advertiser_and_stamps_the_parent_id(self) -> None:
        manager = FakeResumeManager()

        batches = _rows("line_items", self._fan_out_session(), manager)

        assert [(row["advertiserId"], row["lineItemId"]) for batch in batches for row in batch] == [
            ("10", "a"),
            ("10", "b"),
            ("20", "c"),
        ]
        assert [(s.advertiser_id, s.page_token) for s in manager.saved] == [
            ("10", "tok"),
            ("10", None),
            ("20", None),
        ]

    def test_configured_advertisers_are_read_after_checking_they_belong_to_the_partner(self) -> None:
        session = FakeSession(
            get_responses=[
                # The partner's advertisers, listed before any child request is made.
                FakeResponse(json_body={"advertisers": [{"advertiserId": "77"}, {"advertiserId": "88"}]}),
                FakeResponse(json_body={"lineItems": [{"lineItemId": "a"}]}),
            ]
        )

        batches = _rows("line_items", session, FakeResumeManager(), config=_service_account_config(advertiser_ids="77"))

        assert batches == [[{"advertiserId": "77", "lineItemId": "a"}]]
        # Only the configured advertiser is fanned out over — 88 is in the partner but not configured.
        child_calls = [url for url in session.get_calls if "lineItems" in url]
        assert len(child_calls) == 1
        assert child_calls[0].startswith("https://displayvideo.googleapis.com/v4/advertisers/77/lineItems?")

    def test_an_advertiser_outside_the_partner_is_refused_before_any_child_request(self) -> None:
        # `advertisers/{id}/...` is addressed by advertiser alone, so an ID belonging to another
        # partner the credential can reach would otherwise be read despite the configured scope.
        session = FakeSession(get_responses=[FakeResponse(json_body={"advertisers": [{"advertiserId": "77"}]})])

        with pytest.raises(dv.DisplayVideo360CredentialsError, match="not under Display & Video 360 partner 1234"):
            _rows("line_items", session, FakeResumeManager(), config=_service_account_config(advertiser_ids="77,99"))

        assert [url for url in session.get_calls if "lineItems" in url] == []

    def test_resume_skips_completed_advertisers_and_reuses_the_page_token(self) -> None:
        session = FakeSession(
            get_responses=[
                FakeResponse(json_body={"advertisers": [{"advertiserId": "10"}, {"advertiserId": "20"}]}),
                FakeResponse(json_body={"lineItems": [{"lineItemId": "c"}]}),
            ],
        )
        manager = FakeResumeManager(DisplayVideo360ResumeConfig(advertiser_id="20", page_token="tok"))

        batches = _rows("line_items", session, manager, config=_service_account_config(advertiser_ids="10,20"))

        child_calls = [url for url in session.get_calls if "lineItems" in url]
        assert len(child_calls) == 1
        assert "/advertisers/20/lineItems" in child_calls[0]
        assert "pageToken=tok" in child_calls[0]
        assert batches == [[{"advertiserId": "20", "lineItemId": "c"}]]

    def test_resume_on_an_advertiser_that_disappeared_restarts_the_fan_out(self) -> None:
        session = FakeSession(
            get_responses=[
                FakeResponse(json_body={"advertisers": [{"advertiserId": "10"}]}),
                FakeResponse(json_body={"lineItems": [{"lineItemId": "a"}]}),
            ]
        )
        manager = FakeResumeManager(DisplayVideo360ResumeConfig(advertiser_id="99", page_token="stale"))

        _rows("line_items", session, manager, config=_service_account_config(advertiser_ids="10"))

        first_child_call = next(url for url in session.get_calls if "lineItems" in url)
        assert "pageToken" not in first_child_call

    def test_incremental_cutoff_is_applied_to_every_advertiser(self) -> None:
        session = self._fan_out_session()

        _rows(
            "line_items",
            session,
            FakeResumeManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        )

        child_calls = [url for url in session.get_calls if "lineItems" in url]
        assert len(child_calls) == 3
        for url in child_calls:
            assert "filter=updateTime%3E%3D%222026-01-01T00%3A00%3A00Z%22" in url


class TestReportPipeline:
    CSV = "Date,Advertiser ID,Impressions\n2026-01-15,111,10\n"

    def _run_report_stream(
        self,
        poll_responses: list[FakeResponse],
        manager: FakeResumeManager | None = None,
        csv_body: str | None = None,
    ) -> tuple[list[list[dict[str, Any]]], FakeSession, FakeSession]:
        session = FakeSession(
            get_responses=poll_responses,
            post_responses=[
                FakeResponse(json_body={"queryId": "q-1"}),
                FakeResponse(json_body={"key": {"queryId": "q-1", "reportId": "r-1"}}),
            ],
        )
        download = FakeSession(get_responses=[FakeResponse(text=csv_body if csv_body is not None else self.CSV)])

        with (
            mock.patch.object(dv, "display_video_360_session", return_value=session),
            mock.patch.object(dv, "report_download_session", return_value=download),
            mock.patch.object(dv, "report_windows", return_value=[(dt.date(2026, 1, 15), dt.date(2026, 1, 16))]),
            mock.patch.object(dv.time, "sleep"),
        ):
            batches = list(
                dv.get_rows(
                    config=_service_account_config(advertiser_ids="111"),
                    endpoint_name="line_item_performance",
                    api_version="v4",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager or FakeResumeManager(),
                )
            )
        return batches, session, download

    def test_create_run_poll_download_and_cleanup(self) -> None:
        manager = FakeResumeManager()
        batches, session, download = self._run_report_stream(
            [
                FakeResponse(json_body={"metadata": {"status": {"state": "RUNNING"}}}),
                FakeResponse(
                    json_body={
                        "metadata": {
                            "status": {"state": "DONE"},
                            "googleCloudStoragePath": "https://storage.googleapis.com/report.csv",
                        }
                    }
                ),
            ],
            manager=manager,
        )

        create_url, create_body = session.post_calls[0]
        assert create_url.endswith("/v2/queries")
        assert create_body["params"]["groupBys"] == list(
            DISPLAY_VIDEO_360_ENDPOINTS["line_item_performance"].report_group_bys
        )
        assert create_body["schedule"]["frequency"] == "ONE_TIME"
        assert create_body["metadata"]["dataRange"]["customStartDate"] == {"year": 2026, "month": 1, "day": 15}
        assert {"type": "FILTER_PARTNER", "value": "1234"} in create_body["params"]["filters"]
        assert {"type": "FILTER_ADVERTISER", "value": "111"} in create_body["params"]["filters"]

        run_url, run_body = session.post_calls[1]
        assert run_url.endswith("/v2/queries/q-1:run?synchronous=false")
        assert run_body["dataRange"]["range"] == "CUSTOM_DATES"

        # Polled until DONE, then the pre-signed URL is fetched without credentials.
        assert len(session.get_calls) == 2
        assert download.get_calls == ["https://storage.googleapis.com/report.csv"]

        assert batches == [[{"date": dt.date(2026, 1, 15), "advertiser_id": "111", "impressions": 10.0}]]
        # The one-time query is always cleaned up.
        assert session.delete_calls == ["https://doubleclickbidmanager.googleapis.com/v2/queries/q-1"]
        # Resume bookmark points at the day after the finished window.
        assert [state.report_start_date for state in manager.saved] == ["2026-01-17"]

    def test_failed_report_raises_and_still_deletes_the_query(self) -> None:
        with pytest.raises(DisplayVideo360ReportError, match="failed"):
            self._run_report_stream([FakeResponse(json_body={"metadata": {"status": {"state": "FAILED"}}})])

    def test_done_without_a_storage_path_yields_no_rows(self) -> None:
        batches, _session, download = self._run_report_stream(
            [FakeResponse(json_body={"metadata": {"status": {"state": "DONE"}}})]
        )

        assert batches == []
        assert download.get_calls == []

    def test_poll_budget_exhaustion_is_retryable_at_the_activity_level(self) -> None:
        running = [
            FakeResponse(json_body={"metadata": {"status": {"state": "RUNNING"}}})
            for _ in range(dv.REPORT_POLL_MAX_ATTEMPTS)
        ]

        with pytest.raises(DisplayVideo360ReportTimeoutError):
            self._run_report_stream(running)

    def test_report_resumes_from_the_saved_window(self) -> None:
        manager = FakeResumeManager(DisplayVideo360ResumeConfig(report_start_date="2026-02-01"))
        session = FakeSession(
            get_responses=[
                FakeResponse(
                    json_body={
                        "metadata": {
                            "status": {"state": "DONE"},
                            "googleCloudStoragePath": "https://storage.googleapis.com/r.csv",
                        }
                    }
                )
            ],
            post_responses=[
                FakeResponse(json_body={"queryId": "q-1"}),
                FakeResponse(json_body={"key": {"reportId": "r-1"}}),
            ],
        )
        download = FakeSession(get_responses=[FakeResponse(text=self.CSV)])

        with (
            mock.patch.object(dv, "display_video_360_session", return_value=session),
            mock.patch.object(dv, "report_download_session", return_value=download),
            mock.patch.object(dv, "report_windows", return_value=[]) as windows,
            mock.patch.object(dv.time, "sleep"),
        ):
            list(
                dv.get_rows(
                    config=_service_account_config(),
                    endpoint_name="advertiser_performance",
                    api_version="v4",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        assert windows.call_args.args[0] == dt.date(2026, 2, 1)

    def test_missing_query_id_is_reported(self) -> None:
        session = FakeSession(post_responses=[FakeResponse(json_body={})])

        with (
            mock.patch.object(dv, "display_video_360_session", return_value=session),
            mock.patch.object(dv, "report_download_session", return_value=FakeSession()),
            mock.patch.object(dv, "report_windows", return_value=[(dt.date(2026, 1, 1), dt.date(2026, 1, 2))]),
        ):
            with pytest.raises(DisplayVideo360ReportError, match="query id"):
                list(
                    dv.get_rows(
                        config=_service_account_config(),
                        endpoint_name="advertiser_performance",
                        api_version="v4",
                        logger=mock.MagicMock(),
                        resumable_source_manager=FakeResumeManager(),
                    )
                )

    @pytest.mark.parametrize("path", ["http://storage.googleapis.com/r.csv", "file:///etc/passwd"])
    def test_non_https_report_paths_are_refused(self, path: str) -> None:
        with pytest.raises(DisplayVideo360ReportError, match="unexpected report path"):
            dv.download_report_rows(cast(Any, FakeSession()), path, mock.MagicMock())

    def test_oversized_report_download_is_refused(self) -> None:
        download = FakeSession(get_responses=[FakeResponse(text="x" * 1024)])
        with mock.patch.object(dv, "REPORT_MAX_DOWNLOAD_BYTES", 64):
            with pytest.raises(DisplayVideo360ReportError, match="download limit"):
                dv.download_report_rows(
                    cast(Any, download), "https://storage.googleapis.com/report.csv", mock.MagicMock()
                )

    def test_signed_url_is_scrubbed_from_error_logs(self) -> None:
        # A failed report download logs response.url, which is a replayable pre-signed URL.
        signed = "https://storage.googleapis.com/b/r.csv?X-Goog-Credential=sa&X-Goog-Signature=deadbeef"
        logger = mock.MagicMock()
        with pytest.raises(requests.HTTPError):
            dv._raise_for_status(cast(Any, FakeResponse(status_code=403, url=signed)), logger)
        logged = logger.error.call_args[0][0]
        assert "deadbeef" not in logged
        assert "X-Goog-Signature=REDACTED" in logged


class TestPostRetries:
    def test_transient_failures_are_retried_then_succeed(self) -> None:
        session = FakeSession(
            post_responses=[
                FakeResponse(status_code=429),
                FakeResponse(status_code=503),
                FakeResponse(json_body={"queryId": "q"}),
            ]
        )

        with mock.patch.object(dv.time, "sleep") as sleep:
            body = dv._post_json(cast(Any, session), "https://example.test/queries", {}, mock.MagicMock())

        assert body == {"queryId": "q"}
        assert sleep.call_count == 2

    def test_retry_budget_exhaustion_raises(self) -> None:
        session = FakeSession(post_responses=[FakeResponse(status_code=500) for _ in range(dv.POST_MAX_ATTEMPTS)])

        with mock.patch.object(dv.time, "sleep"):
            with pytest.raises(requests.HTTPError, match="500 Server Error"):
                dv._post_json(cast(Any, session), "https://example.test/queries", {}, mock.MagicMock())

    def test_client_errors_are_not_retried(self) -> None:
        session = FakeSession(post_responses=[FakeResponse(status_code=400)])

        with pytest.raises(requests.HTTPError, match="400 Client Error"):
            dv._post_json(cast(Any, session), "https://example.test/queries", {}, mock.MagicMock())


class TestValidateCredentials:
    def _validate(self, response: FakeResponse | Exception) -> tuple[bool, str | None]:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        with mock.patch.object(dv, "display_video_360_session", return_value=session):
            return validate_credentials(_service_account_config(), "v4")

    def test_reachable_partner_validates(self) -> None:
        assert self._validate(FakeResponse(json_body={"partnerId": "1234"})) == (True, None)

    @pytest.mark.parametrize(
        ("status", "expected_fragment"),
        [
            (401, "rejected the credentials"),
            (403, "Display & Video 360 user"),
            (404, "was not found"),
            (500, "status 500"),
        ],
    )
    def test_failures_map_to_actionable_messages(self, status: int, expected_fragment: str) -> None:
        is_valid, error = self._validate(FakeResponse(status_code=status))

        assert is_valid is False
        assert error is not None and expected_fragment in error

    def test_network_failures_are_reported(self) -> None:
        is_valid, error = self._validate(requests.ConnectionError("boom"))

        assert is_valid is False
        assert error is not None and "Could not reach" in error

    @pytest.mark.parametrize("partner_id", ["", "   "])
    def test_missing_partner_id_short_circuits(self, partner_id: str) -> None:
        is_valid, error = validate_credentials(_service_account_config(partner_id=partner_id), "v4")

        assert is_valid is False
        assert error is not None and "partner ID" in error

    def test_unusable_credentials_are_reported_without_a_request(self) -> None:
        is_valid, error = validate_credentials(_oauth_config(), "v4", None)

        assert is_valid is False
        assert error is not None and "No Google account is connected" in error

    def test_the_probe_uses_the_resolved_api_version(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = FakeResponse()
        with mock.patch.object(dv, "display_video_360_session", return_value=session):
            validate_credentials(_service_account_config(), "v3")

        assert session.get.call_args.args[0] == "https://displayvideo.googleapis.com/v3/partners/1234"


class TestSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "expected_primary_keys", "expected_sort_mode"),
        [
            ("partners", ["partnerId"], "asc"),
            ("advertisers", ["advertiserId"], "asc"),
            ("campaigns", ["advertiserId", "campaignId"], "desc"),
            ("insertion_orders", ["advertiserId", "insertionOrderId"], "desc"),
            ("line_items", ["advertiserId", "lineItemId"], "desc"),
            ("creatives", ["advertiserId", "creativeId"], "asc"),
            ("advertiser_performance", ["date", "advertiser_id"], "asc"),
            ("line_item_performance", ["date", "advertiser_id", "line_item_id"], "asc"),
        ],
    )
    def test_response_shape(self, endpoint: str, expected_primary_keys: list[str], expected_sort_mode: str) -> None:
        response = display_video_360_source(
            config=_service_account_config(),
            endpoint=endpoint,
            api_version="v4",
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        # Fan-out incremental endpoints report "desc" so the watermark is only persisted once the
        # whole sync finishes, instead of advancing past advertisers not yet visited.
        assert response.sort_mode == expected_sort_mode

    @pytest.mark.parametrize("endpoint", ["advertiser_performance", "line_item_performance"])
    def test_report_tables_partition_on_the_report_date(self, endpoint: str) -> None:
        response = display_video_360_source(
            config=_service_account_config(),
            endpoint=endpoint,
            api_version="v4",
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),
        )

        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["date"]

    @pytest.mark.parametrize("endpoint", ["partners", "line_items", "creatives"])
    def test_entity_tables_are_not_partitioned_on_a_mutable_field(self, endpoint: str) -> None:
        response = display_video_360_source(
            config=_service_account_config(),
            endpoint=endpoint,
            api_version="v4",
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),
        )

        assert response.partition_mode is None
        assert response.partition_keys is None

    def test_items_is_lazy(self) -> None:
        # Nothing may hit the network until the pipeline pulls the iterator.
        response = display_video_360_source(
            config=_service_account_config(),
            endpoint="partners",
            api_version="v4",
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),
        )

        session = FakeSession(get_responses=[FakeResponse(json_body={"partnerId": "1"})])
        with mock.patch.object(dv, "display_video_360_session", return_value=session):
            assert list(cast("Iterable[Any]", response.items())) == [[{"partnerId": "1"}]]
