import contextlib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.google_admob._config import GoogleAdMobSourceConfig
from products.warehouse_sources.sources.google_admob.google_admob import (
    AdMobResumeConfig,
    account_name,
    shape_report_row,
    validate_credentials,
)
from products.warehouse_sources.sources.google_admob.settings import (
    AD_UNITS,
    ADMOB_REPORTS,
    APPS,
    MEDIATION_REPORT,
    NETWORK_REPORT,
)
from products.warehouse_sources.sources.google_admob.source import GoogleAdMobSource
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)

SOURCE_MODULE = "products.warehouse_sources.sources.google_admob.source"
TRANSPORT_MODULE = "products.warehouse_sources.sources.google_admob.google_admob"
FROZEN_NOW = "2026-03-15T12:00:00Z"
PUBLISHER_ID = "pub-1234567890"
ACCOUNT_PATH = f"/v1/accounts/{PUBLISHER_ID}"

# Google's error envelope, as the AdMob API sends it.
UNAUTHENTICATED_BODY = {
    "error": {
        "code": 401,
        "message": "Request had invalid authentication credentials. Expected OAuth 2 access token, login cookie or "
        "other valid authentication credential.",
        "status": "UNAUTHENTICATED",
    }
}
PERMISSION_DENIED_BODY = {
    "error": {"code": 403, "message": "The caller does not have permission", "status": "PERMISSION_DENIED"}
}
NOT_FOUND_BODY = {"error": {"code": 404, "message": "Requested entity was not found.", "status": "NOT_FOUND"}}


@contextlib.contextmanager
def _connected_account() -> Iterator[None]:
    """Stand in for the DB-backed integration that holds the Google access token."""
    integration = mock.MagicMock()
    integration.access_token = "access-token"
    integration.errors = ""
    oauth = mock.MagicMock()
    oauth.access_token_expired.return_value = False
    oauth.refresh_access_token.return_value = mock.MagicMock(access_token="fresh-token", errors="")
    with (
        mock.patch.object(GoogleAdMobSource, "get_oauth_integration", return_value=integration),
        mock.patch(f"{SOURCE_MODULE}.OauthIntegration", return_value=oauth),
    ):
        yield


def _driver(start_date: str | None = None) -> SourceDriver:
    config = GoogleAdMobSourceConfig(publisher_id=PUBLISHER_ID, google_admob_integration_id=1, start_date=start_date)
    return SourceDriver(GoogleAdMobSource(), config)


def _account() -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "name": f"accounts/{PUBLISHER_ID}",
            "publisherId": PUBLISHER_ID,
            "reportingTimeZone": "America/Los_Angeles",
            "currencyCode": "EUR",
        }
    )


def _network_row(day: str, ad_unit: str = "ca-app-pub-1234567890/111") -> dict[str, Any]:
    return {
        "row": {
            "dimensionValues": {
                "DATE": {"value": day},
                "APP": {"value": "ca-app-pub-1234567890~222", "displayLabel": "Puzzle game"},
                "AD_UNIT": {"value": ad_unit, "displayLabel": "Home banner"},
                "COUNTRY": {"value": "US"},
                "FORMAT": {"value": "BANNER"},
                "PLATFORM": {"value": "Android"},
            },
            "metricValues": {
                "AD_REQUESTS": {"integerValue": "1000"},
                "CLICKS": {"integerValue": "12"},
                "ESTIMATED_EARNINGS": {"microsValue": "6500000"},
                "IMPRESSIONS": {"integerValue": "900"},
                "IMPRESSION_CTR": {"doubleValue": 0.0133},
                "IMPRESSION_RPM": {"microsValue": "7222222"},
                "MATCHED_REQUESTS": {"integerValue": "950"},
                "MATCH_RATE": {"doubleValue": 0.95},
                "SHOW_RATE": {"doubleValue": 0.947},
            },
        }
    }


def _report(*rows: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(
        json=[
            {"header": {"reportingTimeZone": "America/Los_Angeles"}},
            *rows,
            {"footer": {"matchingRowCount": str(len(rows))}},
        ]
    )


def _report_script(report_answer: Any) -> Any:
    """Answer the account lookup, then every report request with `report_answer`."""

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.method == "GET" and request.path == ACCOUNT_PATH:
            return _account()
        return report_answer(request) if callable(report_answer) else report_answer

    return respond


def _date_ranges(requests: list[RecordedRequest]) -> list[tuple[str, str]]:
    ranges = []
    for request in requests:
        if request.method != "POST":
            continue
        date_range = request.json()["reportSpec"]["dateRange"]
        start, end = date_range["startDate"], date_range["endDate"]
        ranges.append(
            (
                f"{start['year']:04d}-{start['month']:02d}-{start['day']:02d}",
                f"{end['year']:04d}-{end['month']:02d}-{end['day']:02d}",
            )
        )
    return ranges


class TestAccountName:
    @parameterized.expand(
        [
            ("bare_id", "pub-123", "accounts/pub-123"),
            ("resource_name", "accounts/pub-123", "accounts/pub-123"),
            ("padded", "  pub-123/ ", "accounts/pub-123"),
        ]
    )
    def test_builds_resource_name(self, _name: str, publisher_id: str, expected: str) -> None:
        assert account_name(publisher_id) == expected


class TestShapeReportRow:
    def test_flattens_dimensions_labels_and_typed_metrics(self) -> None:
        row = shape_report_row(_network_row("20260301")["row"], ADMOB_REPORTS[NETWORK_REPORT], "EUR")

        assert row == {
            "date": datetime(2026, 3, 1, tzinfo=UTC),
            "app": "ca-app-pub-1234567890~222",
            "app_name": "Puzzle game",
            "ad_unit": "ca-app-pub-1234567890/111",
            "ad_unit_name": "Home banner",
            "country": "US",
            "format": "BANNER",
            "platform": "Android",
            "ad_requests": 1000,
            "clicks": 12,
            "estimated_earnings": 6.5,
            "estimated_earnings_micros": 6_500_000,
            "impressions": 900,
            "impression_ctr": 0.0133,
            "impression_rpm": 7.222222,
            "impression_rpm_micros": 7_222_222,
            "matched_requests": 950,
            "match_rate": 0.95,
            "show_rate": 0.947,
            "currency_code": "EUR",
        }

    def test_missing_values_keep_every_column(self) -> None:
        # AdMob leaves a metric out of the map when it has no value, and a dimension can be absent.
        row = shape_report_row(
            {"dimensionValues": {"DATE": {"value": "20260301"}}, "metricValues": {}},
            ADMOB_REPORTS[MEDIATION_REPORT],
            None,
        )

        assert row["ad_source"] == ""
        assert row["ad_source_name"] is None
        assert row["mediation_group"] == ""
        assert row["observed_ecpm"] is None
        assert row["observed_ecpm_micros"] is None
        assert row["clicks"] is None
        assert row["match_rate"] is None
        # Every primary key column is present and never null.
        assert all(row[key] is not None for key in ADMOB_REPORTS[MEDIATION_REPORT].primary_keys)


class TestReportSync:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel(FROZEN_NOW, tick=False):
            yield

    @pytest.fixture(autouse=True)
    def _account(self):
        with _connected_account():
            yield

    def test_walks_thirty_day_windows_up_to_yesterday(self) -> None:
        result = _driver(start_date="2026-01-01").run(NETWORK_REPORT, _report_script(_report(_network_row("20260301"))))

        assert result.raised is None
        assert _date_ranges(result.requests) == [
            ("2026-01-01", "2026-01-30"),
            ("2026-01-31", "2026-03-01"),
            ("2026-03-02", "2026-03-14"),
        ]
        spec = next(r for r in result.requests if r.method == "POST").json()["reportSpec"]
        assert spec["dimensions"] == ["DATE", "APP", "AD_UNIT", "COUNTRY", "FORMAT", "PLATFORM"]
        assert "AD_TYPE" not in spec["dimensions"]
        assert spec["maxReportRows"] == 100_000
        assert {r.path for r in result.requests if r.method == "POST"} == {f"{ACCOUNT_PATH}/networkReport:generate"}
        assert result.requests[0].headers["authorization"] == "Bearer access-token"
        assert {row["currency_code"] for row in result.rows} == {"EUR"}
        assert result.response is not None
        assert result.response.primary_keys == ["date", "app", "ad_unit", "country", "format", "platform"]

    def test_mediation_report_posts_to_its_own_method(self) -> None:
        result = _driver(start_date="2026-03-14").run(MEDIATION_REPORT, _report_script(_report()))

        assert result.raised is None
        post = next(r for r in result.requests if r.method == "POST")
        assert post.path == f"{ACCOUNT_PATH}/mediationReport:generate"
        assert "AD_SOURCE" in post.json()["reportSpec"]["dimensions"]

    @parameterized.expand(
        [
            ("incremental_uses_watermark", True, "2026-03-10", "2026-03-10"),
            ("incremental_without_watermark_uses_start_date", True, None, "2026-03-01"),
            ("full_refresh_ignores_watermark", False, "2026-03-10", "2026-03-01"),
        ]
    )
    def test_first_requested_day(
        self, _name: str, incremental: bool, watermark: str | None, expected_start: str
    ) -> None:
        result = _driver(start_date="2026-03-01").run(
            NETWORK_REPORT,
            _report_script(_report()),
            incremental_field="date",
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert _date_ranges(result.requests)[0] == (expected_start, "2026-03-14")

    def test_default_start_is_one_year_back(self) -> None:
        result = _driver().run(NETWORK_REPORT, _report_script(_report()))

        assert _date_ranges(result.requests)[0][0] == "2025-03-15"

    def test_truncated_window_is_halved_and_the_smaller_window_kept(self) -> None:
        def answer(request: RecordedRequest) -> ScriptedResponse:
            start = request.json()["reportSpec"]["dateRange"]["startDate"]
            end = request.json()["reportSpec"]["dateRange"]["endDate"]
            span = (
                datetime(end["year"], end["month"], end["day"]) - datetime(start["year"], start["month"], start["day"])
            ).days + 1
            # More than four days of data hits the (patched) row limit.
            if span > 4:
                return _report(_network_row("20260301", "a"), _network_row("20260301", "b"))
            return _report(_network_row("20260301", "a"))

        with mock.patch(f"{TRANSPORT_MODULE}.MAX_REPORT_ROWS", 2):
            result = _driver(start_date="2026-03-01").run(NETWORK_REPORT, _report_script(answer))

        assert result.raised is None
        assert _date_ranges(result.requests) == [
            ("2026-03-01", "2026-03-14"),
            ("2026-03-01", "2026-03-07"),
            ("2026-03-01", "2026-03-03"),
            ("2026-03-04", "2026-03-06"),
            ("2026-03-07", "2026-03-09"),
            ("2026-03-10", "2026-03-12"),
            ("2026-03-13", "2026-03-14"),
        ]
        # Only the windows under the limit are kept.
        assert len(result.rows) == 5

    def test_resumes_from_saved_state_instead_of_the_start_date(self) -> None:
        result = _driver(start_date="2026-01-01").run(
            NETWORK_REPORT,
            _report_script(_report()),
            resume_state=AdMobResumeConfig(next_start_date="2026-03-10"),
        )

        assert _date_ranges(result.requests) == [("2026-03-10", "2026-03-14")]

    def test_cursor_is_saved_before_the_window_it_covers_is_yielded(self) -> None:
        result = _driver(start_date="2026-01-01").run(NETWORK_REPORT, _report_script(_report(_network_row("20260101"))))

        assert result.raised is None
        assert result.committed_states[:3] == [
            AdMobResumeConfig(next_start_date="2026-01-31"),
            AdMobResumeConfig(next_start_date="2026-03-02"),
            AdMobResumeConfig(next_start_date="2026-03-15"),
        ]
        assert result.final_state is None

    def test_rejected_token_is_refreshed_once_mid_sync(self) -> None:
        answers = iter([ScriptedResponse(status=401, json=UNAUTHENTICATED_BODY), _report()])

        result = _driver(start_date="2026-03-14").run(NETWORK_REPORT, _report_script(lambda _r: next(answers)))

        assert result.raised is None
        posts = [r for r in result.requests if r.method == "POST"]
        assert [r.headers["authorization"] for r in posts] == ["Bearer access-token", "Bearer fresh-token"]

    @parameterized.expand(
        [
            ("forbidden", 403, PERMISSION_DENIED_BODY, "403 Client Error"),
            ("not_found", 404, NOT_FOUND_BODY, "404 Client Error"),
        ]
    )
    def test_report_errors_raise_with_the_status(self, _name: str, status: int, body: Any, fragment: str) -> None:
        result = _driver(start_date="2026-03-14").run(
            NETWORK_REPORT, _report_script(ScriptedResponse(status=status, json=body))
        )

        assert fragment in str(result.raised)
        assert "https://admob.googleapis.com" in str(result.raised)


class TestListSync:
    @pytest.fixture(autouse=True)
    def _account(self):
        with _connected_account():
            yield

    def test_apps_walks_pages_until_no_token(self) -> None:
        script = route(
            {
                f"{ACCOUNT_PATH}/apps": [
                    ScriptedResponse(
                        json={
                            "apps": [
                                {
                                    "name": f"accounts/{PUBLISHER_ID}/apps/1",
                                    "appId": "ca-app-pub-1234567890~1",
                                    "platform": "ANDROID",
                                    "manualAppInfo": {"displayName": "Puzzle game"},
                                    "linkedAppInfo": {"appStoreId": "com.example.puzzle", "displayName": "Puzzle"},
                                    "appApprovalState": "APPROVED",
                                }
                            ],
                            "nextPageToken": "page-2",
                        }
                    ),
                    ScriptedResponse(json={"apps": [{"appId": "ca-app-pub-1234567890~2", "platform": "IOS"}]}),
                ]
            }
        )

        result = _driver().run(APPS, script)

        assert result.raised is None
        assert result.params("pageToken") == [None, "page-2"]
        assert set(result.params("pageSize")) == {"10000"}
        assert result.rows[0] == {
            "name": f"accounts/{PUBLISHER_ID}/apps/1",
            "app_id": "ca-app-pub-1234567890~1",
            "platform": "ANDROID",
            "manual_app_info_display_name": "Puzzle game",
            "linked_app_info_app_store_id": "com.example.puzzle",
            "linked_app_info_display_name": "Puzzle",
            "app_approval_state": "APPROVED",
        }
        assert [row["app_id"] for row in result.rows] == ["ca-app-pub-1234567890~1", "ca-app-pub-1234567890~2"]
        assert result.response is not None
        assert result.response.primary_keys == ["app_id"]

    def test_ad_units_reads_the_ad_units_key(self) -> None:
        script = route(
            {
                f"{ACCOUNT_PATH}/adUnits": [
                    ScriptedResponse(
                        json={
                            "adUnits": [
                                {
                                    "adUnitId": "ca-app-pub-1234567890/111",
                                    "appId": "ca-app-pub-1234567890~1",
                                    "displayName": "Home banner",
                                    "adFormat": "BANNER",
                                    "adTypes": ["RICH_MEDIA", "VIDEO"],
                                }
                            ]
                        }
                    )
                ]
            }
        )

        result = _driver().run(AD_UNITS, script)

        assert result.raised is None
        assert result.rows == [
            {
                "ad_unit_id": "ca-app-pub-1234567890/111",
                "app_id": "ca-app-pub-1234567890~1",
                "display_name": "Home banner",
                "ad_format": "BANNER",
                "ad_types": ["RICH_MEDIA", "VIDEO"],
            }
        ]

    def test_empty_account_syncs_nothing(self) -> None:
        result = _driver().run(APPS, route({f"{ACCOUNT_PATH}/apps": [ScriptedResponse(json={})]}))

        assert result.raised is None
        assert result.rows == []


class TestValidateCredentials:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel(FROZEN_NOW, tick=False):
            yield

    def test_valid_credentials_read_the_account(self) -> None:
        with scripted_network([_account()]) as network:
            assert validate_credentials("access-token", PUBLISHER_ID) == (True, None)

        assert [r.path for r in network.requests_log] == [ACCOUNT_PATH]

    @parameterized.expand(
        [
            ("unauthenticated", 401, UNAUTHENTICATED_BODY, "reconnect the Google account"),
            ("permission_denied", 403, PERMISSION_DENIED_BODY, "cannot read this AdMob account"),
            ("not_found", 404, NOT_FOUND_BODY, "cannot read this AdMob account"),
        ]
    )
    def test_errors_map_to_actionable_messages(self, _name: str, status: int, body: Any, fragment: str) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json=body))):
            ok, message = validate_credentials("access-token", PUBLISHER_ID)

        assert ok is False
        assert message is not None and fragment in message

    @parameterized.expand(
        [
            ("bad_format", "03/01/2026", "Invalid start date"),
            ("too_early", "2005-12-31", "on or after 2006-01-01"),
            ("future", "2026-04-01", "can't be in the future"),
        ]
    )
    def test_bad_start_date_is_rejected_before_any_request(self, _name: str, start_date: str, fragment: str) -> None:
        with scripted_network([]) as network:
            ok, message = validate_credentials("access-token", PUBLISHER_ID, start_date=start_date)

        assert ok is False
        assert message is not None and fragment in message
        assert network.requests_log == []
