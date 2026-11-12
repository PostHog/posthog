from datetime import UTC, date, datetime
from typing import Any, cast

import pytest

from parameterized import parameterized

from products.warehouse_sources.sources.sdk import PageNumberPaginator, SinglePagePaginator
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.tinyemail._config import TinyemailSourceConfig
from products.warehouse_sources.sources.tinyemail.source import TinyemailSource
from products.warehouse_sources.sources.tinyemail.tinyemail import (
    engagement_windows,
    get_resource,
    validate_credentials,
)


def _members_walk(request: RecordedRequest) -> ScriptedResponse:
    if request.path.endswith("/contacts"):
        return ScriptedResponse(json={"contacts": [{"id": "list_1", "name": "Newsletter"}]})
    if request.param("page") == "1":
        return ScriptedResponse(json={"members": {"content": [{"email": "a@example.com"}]}})
    return ScriptedResponse(json={"members": {"content": []}})


def _contacts_or(request: RecordedRequest, child: ScriptedResponse) -> ScriptedResponse:
    if request.path.endswith("/contacts"):
        return ScriptedResponse(json={"contacts": [{"id": "list_1", "name": "Newsletter"}]})
    return child


DOMAINS = ["gmail.com", "yahoo.com", "outlook.com"]


def _domain_stats_walk(honors_page: bool):
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/campaign"):
            if request.param("page") == "0":
                return ScriptedResponse(json={"campaigns": {"content": [{"id": "c1"}, {"id": "c2"}]}})
            return ScriptedResponse(json={"campaigns": {"content": []}})
        campaign_id = request.json()["campaignId"]
        page = request.param("page") if honors_page else "0"
        domain = DOMAINS[int(page or 0)]
        return ScriptedResponse(
            json={"content": [{"domainName": f"{campaign_id}.{domain}", "send": 1}], "totalPages": len(DOMAINS)}
        )

    return respond


class TestTinyemailTransport:
    @parameterized.expand(
        [
            # The campaigns list path really is singular, rows wrapped in `campaigns.content`,
            # and pages are 0-indexed.
            ("campaigns", "/campaign", "campaigns.content", PageNumberPaginator, 0, 20),
            ("contacts", "/contacts", "contacts", SinglePagePaginator, None, None),
            ("sender_details", "/sender-details", "senderDetailses", SinglePagePaginator, None, None),
            ("suppressions", "/suppression", "suppressions", SinglePagePaginator, None, None),
        ]
    )
    def test_get_resource_top_level(self, endpoint, path, data_selector, paginator_type, base_page, size) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint))

        assert resource["name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["table_format"] == "delta"
        assert resource["endpoint"]["path"] == path
        assert resource["endpoint"]["data_selector"] == data_selector

        paginator = resource["endpoint"]["paginator"]
        assert isinstance(paginator, paginator_type)
        if base_page is not None:
            assert paginator.page == base_page
        if size is not None:
            assert resource["endpoint"]["params"]["size"] == size
        else:
            assert "size" not in resource["endpoint"]["params"]

    def test_get_resource_rejects_fanout_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource("contact_members")

    def test_tinyemail_source_top_level_response(self) -> None:
        driver = SourceDriver(TinyemailSource(), TinyemailSourceConfig(api_key="key"))
        result = driver.run("campaigns", always(ScriptedResponse(json={"campaigns": {"content": []}})))

        assert result.response is not None
        assert result.response.name == "campaigns"
        assert result.response.primary_keys == ["id"]

    def test_tinyemail_source_contact_members_row_format(self) -> None:
        driver = SourceDriver(TinyemailSource(), TinyemailSourceConfig(api_key="key"))
        result = driver.run("contact_members", _members_walk)

        assert result.raised is None
        assert result.rows == [{"email": "a@example.com", "contact_id": "list_1"}]
        # An email is only unique within one contact list, so the parent id is part of the key.
        assert result.response is not None
        assert result.response.primary_keys == ["contact_id", "email"]

    def test_clean_history_reads_the_history_path_only(self) -> None:
        driver = SourceDriver(TinyemailSource(), TinyemailSourceConfig(api_key="key"))
        result = driver.run(
            "clean_history",
            lambda request: _contacts_or(
                request, ScriptedResponse(json={"histories": [{"id": "h1", "fileName": "f.csv", "dateTime": 1}]})
            ),
        )

        assert result.raised is None
        # `PUT /audiences/clean-list/{id}` without `/history` starts a paid list clean.
        assert [(r.method, r.path) for r in result.requests] == [
            ("GET", "/v1/contacts"),
            ("PUT", "/v1/audiences/clean-list/list_1/history"),
        ]
        assert result.rows == [{"id": "h1", "fileName": "f.csv", "dateTime": 1, "audience_id": "list_1"}]
        assert result.response is not None
        assert result.response.primary_keys == ["audience_id", "id"]

    @parameterized.expand(
        [
            ("api_honors_page", True, 3, 3),
            # Without page support every page repeats the first, so the walk stops at the first repeat.
            ("api_ignores_page", False, 2, 1),
        ]
    )
    def test_campaign_domain_stats_walk(
        self, _name: str, honors_page: bool, requests_per_campaign: int, domains_per_campaign: int
    ) -> None:
        driver = SourceDriver(TinyemailSource(), TinyemailSourceConfig(api_key="key"))
        result = driver.run("campaign_domain_stats", _domain_stats_walk(honors_page))

        assert result.raised is None
        stats_requests = [r for r in result.requests if r.path.endswith("/campaign/domain-stats")]
        assert all(r.method == "POST" for r in stats_requests)
        assert [r.json() for r in stats_requests] == [{"campaignId": "c1"}] * requests_per_campaign + [
            {"campaignId": "c2"}
        ] * requests_per_campaign
        domains = DOMAINS[:domains_per_campaign]
        assert result.rows == [
            {"domainName": f"{campaign}.{domain}", "send": 1, "campaign_id": campaign}
            for campaign in ("c1", "c2")
            for domain in domains
        ]

    @parameterized.expand(
        [
            (
                "first_sync_reads_90_days_in_7_day_windows",
                False,
                None,
                13,
                ("2026-08-15T00:00:00", "2026-08-21T23:59:59"),
                ("2026-11-07T00:00:00", "2026-11-12T10:30:00"),
            ),
            (
                "incremental_starts_at_the_watermark_day",
                True,
                "2026-11-01",
                2,
                ("2026-11-01T00:00:00", "2026-11-07T23:59:59"),
                ("2026-11-08T00:00:00", "2026-11-12T10:30:00"),
            ),
            (
                "incremental_accepts_a_date_watermark",
                True,
                date(2026, 11, 12),
                1,
                ("2026-11-12T00:00:00", "2026-11-12T10:30:00"),
                ("2026-11-12T00:00:00", "2026-11-12T10:30:00"),
            ),
            (
                "full_refresh_ignores_a_stored_watermark",
                False,
                "2026-11-01",
                13,
                ("2026-08-15T00:00:00", "2026-08-21T23:59:59"),
                ("2026-11-07T00:00:00", "2026-11-12T10:30:00"),
            ),
        ]
    )
    def test_engagement_windows(self, _name, incremental, last_value, count, first, last) -> None:
        now = datetime(2026, 11, 12, 10, 30, tzinfo=UTC)
        windows = engagement_windows(incremental, last_value, now)

        assert len(windows) == count
        assert windows[0] == first
        assert windows[-1] == last
        for window_from, window_to in windows:
            span = datetime.fromisoformat(window_to) - datetime.fromisoformat(window_from)
            assert span.days < 7

    def test_new_subscriber_engagement_asks_for_one_audience_per_request(self) -> None:
        driver = SourceDriver(TinyemailSource(), TinyemailSourceConfig(api_key="key"))
        row = {"date": "2026-11-10", "audienceName": "Newsletter", "sends": 3}
        result = driver.run(
            "new_subscriber_engagement",
            lambda request: _contacts_or(request, ScriptedResponse(json=[row])),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now(UTC).date().isoformat(),
        )

        assert result.raised is None
        report_requests = [r for r in result.requests if r.path.endswith("/new-subscriber-engagement")]
        assert len(report_requests) == 1
        assert report_requests[0].method == "POST"
        body = report_requests[0].json()
        assert body["audienceIds"] == ["list_1"]
        assert body["from"].endswith("T00:00:00")
        # Rows name the audience but carry no id, so the source adds it for the primary key.
        assert result.rows == [{**row, "audience_id": "list_1"}]
        assert result.response is not None
        assert result.response.primary_keys == ["audience_id", "date"]

    def test_validate_credentials_handles_request_exception(self) -> None:
        with scripted_network(always(ConnectionResetError("reset"))):
            is_valid, message = validate_credentials(api_key="key")

        assert is_valid is False
        assert message is not None and "Could not connect to the tinyEmail API" in message
