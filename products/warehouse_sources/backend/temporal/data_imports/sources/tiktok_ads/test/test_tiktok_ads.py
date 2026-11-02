from datetime import datetime, timedelta
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tiktokads import (
    TikTokAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.source import TikTokAdsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.tiktok_ads import (
    TikTokAdsResumeConfig,
    get_tiktok_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.utils import (
    TikTokDateRangeManager,
    TikTokReportResource,
)

ADVERTISER_ID = "123456789"


def _make_response(json_body: Any, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=json_body)


def _page_response(page: int, total_pages: int, items: list[dict[str, Any]]) -> ScriptedResponse:
    return _make_response(
        {
            "code": 0,
            "message": "OK",
            "data": {
                "list": items,
                "page_info": {
                    "page": page,
                    "page_size": 1000,
                    "total_page": total_pages,
                    "total_number": len(items) * total_pages,
                },
            },
        }
    )


def _drive(
    endpoint: str,
    script: Script,
    resume_state: TikTokAdsResumeConfig | None = None,
    **inputs: Any,
) -> DriveResult:
    driver = SourceDriver(
        TikTokAdsSource(), TikTokAdsSourceConfig(advertiser_id=ADVERTISER_ID, tiktok_integration_id=1)
    )
    integration = MagicMock(access_token="test_access_token")
    with patch.object(TikTokAdsSource, "get_oauth_integration", return_value=integration):
        return driver.run(endpoint, script, resume_state=resume_state, **inputs)


class TestTikTokAdsHelpers:
    """Test suite for TikTok Ads helper functions."""

    def test_flatten_tiktok_report_record_nested(self):
        nested_record = {
            "dimensions": {"campaign_id": "123456", "stat_time_day": "2025-09-27"},
            "metrics": {"clicks": "947", "impressions": "23241", "spend": "125.50"},
        }

        result = TikTokReportResource.transform_analytics_reports([nested_record])[0]

        expected = {
            "campaign_id": "123456",
            "stat_time_day": "2025-09-27",
            "clicks": "947",
            "impressions": "23241",
            "spend": "125.50",
        }

        assert result == expected

    @parameterized.expand(
        [
            ("no_incremental", False, None, 365),
            ("with_datetime", True, datetime.now() - timedelta(days=30), 30),
            ("with_date_string", True, (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"), 30),
            ("with_recent_date", True, datetime.now() - timedelta(days=2), 7),
            ("with_old_date", True, datetime.now() - timedelta(days=60), 60),
        ]
    )
    def test_get_incremental_date_range(self, name, should_use_incremental, last_value, expected_days_back):
        start_date, end_date = TikTokDateRangeManager.get_incremental_range(should_use_incremental, last_value)

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        days_diff = (end_dt - start_dt).days
        assert days_diff <= expected_days_back + 1

    def test_get_incremental_date_range_parse_error(self):
        start_date, end_date = TikTokDateRangeManager.get_incremental_range(True, "invalid_date")

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days_diff = (end_dt - start_dt).days

        assert days_diff <= 365

    @parameterized.expand(
        [
            (
                "single_chunk",
                (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                1,
            ),
            (
                "two_chunks",
                (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                2,
            ),
            (
                "three_chunks",
                (datetime.now() - timedelta(days=89)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                3,
            ),
            (
                "exact_boundary",
                (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                1,
            ),
        ]
    )
    def test_generate_date_chunks(self, name, start_date, end_date, chunk_days, expected_chunks):
        chunks = TikTokDateRangeManager.generate_chunks(start_date, end_date, chunk_days)

        assert len(chunks) == expected_chunks

        for i, (chunk_start, chunk_end) in enumerate(chunks):
            chunk_start_dt = datetime.strptime(chunk_start, "%Y-%m-%d")
            chunk_end_dt = datetime.strptime(chunk_end, "%Y-%m-%d")

            assert (chunk_end_dt - chunk_start_dt).days <= chunk_days

            if i < len(chunks) - 1:
                next_chunk_start = datetime.strptime(chunks[i + 1][0], "%Y-%m-%d")
                assert (next_chunk_start - chunk_end_dt).days == 1


class TestGetResource:
    """Test suite for resource configuration generation."""

    def setup_method(self):
        self.advertiser_id = "123456789"

    def test_get_tiktok_resource_unknown_endpoint(self):
        with pytest.raises(ValueError, match="Unknown endpoint: invalid_endpoint"):
            get_tiktok_resource("invalid_endpoint", self.advertiser_id, False)


class TestTikTokAdsSource:
    """Test suite for main TikTok Ads source function."""

    @parameterized.expand(
        [
            ("campaigns", False, None),
            ("ad_groups", False, None),
            ("ads", False, None),
            ("creative_videos", False, None),
            ("creative_images", False, None),
        ]
    )
    def test_tiktok_ads_source_entity_endpoints(self, endpoint, should_use_incremental, last_value):
        """Source returns a response with a callable items iterable for entity endpoints."""
        result = _drive(
            endpoint,
            always(_page_response(1, 1, [{"campaign_id": "123", "name": "Test Campaign"}])),
            should_use_incremental_field=should_use_incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.items is not None
        assert result.response.partition_count == 1

    @parameterized.expand(
        [
            ("campaign_report", False, None),
            ("ad_group_report", False, None),
            ("ad_report", False, None),
        ]
    )
    def test_tiktok_ads_source_report_endpoints_full_refresh(self, endpoint, should_use_incremental, last_value):
        """Source returns a response for report endpoints with full refresh."""
        result = _drive(
            endpoint,
            always(_page_response(1, 1, [{"campaign_id": "123", "clicks": "100"}])),
            should_use_incremental_field=should_use_incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.items is not None
        assert result.response.partition_count == 1

    @parameterized.expand(
        [
            ("campaign_report", True, datetime.now() - timedelta(days=5)),
            ("ad_group_report", True, (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")),
            ("ad_report", True, datetime.now() - timedelta(days=10)),
        ]
    )
    def test_tiktok_ads_source_report_endpoints_incremental(self, endpoint, should_use_incremental, last_value):
        """Source returns a response for report endpoints with incremental sync."""
        result = _drive(
            endpoint,
            always(_page_response(1, 1, [{"campaign_id": "123", "clicks": "100"}])),
            should_use_incremental_field=should_use_incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.items is not None
        assert result.response.partition_count == 1

    def test_tiktok_ads_source_invalid_endpoint(self):
        result = _drive("invalid_endpoint", [])

        assert isinstance(result.raised, KeyError)


class TestTikTokAdsResumeBehavior:
    """End-to-end resume behavior, driven through ``source_for_pipeline``."""

    def test_resume_uses_saved_cursor(self):
        """A saved cursor: the first request targets the saved page, not page 1."""
        result = _drive(
            "campaigns",
            [_page_response(page=2, total_pages=2, items=[{"campaign_id": "c2"}])],
            resume_state=TikTokAdsResumeConfig(page=2, chunk_index=0),
        )

        # Only one request issued — initial page 1 is skipped.
        assert len(result.requests) == 1
        assert result.paths[0].endswith("/campaign/get/")
        assert result.params("page") == ["2"]

    def test_stale_resume_state_is_discarded(self):
        """A saved chunk_index beyond the current chunk list falls back to a fresh run."""
        result = _drive(
            "campaigns",
            [_page_response(page=1, total_pages=1, items=[{"campaign_id": "c1"}])],
            resume_state=TikTokAdsResumeConfig(page=4, chunk_index=99),
        )

        # Falls back to a fresh run that requests page 1.
        assert result.params("page")[0] == "1"


class TestTikTokAdsReportChunkResumeBehavior:
    """End-to-end resume behavior for chunked report endpoints."""

    def _report_chunks(self) -> list[dict[str, Any]]:
        """Build deterministic chunks using the production setup code.

        Uses a 58-day span and 29-day chunk size to produce exactly two
        29-day chunks. The test then extends this to three chunks below
        where multi-chunk skip/resume behavior is exercised.
        """
        base = get_tiktok_resource("campaign_report", ADVERTISER_ID, True)
        return TikTokReportResource.create_chunked_resources(
            base,
            start_date="2024-01-01",
            end_date="2024-03-30",  # 90 days -> 4 chunks at 29-day chunk size
            advertiser_id=ADVERTISER_ID,
        )

    def _run_report(self, script: Script, resume_state: TikTokAdsResumeConfig | None = None) -> DriveResult:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.tiktok_ads.TikTokReportResource.setup_report_resources",
            return_value=self._report_chunks(),
        ):
            return _drive("campaign_report", script, resume_state=resume_state, should_use_incremental_field=True)

    def test_resume_from_middle_chunk_skips_earlier_and_runs_later_chunks_fresh(self):
        """Resuming into a non-first chunk:
        - chunks before the resumed one issue no HTTP requests,
        - the first request for the resumed chunk targets the saved page,
        - chunks after it start fresh at page 1.
        """
        chunks = self._report_chunks()
        assert len(chunks) >= 3, "need at least 3 chunks to exercise skip/resume/fresh"

        resume_idx = 1
        chunk_r = chunks[resume_idx]
        chunk_r_start = chunk_r["endpoint"]["params"]["start_date"]
        chunk_r_end = chunk_r["endpoint"]["params"]["end_date"]

        # Resumed chunk: single terminal page at page=3. Subsequent chunks:
        # each resolves in one page.
        responses: list[ScriptedResponse] = [_page_response(page=3, total_pages=3, items=[{"campaign_id": "c-resume"}])]
        responses.extend(
            _page_response(page=1, total_pages=1, items=[{"campaign_id": f"c{i}"}])
            for i in range(resume_idx + 1, len(chunks))
        )
        result = self._run_report(
            responses,
            resume_state=TikTokAdsResumeConfig(
                page=3,
                chunk_index=resume_idx,
                chunk_start_date=chunk_r_start,
                chunk_end_date=chunk_r_end,
            ),
        )

        # One request for the resumed chunk + one for each chunk after it.
        assert len(result.requests) == 1 + (len(chunks) - resume_idx - 1)

        resumed_request = result.requests[0]
        assert resumed_request.param("page") == "3"
        assert resumed_request.param("start_date") == chunk_r_start
        assert resumed_request.param("end_date") == chunk_r_end

        for req, chunk in zip(result.requests[1:], chunks[resume_idx + 1 :], strict=True):
            assert req.param("page") == "1"
            assert req.param("start_date") == chunk["endpoint"]["params"]["start_date"]

    def test_resume_falls_back_when_saved_chunk_dates_no_longer_match(self):
        """If the saved chunk's date range doesn't exist in the current chunk
        list (e.g. ``datetime.now()`` advanced and shifted the window), discard
        the state and start fresh from chunk 0, page 1."""
        chunks = self._report_chunks()
        responses = [
            _page_response(page=1, total_pages=1, items=[{"campaign_id": f"c{i}"}]) for i in range(len(chunks))
        ]
        result = self._run_report(
            responses,
            resume_state=TikTokAdsResumeConfig(
                page=5,
                chunk_index=1,
                chunk_start_date="1999-12-01",  # definitely not in any current chunk
                chunk_end_date="1999-12-29",
            ),
        )

        assert len(result.requests) == len(chunks)
        for req in result.requests:
            assert req.param("page") == "1"

    def test_fresh_run_save_state_includes_chunk_dates(self):
        """Fresh chunked run: save_state calls include the chunk's
        ``(start_date, end_date)`` so the saved state is stable across
        boundary-shifting re-runs."""
        chunks = self._report_chunks()
        chunk0_start = chunks[0]["endpoint"]["params"]["start_date"]
        chunk0_end = chunks[0]["endpoint"]["params"]["end_date"]

        responses: list[ScriptedResponse] = [
            # chunk 0: two pages (save expected after page 1, not after page 2).
            _page_response(page=1, total_pages=2, items=[{"campaign_id": "c0a"}]),
            _page_response(page=2, total_pages=2, items=[{"campaign_id": "c0b"}]),
        ]
        # Remaining chunks each resolve in a single page (no saves).
        responses.extend(
            _page_response(page=1, total_pages=1, items=[{"campaign_id": f"c{i}"}]) for i in range(1, len(chunks))
        )
        result = self._run_report(responses)

        assert len(result.saved_states) == 1
        saved: TikTokAdsResumeConfig = result.saved_states[0]
        assert saved.chunk_index == 0
        assert saved.page == 2
        assert saved.chunk_start_date == chunk0_start
        assert saved.chunk_end_date == chunk0_end


class TestTikTokAdsTransientErrorRetry:
    """TikTok signals rate limits with HTTP 200 + a body `code`, so the request has to be
    reissued from inside the rest client — the paginator can't re-request a page."""

    def test_persistent_qps_limit_surfaces_transient_message(self):
        result = _drive(
            "campaigns",
            always(_make_response({"code": 40100, "message": "App reaches the QPS limit 10, current QPS is 11."})),
        )

        assert isinstance(result.raised, RESTClientRetryableError)
        assert "rate-limiting" in str(result.raised)

    def test_non_retryable_code_is_not_reissued(self):
        result = _drive(
            "campaigns",
            [
                _make_response(
                    {"code": 40001, "message": "advertiser does not grant you /file/video/ad/search/:GET permission"}
                )
            ],
        )

        assert isinstance(result.raised, ValueError)
        assert "non-retryable" in str(result.raised)
        assert len(result.requests) == 1
