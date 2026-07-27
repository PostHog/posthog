import datetime as dt
from collections.abc import Iterable

import pytest
from unittest.mock import MagicMock, Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads import (
    BING_ADS_REPORT_RETENTION,
    bing_ads_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.schemas import BingAdsResource
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.utils import (
    BingAdsResumeConfig,
    download_and_extract_report_csv,
    fetch_data_in_yearly_chunks,
    parse_csv_to_dicts,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.types import IncrementalFieldType


def _mock_resumable_manager(
    can_resume: bool = False, load_state_return: BingAdsResumeConfig | None = None
) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = load_state_return
    return manager


class TestBingAdsHelperFunctions:
    """Test helper functions in bing_ads.py and utils.py."""

    def test_parse_csv_to_dicts_valid_data(self):
        """Test parsing valid CSV report data."""
        csv_data = """TimePeriod,CampaignId,CampaignName,Impressions,Clicks
2024-01-01,123,Test Campaign,1000,50
2024-01-02,123,Test Campaign,1200,60"""

        result = parse_csv_to_dicts(csv_data)

        assert len(result) == 2
        assert result[0]["TimePeriod"] == "2024-01-01"
        assert result[0]["CampaignId"] == "123"
        assert result[0]["Impressions"] == "1000"
        assert result[1]["TimePeriod"] == "2024-01-02"

    def test_parse_csv_to_dicts_with_null_values(self):
        """Test parsing CSV with null values (--) and empty strings."""
        csv_data = """TimePeriod,CampaignId,CampaignName,Impressions,Clicks
2024-01-01,123,Test Campaign,--,
2024-01-02,456,--,1000,50"""

        result = parse_csv_to_dicts(csv_data)

        assert len(result) == 2
        assert result[0]["Impressions"] is None
        assert result[0]["Clicks"] is None
        assert result[1]["CampaignName"] is None

    def test_fetch_data_in_yearly_chunks_single_chunk(self):
        """Test fetching data within a single year."""
        mock_client = Mock()
        mock_client.get_data_by_resource.return_value = iter([[{"CampaignId": "123", "Clicks": "100"}]])

        start_date = dt.date(2024, 1, 1)
        end_date = dt.date(2024, 6, 30)

        manager = _mock_resumable_manager()
        result = list(
            fetch_data_in_yearly_chunks(
                client=mock_client,
                resource=BingAdsResource.CAMPAIGN_PERFORMANCE_REPORT,
                account_id=12345,
                start_date=start_date,
                end_date=end_date,
                resumable_source_manager=manager,
            )
        )

        assert len(result) == 1
        assert result[0][0]["CampaignId"] == "123"
        mock_client.get_data_by_resource.assert_called_once()
        manager.save_state.assert_called_once_with(
            BingAdsResumeConfig(next_start_date="2024-07-01", end_date=end_date.isoformat())
        )

    def test_fetch_data_in_yearly_chunks_multiple_chunks(self):
        """Test fetching data across multiple years."""
        mock_client = Mock()
        mock_client.get_data_by_resource.side_effect = [
            iter([[{"year": "2023"}]]),
            iter([[{"year": "2024"}]]),
            iter([[{"year": "2025"}]]),
        ]

        start_date = dt.date(2023, 1, 1)
        end_date = dt.date(2025, 6, 30)

        manager = _mock_resumable_manager()
        result = list(
            fetch_data_in_yearly_chunks(
                client=mock_client,
                resource=BingAdsResource.CAMPAIGN_PERFORMANCE_REPORT,
                account_id=12345,
                start_date=start_date,
                end_date=end_date,
                resumable_source_manager=manager,
            )
        )

        assert len(result) == 3
        assert mock_client.get_data_by_resource.call_count == 3
        # One checkpoint after each chunk
        assert manager.save_state.call_count == 3
        first_checkpoint = manager.save_state.call_args_list[0].args[0]
        assert first_checkpoint == BingAdsResumeConfig(next_start_date="2024-01-02", end_date=end_date.isoformat())

    def test_fetch_data_in_yearly_chunks_same_day(self):
        mock_client = Mock()
        mock_client.get_data_by_resource.return_value = iter([[{"CampaignId": "123", "Clicks": "100"}]])

        today = dt.date(2026, 4, 10)

        manager = _mock_resumable_manager()
        result = list(
            fetch_data_in_yearly_chunks(
                client=mock_client,
                resource=BingAdsResource.CAMPAIGN_PERFORMANCE_REPORT,
                account_id=12345,
                start_date=today,
                end_date=today,
                resumable_source_manager=manager,
            )
        )

        assert len(result) == 1
        assert result[0][0]["CampaignId"] == "123"
        mock_client.get_data_by_resource.assert_called_once_with(
            resource=BingAdsResource.CAMPAIGN_PERFORMANCE_REPORT,
            account_id=12345,
            start_date=dt.datetime.combine(today, dt.time.min),
            end_date=dt.datetime.combine(today, dt.time.max),
        )

    def test_fetch_data_in_yearly_chunks_failure_fails_sync(self):
        """A chunk failure propagates so the sync fails rather than completing with missing data.

        The checkpoint must not advance past the failed chunk, so a resume re-attempts it
        instead of leaving a permanent gap in the data.
        """
        mock_client = Mock()
        mock_client.get_data_by_resource.side_effect = [
            iter([[{"year": "2023"}]]),
            Exception("API Error"),
            iter([[{"year": "2025"}]]),
        ]

        start_date = dt.date(2023, 1, 1)
        end_date = dt.date(2025, 6, 30)

        manager = _mock_resumable_manager()

        result: list[list[dict]] = []
        with pytest.raises(Exception, match="API Error"):
            for page in fetch_data_in_yearly_chunks(
                client=mock_client,
                resource=BingAdsResource.CAMPAIGN_PERFORMANCE_REPORT,
                account_id=12345,
                start_date=start_date,
                end_date=end_date,
                resumable_source_manager=manager,
            ):
                result.append(page)

        # Only the first chunk was yielded before the failure aborted the sync
        assert result == [[{"year": "2023"}]]
        # Checkpoint advanced only past the successful first chunk, not the failed one
        manager.save_state.assert_called_once_with(
            BingAdsResumeConfig(next_start_date="2024-01-02", end_date=end_date.isoformat())
        )

    def test_fetch_data_in_yearly_chunks_skips_out_of_retention_chunk(self):
        # A chunk rejected with InvalidCustomDateRangeEnd (older than Bing's 36-month retention) is
        # skipped and its checkpoint advanced, so the sync keeps the in-retention chunks instead of
        # aborting. Any other error stays fatal — see test_fetch_data_in_yearly_chunks_failure_fails_sync.
        mock_client = Mock()
        mock_client.get_data_by_resource.side_effect = [
            Exception(
                "Failed to generate campaign_performance_report report: WebFault: Server raised fault: "
                "'Invalid client data...' (InvalidCustomDateRangeEnd: The specified report time contains "
                "an invalid custom date range end.)"
            ),
            iter([[{"year": "2024"}]]),
            iter([[{"year": "2025"}]]),
        ]

        start_date = dt.date(2023, 1, 1)
        end_date = dt.date(2025, 6, 30)

        manager = _mock_resumable_manager()
        result = list(
            fetch_data_in_yearly_chunks(
                client=mock_client,
                resource=BingAdsResource.CAMPAIGN_PERFORMANCE_REPORT,
                account_id=12345,
                start_date=start_date,
                end_date=end_date,
                resumable_source_manager=manager,
            )
        )

        assert result == [[{"year": "2024"}], [{"year": "2025"}]]
        # The skipped chunk still advances the checkpoint, so all three chunks are accounted for
        assert manager.save_state.call_count == 3

    def test_download_and_extract_report_csv_no_file_returns_empty(self):
        # Bing returns no file (download_file -> None) when a report has zero rows for the range;
        # treat it as an empty report instead of crashing on Path(None).
        manager = Mock()
        manager.download_file.return_value = None

        result = download_and_extract_report_csv(
            reporting_service_manager=manager,
            report_request=Mock(),
            report_type="CampaignPerformanceReportRequest",
            account_id=12345,
        )

        assert result == ""

    def test_fetch_data_in_yearly_chunks_resumes_from_saved_state(self):
        """When resume state exists, the loop starts at the saved chunk boundary and does not re-fetch earlier chunks."""
        mock_client = Mock()
        mock_client.get_data_by_resource.return_value = iter([[{"year": "2025"}]])

        manager = _mock_resumable_manager(
            can_resume=True,
            load_state_return=BingAdsResumeConfig(next_start_date="2025-01-01", end_date="2025-06-30"),
        )

        result = list(
            fetch_data_in_yearly_chunks(
                client=mock_client,
                resource=BingAdsResource.CAMPAIGN_PERFORMANCE_REPORT,
                account_id=12345,
                # Initial start/end should be overridden by saved state
                start_date=dt.date(2023, 1, 1),
                end_date=dt.date(2030, 1, 1),
                resumable_source_manager=manager,
            )
        )

        assert len(result) == 1
        mock_client.get_data_by_resource.assert_called_once_with(
            resource=BingAdsResource.CAMPAIGN_PERFORMANCE_REPORT,
            account_id=12345,
            start_date=dt.datetime.combine(dt.date(2025, 1, 1), dt.time.min),
            end_date=dt.datetime.combine(dt.date(2025, 6, 30), dt.time.max),
        )


class TestBingAdsSource:
    """Test suite for main Bing Ads source function."""

    def setup_method(self):
        """Set up test fixtures."""
        self.account_id = "12345"
        self.access_token = "test_access_token"
        self.refresh_token = "test_refresh_token"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.BingAdsClient")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.integrations")
    def test_bing_ads_source_campaigns(self, mock_integrations, mock_client_class):
        """Test source function for campaigns (non-report endpoint)."""
        mock_integrations.BING_ADS_DEVELOPER_TOKEN = "test_dev_token"

        mock_client = Mock()
        mock_client.get_data_by_resource.return_value = iter([[{"Id": "123", "Name": "Test Campaign"}]])
        mock_client_class.return_value = mock_client

        result = bing_ads_source(
            account_id=self.account_id,
            resource_name="campaigns",
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            resumable_source_manager=_mock_resumable_manager(),
            should_use_incremental_field=False,
        )

        assert result.name == "campaigns"
        assert result.primary_keys == ["Id"]
        assert result.partition_mode is None

        items = result.items()
        assert isinstance(items, Iterable)
        data = list(items)
        assert len(data) == 1
        assert data[0][0]["Id"] == "123"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.fetch_data_in_yearly_chunks"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.BingAdsClient")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.integrations")
    def test_bing_ads_source_report_full_refresh(self, mock_integrations, mock_client_class, mock_fetch_chunks):
        """Test source function for report endpoint with full refresh."""
        mock_integrations.BING_ADS_DEVELOPER_TOKEN = "test_dev_token"

        mock_client = Mock()
        mock_client_class.return_value = mock_client

        mock_fetch_chunks.return_value = iter([[{"CampaignId": "123", "Clicks": "100"}]])

        manager = _mock_resumable_manager()
        result = bing_ads_source(
            account_id=self.account_id,
            resource_name="campaign_performance_report",
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            resumable_source_manager=manager,
            should_use_incremental_field=False,
        )

        assert result.name == "campaign_performance_report"
        assert result.primary_keys == ["CampaignId", "TimePeriod"]
        assert result.partition_mode == "datetime"

        items = result.items()
        assert isinstance(items, Iterable)
        data = list(items)
        assert len(data) == 1

        # Manager is threaded through to the chunk fetcher
        assert mock_fetch_chunks.call_args.kwargs["resumable_source_manager"] is manager

    @parameterized.expand(
        [
            ("with_datetime", dt.datetime(2024, 6, 15, 14, 30)),
            ("with_date", dt.date(2024, 6, 15)),
            ("with_string", "2024-06-15T14:30:00"),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.fetch_data_in_yearly_chunks"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.BingAdsClient")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.integrations")
    def test_bing_ads_source_report_incremental(
        self, _name, last_value, mock_integrations, mock_client_class, mock_fetch_chunks
    ):
        """Test source function for report endpoint with incremental sync."""
        mock_integrations.BING_ADS_DEVELOPER_TOKEN = "test_dev_token"

        mock_client = Mock()
        mock_client_class.return_value = mock_client

        mock_fetch_chunks.return_value = iter([[{"CampaignId": "123", "Clicks": "100"}]])

        manager = _mock_resumable_manager()
        result = bing_ads_source(
            account_id=self.account_id,
            resource_name="campaign_performance_report",
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            incremental_field="TimePeriod",
            incremental_field_type=IncrementalFieldType.Date,
            db_incremental_field_last_value=last_value,
        )

        assert result.name == "campaign_performance_report"
        items = result.items()
        assert isinstance(items, Iterable)
        data = list(items)
        assert len(data) == 1

        mock_fetch_chunks.assert_called_once()
        call_args = mock_fetch_chunks.call_args
        assert call_args.kwargs["start_date"] <= dt.date.today()
        assert call_args.kwargs["resumable_source_manager"] is manager

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.fetch_data_in_yearly_chunks"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.BingAdsClient")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.integrations")
    def test_bing_ads_source_first_sync_caps_lookback_to_retention(
        self, mock_integrations, mock_client_class, mock_fetch_chunks
    ):
        # On the first sync (no prior incremental value) the lookback is capped to Bing's 36-month
        # retention window rather than reaching years back for data Bing no longer retains.
        mock_integrations.BING_ADS_DEVELOPER_TOKEN = "test_dev_token"
        mock_client_class.return_value = Mock()
        mock_fetch_chunks.return_value = iter([[{"CampaignId": "123"}]])

        result = bing_ads_source(
            account_id=self.account_id,
            resource_name="campaign_performance_report",
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            resumable_source_manager=_mock_resumable_manager(),
            should_use_incremental_field=True,
            incremental_field="TimePeriod",
            incremental_field_type=IncrementalFieldType.Date,
            db_incremental_field_last_value=None,
        )
        items = result.items()
        assert isinstance(items, Iterable)
        list(items)

        assert mock_fetch_chunks.call_args.kwargs["start_date"] == dt.date.today() - BING_ADS_REPORT_RETENTION

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.integrations")
    def test_bing_ads_source_missing_developer_token(self, mock_integrations):
        """Test source function raises error when developer token is missing."""
        mock_integrations.BING_ADS_DEVELOPER_TOKEN = None

        result = bing_ads_source(
            account_id=self.account_id,
            resource_name="campaigns",
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            resumable_source_manager=_mock_resumable_manager(),
        )

        with pytest.raises(ValueError, match="Bing Ads developer token not configured"):
            items = result.items()
            assert isinstance(items, Iterable)
            list(items)

    @parameterized.expand(
        [
            ("missing_client_id", "", "test_client_secret"),
            ("missing_client_secret", "test_client_id", ""),
            ("both_missing", "", ""),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.integrations")
    def test_bing_ads_source_missing_oauth_app_credentials(self, _name, client_id, client_secret, mock_integrations):
        """An empty OAuth app client id/secret raises a deterministic error instead of a doomed token request.

        Without the guard the SDK posts a token request omitting client_id and Microsoft returns the opaque
        AADSTS900144, which was being mis-surfaced as a customer "reconnect your integration" error.
        """
        mock_integrations.BING_ADS_DEVELOPER_TOKEN = "test_dev_token"
        mock_integrations.BING_ADS_CLIENT_ID = client_id
        mock_integrations.BING_ADS_CLIENT_SECRET = client_secret

        result = bing_ads_source(
            account_id=self.account_id,
            resource_name="campaigns",
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            resumable_source_manager=_mock_resumable_manager(),
        )

        with pytest.raises(ValueError, match="Bing Ads OAuth application credentials not configured"):
            items = result.items()
            assert isinstance(items, Iterable)
            list(items)

    @parameterized.expand(
        [
            ("account_number", "F118FDGN"),
            ("alphanumeric", "ABC123"),
            ("empty", ""),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.BingAdsClient")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.integrations")
    def test_bing_ads_source_non_numeric_account_id(self, _name, account_id, mock_integrations, mock_client_class):
        """A non-numeric account ID raises a deterministic, non-retryable error instead of a bare int() crash."""
        mock_integrations.BING_ADS_DEVELOPER_TOKEN = "test_dev_token"

        result = bing_ads_source(
            account_id=account_id,
            resource_name="campaigns",
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            resumable_source_manager=_mock_resumable_manager(),
        )

        with pytest.raises(ValueError, match="Bing Ads Account ID must be numeric"):
            items = result.items()
            assert isinstance(items, Iterable)
            list(items)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.BingAdsClient")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.bing_ads.integrations")
    def test_bing_ads_source_incremental_missing_field(self, mock_integrations, mock_client_class):
        """Test source function raises error when incremental field is missing."""
        mock_integrations.BING_ADS_DEVELOPER_TOKEN = "test_dev_token"

        result = bing_ads_source(
            account_id=self.account_id,
            resource_name="campaign_performance_report",
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            resumable_source_manager=_mock_resumable_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=dt.date(2024, 1, 1),
        )

        with pytest.raises(
            ValueError, match="incremental_field and incremental_field_type required for incremental sync"
        ):
            items = result.items()
            assert isinstance(items, Iterable)
            list(items)
