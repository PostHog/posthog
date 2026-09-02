import json
import datetime as dt
from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Request, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.reddit_ads import (
    RedditAdsApiError,
    RedditAdsPaginator,
    _get_incremental_date_range,
    get_resource,
    list_business_ad_accounts,
    list_businesses,
    reddit_ads_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.settings import REDDIT_ADS_CONFIG


class TestRedditAdsHelperFunctions:
    """Test helper functions in reddit_ads.py."""

    def test_get_incremental_date_range_with_datetime(self):
        last_value = dt.datetime(2024, 3, 15, 14, 30, 0)
        starts_at, ends_at = _get_incremental_date_range(True, last_value)

        assert starts_at == "2024-03-15T14:00:00Z"
        assert ends_at.endswith(":00:00Z")  # Should be next hour (rounded to hour)

    def test_get_incremental_date_range_with_date(self):
        last_value = dt.date(2024, 3, 15)
        starts_at, ends_at = _get_incremental_date_range(True, last_value)

        assert starts_at == "2024-03-15T00:00:00Z"
        assert ends_at.endswith(":00:00Z")  # Should be next hour (rounded to hour)

    def test_get_incremental_date_range_with_string(self):
        last_value = "2024-03-15T14:30:00Z"
        starts_at, ends_at = _get_incremental_date_range(True, last_value)

        assert starts_at == "2024-03-15T14:00:00Z"
        assert ends_at.endswith(":00:00Z")  # Should be next hour (rounded to hour)

    def test_get_incremental_date_range_with_invalid_string(self):
        last_value = "invalid-date"
        starts_at, ends_at = _get_incremental_date_range(True, last_value)

        # Should fall back to initial_datetime
        assert starts_at is not None
        assert ends_at.endswith(":00:00Z")  # Should be next hour (rounded to hour)

    def test_get_incremental_date_range_no_incremental(self):
        starts_at, ends_at = _get_incremental_date_range(False)

        # Should use initial_datetime
        assert starts_at is not None
        assert ends_at.endswith(":00:00Z")  # Should be next hour (rounded to hour)

    def test_get_incremental_date_range_none_value(self):
        starts_at, ends_at = _get_incremental_date_range(True, None)

        # Should use initial_datetime
        assert starts_at is not None
        assert ends_at.endswith(":00:00Z")  # Should be next hour (rounded to hour)


class TestGetResource:
    """Test get_resource function."""

    def test_get_resource_campaigns(self):
        resource = get_resource("campaigns", "test_account", False)

        assert resource["name"] == "campaigns"
        assert resource["table_name"] == "campaigns"
        assert "primary_key" not in resource
        assert isinstance(resource["endpoint"], dict)
        assert resource["endpoint"]["path"] == "/ad_accounts/test_account/campaigns"
        assert resource["endpoint"]["method"] == "GET"
        assert resource["write_disposition"] == "replace"

    def test_get_resource_campaigns_incremental(self):
        resource = get_resource("campaigns", "test_account", True, dt.datetime(2024, 3, 15, 14, 30))

        assert isinstance(resource["write_disposition"], dict)
        write_disposition = resource["write_disposition"]
        assert write_disposition["disposition"] == "merge"
        assert write_disposition["strategy"] == "upsert"
        assert isinstance(resource["endpoint"], dict)
        endpoint_params = resource["endpoint"]["params"]
        assert endpoint_params is not None
        assert "modified_at[after]" in endpoint_params

    def test_get_resource_campaign_report_incremental(self):
        resource = get_resource("campaign_report", "test_account", True, dt.datetime(2024, 3, 15, 14, 30))

        assert isinstance(resource["write_disposition"], dict)
        write_disposition = resource["write_disposition"]
        assert write_disposition["disposition"] == "merge"
        assert write_disposition["strategy"] == "upsert"
        assert isinstance(resource["endpoint"], dict)
        assert resource["endpoint"]["method"] == "POST"
        endpoint_json = resource["endpoint"]["json"]
        assert endpoint_json is not None
        assert endpoint_json["data"]["starts_at"] == "2024-03-15T14:00:00Z"
        assert endpoint_json["data"]["ends_at"].endswith(":00:00Z")  # Should be next hour (rounded to hour)

    def test_get_resource_unknown_endpoint(self):
        with pytest.raises(ValueError, match="Unknown endpoint: unknown_endpoint"):
            get_resource("unknown_endpoint", "test_account", False)

    def test_get_resource_invalid_endpoint_type(self):
        # This would require mocking REDDIT_ADS_CONFIG to have invalid endpoint
        # For now, we'll test the happy path since the config is properly structured
        resource = get_resource("campaigns", "test_account", False)
        assert isinstance(resource["endpoint"], dict)

    @parameterized.expand(
        [
            ("ad_account", "/ad_accounts/test_account"),
            ("custom_audiences", "/ad_accounts/test_account/custom_audiences"),
            ("saved_audiences", "/ad_accounts/test_account/saved_audiences"),
            ("pixels", "/ad_accounts/test_account/pixels"),
            ("funding_instruments", "/ad_accounts/test_account/funding_instruments"),
            ("lead_gen_forms", "/ad_accounts/test_account/lead_gen_forms"),
            ("profiles", "/ad_accounts/test_account/profiles"),
        ]
    )
    def test_account_scoped_list_endpoints_bind_the_account_id(self, endpoint: str, expected_path: str) -> None:
        resource = get_resource(endpoint, "test_account", False)

        assert isinstance(resource["endpoint"], dict)
        assert resource["endpoint"]["path"] == expected_path
        assert resource["endpoint"]["method"] == "GET"


class TestBreakdownReportEndpoints:
    """Reddit returns breakdowns as extra dimensions on the same report request, so each dimension is
    its own table. The request body has two hard constraints these tests pin down."""

    BREAKDOWN_TABLES = [
        ("campaign_country_report", "COUNTRY", "country"),
        ("campaign_gender_report", "GENDER", "gender"),
        ("campaign_placement_report", "PLACEMENT", "placement"),
        ("campaign_community_report", "COMMUNITY", "community"),
        ("campaign_os_type_report", "OS_TYPE", "os_type"),
        ("campaign_keyword_report", "KEYWORD", "keyword"),
    ]

    @parameterized.expand(BREAKDOWN_TABLES)
    def test_breakdowns_stay_within_reddits_three_dimension_cap(
        self, endpoint: str, breakdown: str, column: str
    ) -> None:
        resource = get_resource(endpoint, "test_account", False)

        assert isinstance(resource["endpoint"], dict)
        body = resource["endpoint"]["json"]
        assert body is not None
        assert body["data"]["breakdowns"] == ["CAMPAIGN_ID", "DATE", breakdown]

    @parameterized.expand(BREAKDOWN_TABLES)
    def test_breakdown_column_is_part_of_the_primary_key(self, endpoint: str, breakdown: str, column: str) -> None:
        # Rows only differ by the breakdown value, so leaving it out collapses every dimension value
        # for a campaign-day onto one row.
        assert REDDIT_ADS_CONFIG[endpoint].resource["primary_key"] == ["campaign_id", "date", column]

    @parameterized.expand(
        [
            # Dimensions Reddit accepts in both `breakdowns` and `fields` must be requested as a field,
            # otherwise the response carries no column to key the row on.
            ("campaign_country_report", "COUNTRY", True),
            ("campaign_gender_report", "GENDER", True),
            ("campaign_placement_report", "PLACEMENT", True),
            ("campaign_community_report", "COMMUNITY", True),
            # `OS_TYPE` is a valid breakdown but is not a member of Reddit's `fields` enum — asking for
            # it as a field is rejected and fails the whole report request.
            ("campaign_os_type_report", "OS_TYPE", False),
            # `KEYWORD`'s membership of the `fields` enum is unconfirmed, so it is requested as a
            # breakdown only rather than risking a rejected report request.
            ("campaign_keyword_report", "KEYWORD", False),
        ]
    )
    def test_dimension_is_requested_as_a_field_only_when_reddit_allows_it(
        self, endpoint: str, breakdown: str, expected_in_fields: bool
    ) -> None:
        resource = get_resource(endpoint, "test_account", False)

        assert isinstance(resource["endpoint"], dict)
        body = resource["endpoint"]["json"]
        assert body is not None
        assert (breakdown in body["data"]["fields"]) is expected_in_fields


class TestRedditAdsPaginator:
    """Test RedditAdsPaginator class."""

    def test_paginator_init(self):
        paginator = RedditAdsPaginator()
        assert paginator._next_url is None
        assert paginator._has_next_page is False

    def test_update_state_with_pagination(self):
        paginator = RedditAdsPaginator()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {"pagination": {"next_url": "https://api.reddit.com/next-page"}}

        paginator.update_state(mock_response)

        assert paginator._next_url == "https://api.reddit.com/next-page"
        assert paginator._has_next_page is True

    def test_update_state_without_pagination(self):
        paginator = RedditAdsPaginator()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {"data": []}

        paginator.update_state(mock_response)

        assert paginator._next_url is None
        assert paginator._has_next_page is False

    def test_update_state_invalid_json(self):
        paginator = RedditAdsPaginator()

        mock_response = mock.MagicMock()
        mock_response.json.side_effect = Exception("Invalid JSON")

        paginator.update_state(mock_response)

        assert paginator._next_url is None
        assert paginator._has_next_page is False

    def test_update_request_with_next_url(self):
        paginator = RedditAdsPaginator()
        paginator._next_url = "https://api.reddit.com/next-page"

        mock_request = mock.MagicMock()
        paginator.update_request(mock_request)

        assert mock_request.url == "https://api.reddit.com/next-page"

    def test_update_request_without_next_url(self):
        paginator = RedditAdsPaginator()

        mock_request = mock.MagicMock()
        original_url = mock_request.url
        paginator.update_request(mock_request)

        # URL should remain unchanged
        assert mock_request.url == original_url

    @parameterized.expand(
        [
            ("fresh_paginator", None, None),
            (
                "after_update_with_next_url",
                {"pagination": {"next_url": "https://api.reddit.com/page-2"}},
                {"next_url": "https://api.reddit.com/page-2"},
            ),
            ("after_terminal_page", {"pagination": {}}, None),
        ]
    )
    def test_get_resume_state(
        self, _name: str, response_body: Optional[dict[str, Any]], expected: Optional[dict[str, Any]]
    ) -> None:
        paginator = RedditAdsPaginator()
        if response_body is not None:
            mock_response = mock.MagicMock()
            mock_response.json.return_value = response_body
            paginator.update_state(mock_response)

        assert paginator.get_resume_state() == expected

    def test_set_resume_state_round_trip(self):
        """set_resume_state then get_resume_state returns the same value."""
        paginator = RedditAdsPaginator()
        paginator.set_resume_state({"next_url": "https://api.reddit.com/page-5"})

        assert paginator.has_next_page is True
        assert paginator.get_resume_state() == {"next_url": "https://api.reddit.com/page-5"}

    def test_redirect_to_next_url_stops_the_url_from_growing(self) -> None:
        """The prepared URL must not grow as pages advance.

        The REST client reuses one `Request` across pages and seeds `page.size` in its params.
        Reddit's `next_url` already carries `page.size`, so without clearing the params `requests`
        appends `page.size` again on every page and the URL grows until Reddit returns 414.
        """
        session = Session()
        base_url = "https://ads-api.reddit.com/api/v3/ad_accounts/a1/reports"
        request = Request(method="GET", url=base_url, params={"page.size": 100})

        paginator = RedditAdsPaginator()
        paginator.init_request(request)

        prepared_urls = [session.prepare_request(request).url or ""]
        for page in range(2, 6):
            paginator._next_url = f"{base_url}?page={page}&page.size=100"
            paginator.update_request(request)
            prepared_urls.append(session.prepare_request(request).url or "")

        # Each redirect swaps in the next self-contained URL, so `page.size` appears once per page.
        for url in prepared_urls:
            assert url.count("page.size") == 1

    @parameterized.expand(
        [
            ("no_seed", None),
            ("seeded", "https://api.reddit.com/page-3"),
        ]
    )
    def test_init_request(self, _name: str, seed_url: Optional[str]) -> None:
        paginator = RedditAdsPaginator()
        if seed_url is not None:
            paginator.set_resume_state({"next_url": seed_url})

        mock_request = mock.MagicMock()
        original_url = mock_request.url
        paginator.init_request(mock_request)

        if seed_url is not None:
            assert mock_request.url == seed_url
        else:
            assert mock_request.url == original_url


class TestListBusinessesAndAdAccounts:
    MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.reddit_ads"

    @staticmethod
    def _response(status: int, body: dict) -> mock.MagicMock:
        response = mock.MagicMock()
        response.status_code = status
        response.json.return_value = body
        response.text = ""
        return response

    def test_follows_next_url_across_pages(self):
        session = mock.MagicMock()
        session.get.side_effect = [
            self._response(
                200,
                {
                    "data": [{"id": "b1"}],
                    "pagination": {"next_url": "https://ads-api.reddit.com/api/v3/me/businesses?page=2"},
                },
            ),
            self._response(200, {"data": [{"id": "b2"}], "pagination": {"next_url": None}}),
        ]

        with mock.patch(f"{self.MODULE}.make_tracked_session", return_value=session):
            businesses = list_businesses("token")

        assert [business["id"] for business in businesses] == ["b1", "b2"]
        assert session.get.call_args_list[1][0][0] == "https://ads-api.reddit.com/api/v3/me/businesses?page=2"

    def test_ad_accounts_are_requested_per_business(self):
        session = mock.MagicMock()
        session.get.return_value = self._response(200, {"data": [{"id": "a2_1"}], "pagination": {}})

        with mock.patch(f"{self.MODULE}.make_tracked_session", return_value=session):
            accounts = list_business_ad_accounts("token", "biz-1")

        assert [account["id"] for account in accounts] == ["a2_1"]
        assert session.get.call_args[0][0] == "https://ads-api.reddit.com/api/v3/businesses/biz-1/ad_accounts"

    def test_error_response_carries_the_api_status_code(self):
        session = mock.MagicMock()
        session.get.return_value = self._response(401, {})

        with mock.patch(f"{self.MODULE}.make_tracked_session", return_value=session):
            with pytest.raises(RedditAdsApiError) as excinfo:
                list_businesses("token")

        assert excinfo.value.api_status_code == 401

    def test_listing_session_disables_redirects_and_redacts_token(self):
        session = mock.MagicMock()
        session.get.return_value = self._response(200, {"data": [], "pagination": {}})

        with mock.patch(f"{self.MODULE}.make_tracked_session", return_value=session) as make_session:
            list_businesses("secret-token")

        assert make_session.call_args.kwargs["allow_redirects"] is False
        assert "secret-token" in make_session.call_args.kwargs["redact_values"]

    def test_cross_origin_next_url_is_rejected_without_resending_token(self):
        session = mock.MagicMock()
        session.get.return_value = self._response(
            200,
            {
                "data": [{"id": "b1"}],
                "pagination": {"next_url": "https://evil.example.com/api/v3/me/businesses?page=2"},
            },
        )

        with mock.patch(f"{self.MODULE}.make_tracked_session", return_value=session):
            with pytest.raises(IntegrationAccountListingError):
                list_businesses("token")

        # Only the first request (to the trusted origin) was made; the token never reached the foreign host.
        assert session.get.call_count == 1

    def test_relative_next_url_resolves_against_the_reddit_origin(self):
        session = mock.MagicMock()
        session.get.side_effect = [
            self._response(
                200,
                {"data": [{"id": "b1"}], "pagination": {"next_url": "/api/v3/me/businesses?page=2"}},
            ),
            self._response(200, {"data": [{"id": "b2"}], "pagination": {}}),
        ]

        with mock.patch(f"{self.MODULE}.make_tracked_session", return_value=session):
            businesses = list_businesses("token")

        assert [business["id"] for business in businesses] == ["b1", "b2"]
        assert session.get.call_args_list[1][0][0] == "https://ads-api.reddit.com/api/v3/me/businesses?page=2"


def _http_response(body: Any) -> Response:
    response = Response()
    response.status_code = 200
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


class TestRedditAdsListEndpointTransport:
    """Behaviour of the endpoints added on top of the original six, driven through a mocked session."""

    SESSION_PATH = (
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source."
        "rest_client.make_tracked_session"
    )

    def _run(self, endpoint: str, responses: list[Response]) -> tuple[list[Any], mock.MagicMock]:
        with mock.patch(self.SESSION_PATH) as MockSession:
            session = MockSession.return_value
            session.headers = {}
            session.prepare_request.side_effect = lambda req: req
            session.send.side_effect = responses

            source = reddit_ads_source(
                account_id="789",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                access_token="test_token",
                db_incremental_field_last_value=None,
                resumable_source_manager=mock.MagicMock(can_resume=mock.MagicMock(return_value=False)),
                should_use_incremental_field=False,
            )
            pages = list(source.items())
            return [row for page in pages for row in page], session

    def test_single_object_ad_account_response_yields_one_row(self):
        # `GET /ad_accounts/{id}` returns one object rather than a list, and the pipeline must still
        # see a row rather than choking on the unwrapped dict.
        rows, session = self._run(
            "ad_account",
            [_http_response({"data": {"id": "a2_789", "currency": "USD", "time_zone_id": "America/Los_Angeles"}})],
        )

        assert rows == [{"id": "a2_789", "currency": "USD", "time_zone_id": "America/Los_Angeles"}]
        assert session.send.call_args_list[0].args[0].url == "https://ads-api.reddit.com/api/v3/ad_accounts/789"

    def test_structured_posts_are_fanned_out_over_every_profile(self):
        # Reddit hangs creatives off profiles, not off the ad account, so this is the only endpoint
        # that has to walk a parent list first.
        rows, session = self._run(
            "structured_posts",
            [
                _http_response({"data": [{"id": "t2_p1"}, {"id": "t2_p2"}], "pagination": {}}),
                _http_response({"data": [{"id": "post-1", "profile_id": None}], "pagination": {}}),
                _http_response({"data": [{"id": "post-2", "profile_id": None}], "pagination": {}}),
            ],
        )

        requested = [call.args[0].url for call in session.send.call_args_list]
        assert requested[0].startswith("https://ads-api.reddit.com/api/v3/ad_accounts/789/profiles")
        assert "/profiles/t2_p1/structured_posts" in requested[1]
        assert "/profiles/t2_p2/structured_posts" in requested[2]

        # The parent id is authoritative: post rows carry a nullable `profile_id`, but the primary key
        # is (profile_id, id), so an unpopulated one would collapse posts across profiles.
        assert [(row["profile_id"], row["id"]) for row in rows] == [("t2_p1", "post-1"), ("t2_p2", "post-2")]
