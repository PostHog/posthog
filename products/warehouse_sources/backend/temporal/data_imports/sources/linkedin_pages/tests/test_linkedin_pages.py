import json
import datetime as dt
from typing import Any, Optional, cast

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.linkedin_pages import (
    INITIAL_LOOKBACK_DAYS,
    MAX_CONFIGURED_ORGANIZATIONS,
    PAGE_SIZE,
    LinkedinPagesApiError,
    LinkedinPagesClient,
    LinkedinPagesDailyRateLimitError,
    LinkedinPagesResumeConfig,
    LinkedinPagesRetryableError,
    PageCursor,
    encode_restli_params,
    linkedin_pages_source,
    next_cursor,
    organization_entity_path,
    organization_urns_from_config,
    post_row,
    probe_credentials,
    statistics_row,
    time_intervals_param,
    window_start_from_watermark,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.settings import (
    LINKEDIN_PAGES_ENDPOINTS,
)

SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.linkedin_pages"
    ".make_tracked_session"
)
BATCHER_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_pages.linkedin_pages.Batcher"

ORG_ONE = "urn:li:organization:1"
ORG_TWO = "urn:li:organization:2"


def _response(status: int = 200, body: Any = None, text: Optional[str] = None) -> Response:
    response = Response()
    response.status_code = status
    response._content = (text if text is not None else json.dumps(body if body is not None else {})).encode()
    return response


def _session(get_responses: list[Response]) -> mock.MagicMock:
    session = mock.MagicMock()
    session.get.side_effect = get_responses
    return session


def _requested_urls(session: mock.MagicMock) -> list[str]:
    return [call.args[0] if call.args else call.kwargs["url"] for call in session.get.call_args_list]


def _client(session: mock.MagicMock) -> LinkedinPagesClient:
    with mock.patch(SESSION_PATCH, return_value=session):
        return LinkedinPagesClient("at_1")


def _manager(resume: Optional[LinkedinPagesResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _epoch_ms(day: dt.date) -> int:
    return int(dt.datetime.combine(day, dt.time.min, tzinfo=dt.UTC).timestamp() * 1000)


def _stats_element(day: dt.date, views: int = 1) -> dict[str, Any]:
    return {
        "timeRange": {"start": _epoch_ms(day), "end": _epoch_ms(day + dt.timedelta(days=1))},
        "totalPageStatistics": {"views": {"allPageViews": {"pageViews": views}}},
    }


def _rows_from(source_response: Any) -> list[dict[str, Any]]:
    return [row for table in cast("list[Any]", source_response.items()) for row in table.to_pylist()]


class TestLinkedinPagesTransport:
    @pytest.mark.parametrize(
        "params, expected",
        [
            # Rest.li punctuation is grammar, not data — it must survive encoding verbatim.
            ({"organization": ORG_ONE}, "organization=urn:li:organization:1"),
            (
                {"timeIntervals": "(timeRange:(start:1,end:2),timeGranularityType:DAY)"},
                "timeIntervals=(timeRange:(start:1,end:2),timeGranularityType:DAY)",
            ),
            ({"q": "roleAssignee", "count": 10}, "q=roleAssignee&count=10"),
            # Anything that isn't Rest.li grammar still gets escaped.
            ({"pageToken": "a b&c"}, "pageToken=a%20b%26c"),
        ],
    )
    def test_encode_restli_params(self, params: dict[str, Any], expected: str) -> None:
        assert encode_restli_params(params) == expected

    def test_time_intervals_param_end_is_exclusive_day_boundary(self) -> None:
        encoded = time_intervals_param(dt.date(2026, 1, 1), dt.date(2026, 1, 2))

        start = _epoch_ms(dt.date(2026, 1, 1))
        end = _epoch_ms(dt.date(2026, 1, 3))
        assert encoded == f"(timeRange:(start:{start},end:{end}),timeGranularityType:DAY)"

    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, []),
            ([], []),
            (["  "], []),
            (["123"], ["urn:li:organization:123"]),
            (["123", " 456"], ["urn:li:organization:123", "urn:li:organization:456"]),
            # The page picker stores URNs, and showcase pages aren't `urn:li:organization:`.
            (["urn:li:organizationBrand:9"], ["urn:li:organizationBrand:9"]),
            # A repeated page would otherwise cost a second full fan-out for identical rows.
            (["123", "urn:li:organization:123", " 123 "], ["urn:li:organization:123"]),
        ],
    )
    def test_organization_urns_from_config(self, raw: Optional[list[str]], expected: list[str]) -> None:
        assert organization_urns_from_config(raw) == expected

    def test_organization_urns_from_config_caps_the_list(self) -> None:
        # Each organization fans out into its own statistics requests against a daily, app-wide
        # call budget, so a hand-edited config can't ask for an unbounded number of them.
        at_limit = [str(i) for i in range(MAX_CONFIGURED_ORGANIZATIONS)]
        assert len(organization_urns_from_config(at_limit)) == MAX_CONFIGURED_ORGANIZATIONS

        with pytest.raises(ValueError):
            organization_urns_from_config([*at_limit, "99999"])

    @pytest.mark.parametrize(
        "raw",
        [
            "../me",
            "123/../../me",
            "urn:li:organization:../me",
            "urn:li:person:9",
            "abc",
        ],
    )
    def test_organization_urns_from_config_rejects_non_numeric_ids(self, raw: str) -> None:
        # These would otherwise become URN path segments and retarget the authenticated request.
        with pytest.raises(ValueError):
            organization_urns_from_config([raw])

    @pytest.mark.parametrize(
        "urn, expected",
        [
            (ORG_ONE, "/organizations"),
            ("urn:li:organizationBrand:9", "/organizationBrands"),
        ],
    )
    def test_organization_entity_path(self, urn: str, expected: str) -> None:
        assert organization_entity_path(urn) == expected

    @pytest.mark.parametrize(
        "endpoint, expected",
        [
            # Rest.li names the URN param after the entity, and it differs per resource.
            ("page_statistics", {"q": "organization", "organization": ORG_ONE}),
            ("follower_statistics", {"q": "organizationalEntity", "organizationalEntity": ORG_ONE}),
            ("share_statistics", {"q": "organizationalEntity", "organizationalEntity": ORG_ONE}),
            ("posts", {"q": "author", "author": ORG_ONE}),
        ],
    )
    def test_urn_query_per_endpoint(self, endpoint: str, expected: dict[str, str]) -> None:
        assert LINKEDIN_PAGES_ENDPOINTS[endpoint].urn_query(ORG_ONE) == expected

    def test_urn_query_rejects_an_endpoint_that_is_not_urn_addressed(self) -> None:
        with pytest.raises(ValueError):
            LINKEDIN_PAGES_ENDPOINTS["organizations"].urn_query(ORG_ONE)

    @pytest.mark.parametrize(
        "body, current, received, expected",
        [
            # A next token always wins, whichever style the walk started in.
            ({"metadata": {"nextPageToken": "t2"}}, PageCursor(), PAGE_SIZE, PageCursor(token="t2")),
            # Token-paginated walks end when the token stops coming — never fall back to offsets,
            # which would restart the walk from the first page.
            ({}, PageCursor(token="t1"), PAGE_SIZE, None),
            # A short page is the offset walk's end-of-list signal.
            ({}, PageCursor(offset=100), PAGE_SIZE - 1, None),
            ({}, PageCursor(), 0, None),
            ({}, PageCursor(offset=100), PAGE_SIZE, PageCursor(offset=100 + PAGE_SIZE)),
        ],
    )
    def test_next_cursor(
        self, body: dict[str, Any], current: PageCursor, received: int, expected: Optional[PageCursor]
    ) -> None:
        assert next_cursor(body, current, received) == expected

    def test_statistics_row_adds_organization_and_date(self) -> None:
        row = statistics_row(_stats_element(dt.date(2026, 5, 4)), ORG_ONE)

        assert row is not None
        assert row["organization"] == ORG_ONE
        assert row["organization_id"] == "1"
        assert row["date"] == dt.date(2026, 5, 4)

    @pytest.mark.parametrize("element", [{}, {"timeRange": None}, {"timeRange": {"end": 1}}])
    def test_statistics_row_drops_elements_without_a_time_bucket(self, element: dict[str, Any]) -> None:
        # A lifetime element has no bucket, so it has neither a cursor nor a unique primary key.
        assert statistics_row(element, ORG_ONE) is None

    @pytest.mark.parametrize(
        "created_at, expected",
        [
            (1767225600000, dt.datetime(2026, 1, 1, tzinfo=dt.UTC)),
            (None, None),
            ("not-a-timestamp", None),
        ],
    )
    def test_post_row_normalizes_created_at(self, created_at: Any, expected: Optional[dt.datetime]) -> None:
        row = post_row({"id": "urn:li:share:9", "createdAt": created_at}, ORG_ONE)

        assert row["created_at"] == expected
        assert row["organization"] == ORG_ONE
        assert row["organization_id"] == "1"

    @pytest.mark.parametrize(
        "last_value, expected_offset_days",
        [
            (dt.date(2026, 5, 10), 1),
            (dt.datetime(2026, 5, 10, 12, 30, tzinfo=dt.UTC), 1),
            ("2026-05-10", 1),
            ("2026-05-10T00:00:00Z", 1),
        ],
    )
    def test_window_start_from_watermark_rereads_the_watermark_day(
        self, last_value: Any, expected_offset_days: int
    ) -> None:
        # Boundary semantics differ per statistics resource, so the watermark day is re-requested.
        start = window_start_from_watermark(last_value, dt.date(2026, 6, 1))

        assert start == dt.date(2026, 5, 10) - dt.timedelta(days=expected_offset_days)

    @pytest.mark.parametrize("last_value", [None, "", "not-a-date"])
    def test_window_start_from_watermark_falls_back_to_the_retention_window(self, last_value: Any) -> None:
        today = dt.date(2026, 6, 1)

        assert window_start_from_watermark(last_value, today) == today - dt.timedelta(days=INITIAL_LOOKBACK_DAYS)

    def test_client_sends_the_integration_token_with_versioned_restli_headers(self) -> None:
        session = _session([_response(body={"elements": []})])
        client = _client(session)

        client.request("/organizations/1", {})

        headers = session.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer at_1"
        assert headers["LinkedIn-Version"] == "202606"
        assert headers["X-Restli-Protocol-Version"] == "2.0.0"

    def test_client_surfaces_a_401_instead_of_reauthenticating(self) -> None:
        # The integration owns the token, so a 401 is for its refresh to fix, not the transport.
        # Re-sending here would only burn LinkedIn's daily call budget.
        session = _session([_response(status=401, body={"message": "bad"})])
        client = _client(session)

        with pytest.raises(LinkedinPagesApiError) as excinfo:
            client.request("/organizations/1", {})

        assert session.get.call_count == 1
        assert excinfo.value.api_status_code == 401
        assert "LinkedIn API error (401)" in str(excinfo.value)

    @pytest.mark.parametrize(
        "status, text, expected_exception",
        [
            (429, '{"message":"Request throttled: DAY window"}', LinkedinPagesDailyRateLimitError),
            (429, '{"message":"Request throttled: MINUTE window"}', LinkedinPagesRetryableError),
            (500, "boom", LinkedinPagesRetryableError),
            (503, "unavailable", LinkedinPagesRetryableError),
            (403, '{"serviceErrorCode":100}', LinkedinPagesApiError),
            (404, '{"code":"RESOURCE_NOT_FOUND"}', LinkedinPagesApiError),
            (200, "<html>gateway</html>", LinkedinPagesRetryableError),
        ],
    )
    def test_client_classifies_responses(self, status: int, text: str, expected_exception: type[Exception]) -> None:
        client = _client(_session([_response(status=status, text=text)]))

        with pytest.raises(expected_exception):
            client.request("/organizations/1", {})

    def test_iter_finder_pages_walks_offsets_and_stops_on_a_short_page(self) -> None:
        full_page = {"elements": [{"organization": ORG_ONE} for _ in range(PAGE_SIZE)]}
        session = _session([_response(body=full_page), _response(body={"elements": [{"organization": ORG_TWO}]})])
        client = _client(session)

        pages = list(client.iter_finder_pages("/organizationAcls", {"q": "roleAssignee"}))

        assert [cursor for _, cursor in pages] == [PageCursor(offset=PAGE_SIZE), None]
        assert f"start={PAGE_SIZE}" in _requested_urls(session)[1]

    def test_iter_finder_pages_follows_a_page_token_when_the_finder_returns_one(self) -> None:
        session = _session(
            [
                _response(body={"elements": [{"id": "a"}], "metadata": {"nextPageToken": "tok2"}}),
                _response(body={"elements": [{"id": "b"}]}),
            ]
        )
        client = _client(session)

        pages = list(client.iter_finder_pages("/posts", {"q": "author"}))

        assert len(pages) == 2
        assert "pageToken=tok2" in _requested_urls(session)[1]
        assert "start=" not in _requested_urls(session)[1]

    def test_list_organization_urns_is_sorted_and_deduplicated(self) -> None:
        session = _session(
            [
                _response(
                    body={"elements": [{"organization": ORG_TWO}, {"organization": ORG_ONE}, {}, {"organization": 5}]}
                )
            ]
        )
        client = _client(session)

        # Resume state indexes into this list, so its order has to be deterministic.
        assert client.list_organization_urns() == [ORG_ONE, ORG_TWO]

    def test_list_administered_organizations_labels_pages_with_their_name(self) -> None:
        session = _session(
            [
                _response(body={"elements": [{"organization": ORG_TWO}, {"organization": ORG_ONE}]}),
                _response(body={"results": {"1": {"localizedName": "Acme"}}}),
            ]
        )
        client = _client(session)

        organizations = client.list_administered_organizations()

        assert [(org.urn, org.name) for org in organizations] == [(ORG_ONE, "Acme"), (ORG_TWO, "Page 2")]
        # One batch call, with the Rest.li id list left unescaped.
        assert "ids=List(1,2)" in _requested_urls(session)[1]

    def test_list_administered_organizations_still_lists_pages_when_the_name_lookup_is_denied(self) -> None:
        session = _session(
            [
                _response(body={"elements": [{"organization": ORG_ONE}]}),
                _response(status=403, body={"message": "nope"}),
            ]
        )
        client = _client(session)

        assert [org.name for org in client.list_administered_organizations()] == ["Page 1"]

    @pytest.mark.parametrize(
        "status, expected",
        [
            (200, (True, 200)),
            (401, (False, 401)),
            (403, (False, 403)),
        ],
    )
    def test_probe_credentials_maps_status(self, status: int, expected: tuple[bool, Optional[int]]) -> None:
        body: dict[str, Any] = {"elements": []} if status == 200 else {"message": "nope"}
        with mock.patch(SESSION_PATCH, return_value=_session([_response(status=status, body=body)])):
            assert probe_credentials("at_1") == expected

    def test_probe_credentials_never_raises_on_transport_failure(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = OSError("connection reset")

        with mock.patch(SESSION_PATCH, return_value=session):
            assert probe_credentials("at_1") == (False, None)


class TestLinkedinPagesSourceResponse:
    @pytest.mark.parametrize("endpoint", sorted(LINKEDIN_PAGES_ENDPOINTS))
    def test_source_response_metadata_matches_the_endpoint_catalog(self, endpoint: str) -> None:
        config = LINKEDIN_PAGES_ENDPOINTS[endpoint]

        response = linkedin_pages_source(
            access_token="at_1",
            organization_ids=["1"],
            endpoint=endpoint,
            resumable_source_manager=_manager(),
            logger=mock.MagicMock(),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.partition_keys == ([config.partition_key] if config.partition_key else None)
        # `posts` is fetched newest-first (`sortBy=LAST_MODIFIED`); statistics walk forward in time.
        assert response.sort_mode == ("desc" if endpoint == "posts" else "asc")

    def test_statistics_rows_carry_the_organization_they_were_fetched_for(self) -> None:
        today = dt.datetime.now(tz=dt.UTC).date()
        session = _session(
            [
                _response(body={"elements": [_stats_element(today - dt.timedelta(days=1), views=7)]}),
                _response(body={"elements": [_stats_element(today - dt.timedelta(days=1), views=9)]}),
            ]
        )

        with mock.patch(SESSION_PATCH, return_value=session):
            rows = _rows_from(
                linkedin_pages_source(
                    access_token="at_1",
                    organization_ids=["1", "2"],
                    endpoint="page_statistics",
                    resumable_source_manager=_manager(),
                    logger=mock.MagicMock(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=today - dt.timedelta(days=2),
                )
            )

        assert [row["organization"] for row in rows] == [ORG_ONE, ORG_TWO]
        assert [row["date"] for row in rows] == [today - dt.timedelta(days=1)] * 2
        # One windowed request per organization, each carrying the Rest.li time interval.
        urls = _requested_urls(session)
        assert len(urls) == 2
        assert "timeIntervals=(timeRange:(start:" in urls[0]
        assert f"organization={ORG_ONE}" in urls[0]

    def test_incremental_window_starts_from_the_watermark_not_the_retention_edge(self) -> None:
        today = dt.datetime.now(tz=dt.UTC).date()
        session = _session([_response(body={"elements": []})])

        with mock.patch(SESSION_PATCH, return_value=session):
            _rows_from(
                linkedin_pages_source(
                    access_token="at_1",
                    organization_ids=["1"],
                    endpoint="follower_statistics",
                    resumable_source_manager=_manager(),
                    logger=mock.MagicMock(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=today - dt.timedelta(days=3),
                )
            )

        expected_start = _epoch_ms(today - dt.timedelta(days=4))
        assert f"start:{expected_start}," in _requested_urls(session)[0]

    def test_full_refresh_window_covers_the_retention_period(self) -> None:
        today = dt.datetime.now(tz=dt.UTC).date()
        # 365 days of lookback is more than one 90-day window, so the sync walks several.
        session = _session([_response(body={"elements": []}) for _ in range(10)])

        with mock.patch(SESSION_PATCH, return_value=session):
            _rows_from(
                linkedin_pages_source(
                    access_token="at_1",
                    organization_ids=["1"],
                    endpoint="share_statistics",
                    resumable_source_manager=_manager(),
                    logger=mock.MagicMock(),
                )
            )

        urls = _requested_urls(session)
        assert len(urls) == 5
        assert f"start:{_epoch_ms(today - dt.timedelta(days=INITIAL_LOOKBACK_DAYS))}," in urls[0]

    def test_resume_skips_organizations_and_windows_already_synced(self) -> None:
        today = dt.datetime.now(tz=dt.UTC).date()
        session = _session([_response(body={"elements": [_stats_element(today)]})])
        resume = LinkedinPagesResumeConfig(org_index=1, next_window_start=(today - dt.timedelta(days=1)).isoformat())

        with mock.patch(SESSION_PATCH, return_value=session):
            rows = _rows_from(
                linkedin_pages_source(
                    access_token="at_1",
                    organization_ids=["1", "2"],
                    endpoint="page_statistics",
                    resumable_source_manager=_manager(resume),
                    logger=mock.MagicMock(),
                )
            )

        urls = _requested_urls(session)
        assert len(urls) == 1
        assert f"organization={ORG_TWO}" in urls[0]
        assert f"start:{_epoch_ms(today - dt.timedelta(days=1))}," in urls[0]
        assert [row["organization"] for row in rows] == [ORG_TWO]

    def test_resume_state_is_saved_only_after_rows_are_yielded(self) -> None:
        today = dt.datetime.now(tz=dt.UTC).date()
        session = _session(
            [
                _response(body={"elements": [_stats_element(today - dt.timedelta(days=1))]}),
                _response(body={"elements": [_stats_element(today - dt.timedelta(days=1))]}),
            ]
        )
        manager = _manager()

        with (
            mock.patch(SESSION_PATCH, return_value=session),
            mock.patch(BATCHER_PATCH, lambda logger: Batcher(logger=logger, chunk_size=1)),
        ):
            response = linkedin_pages_source(
                access_token="at_1",
                organization_ids=["1", "2"],
                endpoint="page_statistics",
                resumable_source_manager=manager,
                logger=mock.MagicMock(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=today - dt.timedelta(days=2),
            )

            saves_at_each_table = [len(manager.save_state.call_args_list) for _ in cast("list[Any]", response.items())]

        # Two tables reach the pipeline, and neither is preceded by a checkpoint: state is only
        # persisted once the table it covers has been handed over.
        assert saves_at_each_table == [0, 0]
        assert [call.args[0] for call in manager.save_state.call_args_list] == [
            LinkedinPagesResumeConfig(org_index=1),
            LinkedinPagesResumeConfig(org_index=2),
        ]

    def test_daily_rate_limit_stops_the_run_but_keeps_what_was_already_fetched(self) -> None:
        today = dt.datetime.now(tz=dt.UTC).date()
        session = _session(
            [
                _response(body={"elements": [_stats_element(today - dt.timedelta(days=1))]}),
                _response(status=429, text='{"message":"Request throttled: DAY window"}'),
            ]
        )
        logger = mock.MagicMock()

        with mock.patch(SESSION_PATCH, return_value=session):
            rows = _rows_from(
                linkedin_pages_source(
                    access_token="at_1",
                    organization_ids=["1", "2"],
                    endpoint="page_statistics",
                    resumable_source_manager=_manager(),
                    logger=logger,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=today - dt.timedelta(days=2),
                )
            )

        assert [row["organization"] for row in rows] == [ORG_ONE]
        assert logger.info.called

    def test_organizations_are_discovered_when_no_id_is_configured(self) -> None:
        session = _session(
            [
                _response(body={"elements": [{"organization": ORG_ONE}]}),
                _response(body={"id": 1, "localizedName": "PostHog"}),
            ]
        )

        with mock.patch(SESSION_PATCH, return_value=session):
            rows = _rows_from(
                linkedin_pages_source(
                    access_token="at_1",
                    organization_ids=None,
                    endpoint="organizations",
                    resumable_source_manager=_manager(),
                    logger=mock.MagicMock(),
                )
            )

        urls = _requested_urls(session)
        assert "/organizationAcls?" in urls[0]
        assert urls[1].endswith("/organizations/1")
        assert rows == [{"id": 1, "localizedName": "PostHog", "urn": ORG_ONE}]

    def test_posts_paginate_per_organization_and_carry_the_author_page(self) -> None:
        session = _session(
            [
                _response(body={"elements": [{"id": "urn:li:share:1", "createdAt": 1767225600000}]}),
            ]
        )

        with mock.patch(SESSION_PATCH, return_value=session):
            rows = _rows_from(
                linkedin_pages_source(
                    access_token="at_1",
                    organization_ids=["1"],
                    endpoint="posts",
                    resumable_source_manager=_manager(),
                    logger=mock.MagicMock(),
                )
            )

        url = _requested_urls(session)[0]
        assert f"author={ORG_ONE}" in url
        assert "q=author" in url
        assert "sortBy=LAST_MODIFIED" in url
        assert rows[0]["organization"] == ORG_ONE
        assert rows[0]["created_at"] == dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

    def test_no_administered_organizations_yields_nothing(self) -> None:
        session = _session([_response(body={"elements": []})])
        logger = mock.MagicMock()

        with mock.patch(SESSION_PATCH, return_value=session):
            rows = _rows_from(
                linkedin_pages_source(
                    access_token="at_1",
                    organization_ids=None,
                    endpoint="page_statistics",
                    resumable_source_manager=_manager(),
                    logger=logger,
                )
            )

        assert rows == []
        assert logger.warning.called
