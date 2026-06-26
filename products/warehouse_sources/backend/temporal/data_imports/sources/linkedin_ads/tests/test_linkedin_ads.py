import typing
import datetime as dt
from collections.abc import Iterable
from functools import partial

import pytest
from unittest import mock

from django.db import OperationalError

import pyarrow as pa
from parameterized import parameterized

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client import (
    LinkedinAdsDailyRateLimitError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.linkedin_ads import (
    INITIAL_ANALYTICS_LOOKBACK_DAYS,
    LinkedInAdsResumeConfig,
    LinkedinAdsSchema,
    _convert_date_object_to_date,
    _convert_timestamp_to_date,
    _extract_type_and_id_from_urn,
    _flatten_linkedin_record,
    _get_integration,
    linkedin_ads_client,
    linkedin_ads_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.source import LinkedInAdsSource
from products.warehouse_sources.backend.types import IncrementalFieldType


def _make_resume_manager(can_resume: bool = False, loaded_state: object = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = loaded_state
    return manager


def _small_batcher_factory(chunk_size: int):
    """Return a factory that builds a real Batcher with a tiny chunk_size for tests that
    need to drive the chunk-boundary / resume-token interaction deterministically."""
    return partial(Batcher, chunk_size=chunk_size)


class TestLinkedinAdsHelperFunctions:
    """Test helper functions in linkedin_ads.py."""

    def test_extract_type_and_id_from_urn_valid(self):
        """Test extracting ID and type from valid LinkedIn URN."""
        urn = "urn:li:sponsoredCampaign:12345678"
        result = _extract_type_and_id_from_urn(urn)

        assert result == ("sponsoredCampaign", 12345678)

    @pytest.mark.parametrize(
        "malformed",
        [
            "not-a-urn",
            "urn:li:sponsoredCampaign",  # missing id segment
            "urn:li:sponsoredCampaign:not-an-int",
            "urn:li:sponsoredCampaign:123:extra",  # too many segments
            "",
        ],
    )
    def test_extract_type_and_id_from_urn_malformed_returns_none(self, malformed):
        """Bad URNs return None instead of raising."""
        assert _extract_type_and_id_from_urn(malformed) is None

    def test_convert_date_object_to_date_valid(self):
        """Test converting LinkedIn date object to Python date."""
        date_obj = {"year": 2024, "month": 3, "day": 15}
        result = _convert_date_object_to_date(date_obj)

        assert result == dt.date(2024, 3, 15)

    def test_convert_date_object_to_date_invalid(self):
        """Test converting invalid date object returns None."""
        invalid_cases = [
            {"year": 2024, "month": 3},  # Missing day
            {},  # Empty dict
            None,
        ]

        for invalid_obj in invalid_cases:
            result = _convert_date_object_to_date(invalid_obj)
            assert result is None

    def test_convert_timestamp_to_date_valid(self):
        """Test converting LinkedIn timestamp to date."""
        timestamp_ms = 1709654400000
        last_modified = {"time": timestamp_ms}
        result = _convert_timestamp_to_date(last_modified)

        assert str(result) == "2024-03-05"


class TestFlattenLinkedinRecord:
    """Test _flatten_linkedin_record function."""

    def test_flatten_date_range(self):
        """Test flattening dateRange field."""
        record = {
            "dateRange": {"start": {"year": 2024, "month": 1, "day": 1}, "end": {"year": 2024, "month": 1, "day": 31}}
        }
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["dateRange"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=True,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)
        assert result is not None

        assert result["date_start"] == dt.date(2024, 1, 1)
        assert result["date_end"] == dt.date(2024, 1, 31)

    def test_flatten_urn_columns(self):
        """Test flattening URN columns."""
        record = {
            "campaignGroup": "urn:li:sponsoredCampaignGroup:123456789",
            "campaign": "urn:li:sponsoredCampaign:987654321",
        }
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["campaignGroup", "campaign"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)
        assert result is not None

        assert result["campaign_group_id"] == 123456789
        assert result["campaign_id"] == 987654321

    def test_flatten_integer_fields(self):
        """Test conversion of integer fields."""
        record = {"impressions": 1000, "clicks": 50}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["impressions", "clicks"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=True,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)
        assert result is not None

        assert result["impressions"] == 1000
        assert result["clicks"] == 50

    @pytest.mark.parametrize(
        "field_name, raw_value, expected",
        [
            ("costInUsd", "25.50", 25.50),
            ("costInLocalCurrency", "30.75", 30.75),
            ("conversionValueInLocalCurrency", "12.34", 12.34),
        ],
    )
    def test_flatten_float_fields(self, field_name: str, raw_value: str, expected: float):
        record = {field_name: raw_value}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=[field_name],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=True,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)
        assert result is not None

        assert result[field_name] == expected

    def test_flatten_change_audit_stamps(self):
        """Test flattening changeAuditStamps field."""
        record = {"changeAuditStamps": {"created": {"time": 1709654400000}, "lastModified": {"time": 1709740800000}}}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["changeAuditStamps"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)
        assert result is not None

        assert str(result["created_time"]) == "2024-03-05"
        assert str(result["last_modified_time"]) == "2024-03-06"

    def test_flatten_pivot_values(self):
        """Test flattening pivotValues field."""
        record = {"pivotValues": ["urn:li:sponsoredCampaign:555666777", "urn:li:sponsoredAccount:888999000"]}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["pivotValues"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=True,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)
        assert result is not None

        assert result["campaign_id"] == 555666777
        assert result["account_id"] == 888999000

    def test_flatten_complex_objects_to_json(self):
        """Test that complex objects are passed through as-is from API."""
        record = {"targetingCriteria": {"locations": ["US", "CA"], "ages": {"min": 25, "max": 65}}}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["targetingCriteria"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)
        assert result is not None

        # API returns dict objects, pipeline handles JSON conversion later
        assert result["targetingCriteria"]["locations"] == ["US", "CA"]
        assert result["targetingCriteria"]["ages"]["min"] == 25

    def test_flatten_missing_field_returns_none(self):
        """Test missing fields return None."""
        record: dict[str, typing.Any] = {}  # Empty record
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["missing_field"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)
        assert result is not None

        assert result is not None
        assert result["missing_field"] is None

    def test_flatten_creative_id_urn_extracted_to_int(self):
        """Creative `id` URN → int, so it joins with `creative_id` in creative_stats."""
        record = {"id": "urn:li:sponsoredCreative:147756353"}
        schema = LinkedinAdsSchema(
            name="creatives",
            primary_keys=["id"],
            field_names=["id"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)
        assert result is not None

        assert result is not None
        assert result["id"] == 147756353
        assert isinstance(result["id"], int)

    def test_flatten_drops_record_when_pk_urn_is_malformed(self):
        """Malformed PK URN → return None so the caller drops the row."""
        record = {"id": "urn:li:sponsoredCreative:not-an-int"}
        schema = LinkedinAdsSchema(
            name="creatives",
            primary_keys=["id"],
            field_names=["id"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert result is None

    def test_flatten_created_at_long_to_virtual_columns(self):
        """`createdAt` / `lastModifiedAt` longs → `created_time` / `last_modified_time` virtual cols."""
        # 1625668063000 ms = 2021-07-07 (UTC)
        record = {"createdAt": 1625668063000, "lastModifiedAt": 1656592925000}
        schema = LinkedinAdsSchema(
            name="creatives",
            primary_keys=[],
            field_names=["createdAt", "lastModifiedAt"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)
        assert result is not None

        assert result is not None
        assert result["created_time"] == dt.date(2021, 7, 7)
        assert result["last_modified_time"] == dt.date(2022, 6, 30)

    def test_flatten_created_at_missing_yields_none(self):
        """Missing/non-int `createdAt` → virtual column is None."""
        record: dict[str, typing.Any] = {"createdAt": None}
        schema = LinkedinAdsSchema(
            name="creatives",
            primary_keys=[],
            field_names=["createdAt"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)
        assert result is not None

        assert result is not None
        assert result["created_time"] is None


@mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.linkedin_ads.Integration")
class TestLinkedinAdsClientFunction:
    """Test linkedin_ads_client function."""

    def test_linkedin_ads_client_no_access_token(self, mock_integration_model):
        """Test client creation with no access token raises error."""
        mock_integration = mock.MagicMock()
        mock_integration.access_token = None
        mock_integration.sensitive_config = {}  # no refresh token → not expired, skips refresh
        mock_integration_model.objects.get.return_value = mock_integration

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")

        with pytest.raises(ValueError, match="LinkedIn Ads integration does not have an access token"):
            linkedin_ads_client(config, team_id=789)

    def test_linkedin_ads_client_refreshes_stale_db_connection_before_query(self, mock_integration_model, monkeypatch):
        # The ORM read runs lazily inside `get_rows` on a worker thread whose pooled
        # Django connection may have been closed server-side, surfacing as
        # `OperationalError: the connection is closed`. We must drop the stale
        # connection before querying, so the read happens on a fresh connection.
        calls: list[str] = []

        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.linkedin_ads.close_old_connections",
            lambda: calls.append("close_old_connections"),
        )

        mock_integration = mock.MagicMock()
        mock_integration.access_token = "token"
        mock_integration.sensitive_config = {}  # no refresh token → not expired, skips refresh

        def fake_get(*args, **kwargs):
            calls.append("Integration.objects.get")
            return mock_integration

        mock_integration_model.objects.get.side_effect = fake_get

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        linkedin_ads_client(config, team_id=789)

        assert calls == ["close_old_connections", "Integration.objects.get"]


_INTEGRATION_GET_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.linkedin_ads.Integration.objects.get"
)
_CLOSE_CONNECTIONS_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.linkedin_ads.close_old_connections"
)
_SLEEP_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.linkedin_ads.time.sleep"


class TestGetIntegrationDbResilience:
    def test_retries_on_dropped_connection_then_succeeds(self):
        integration = object()
        get = mock.Mock(side_effect=[OperationalError("server closed the connection unexpectedly"), integration])

        with (
            mock.patch(_INTEGRATION_GET_PATH, get),
            mock.patch(_CLOSE_CONNECTIONS_PATH) as close,
            mock.patch(_SLEEP_PATH),
        ):
            result = _get_integration(integration_id=1, team_id=2)

        assert result is integration
        assert get.call_count == 2
        # Evicted up front, then again after the failed query marked the connection unusable.
        assert close.call_count == 2

    def test_rides_out_pool_wait_timeout_then_succeeds(self):
        integration = object()
        get = mock.Mock(
            side_effect=[
                OperationalError("query_wait_timeout"),
                OperationalError("query_wait_timeout"),
                integration,
            ]
        )

        with (
            mock.patch(_INTEGRATION_GET_PATH, get),
            mock.patch(_CLOSE_CONNECTIONS_PATH),
            mock.patch(_SLEEP_PATH) as sleep,
        ):
            result = _get_integration(integration_id=1, team_id=2)

        assert result is integration
        assert get.call_count == 3
        # Backoff grows per attempt per `min(2 * attempt, 30)`: 2s after the 1st failure, 4s after the 2nd.
        assert sleep.call_args_list == [mock.call(2), mock.call(4)]

    def test_reraises_after_exhausting_attempts(self):
        get = mock.Mock(side_effect=OperationalError("query_wait_timeout"))

        with (
            mock.patch(_INTEGRATION_GET_PATH, get),
            mock.patch(_CLOSE_CONNECTIONS_PATH),
            mock.patch(_SLEEP_PATH) as sleep,
        ):
            with pytest.raises(OperationalError):
                _get_integration(integration_id=1, team_id=2)

        # Bounded attempts: it gives up rather than looping forever, leaving Temporal to retry the activity.
        assert get.call_count == 4
        # Backed off between each attempt (2s, 4s, 6s) but not after the final attempt that re-raises.
        assert sleep.call_args_list == [mock.call(2), mock.call(4), mock.call(6)]

    def test_missing_integration_is_not_retried(self):
        get = mock.Mock(side_effect=Integration.DoesNotExist())

        with mock.patch(_INTEGRATION_GET_PATH, get), mock.patch(_CLOSE_CONNECTIONS_PATH), mock.patch(_SLEEP_PATH):
            with pytest.raises(Integration.DoesNotExist):
                _get_integration(integration_id=1, team_id=2)

        # A deleted integration row is non-retryable — don't mask it as a transient drop.
        assert get.call_count == 1


@mock.patch(
    "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.linkedin_ads.OauthIntegration"
)
@mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.linkedin_ads.Integration")
class TestLinkedinAdsClientTokenRefresh:
    """Token refresh behaviour of linkedin_ads_client."""

    config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")

    @parameterized.expand(
        [
            ("expired_token_is_refreshed", True),
            ("valid_token_is_not_refreshed", False),
        ]
    )
    def test_refreshes_only_when_token_is_expired(self, mock_integration_model, mock_oauth_cls, _name, token_expired):
        integration = mock.MagicMock()
        integration.access_token = "refreshed-token"
        integration.errors = ""
        mock_integration_model.objects.get.return_value = integration

        oauth = mock_oauth_cls.return_value
        oauth.access_token_expired.return_value = token_expired

        client = linkedin_ads_client(self.config, team_id=789)

        if token_expired:
            oauth.refresh_access_token.assert_called_once()
        else:
            oauth.refresh_access_token.assert_not_called()
        assert client.access_token == "refreshed-token"

    def test_failed_refresh_raises_non_retryable_message(self, mock_integration_model, mock_oauth_cls):
        integration = mock.MagicMock()
        integration.access_token = "stale-token"
        integration.errors = ERROR_TOKEN_REFRESH_FAILED
        mock_integration_model.objects.get.return_value = integration

        oauth = mock_oauth_cls.return_value
        oauth.access_token_expired.return_value = True

        with pytest.raises(Exception) as exc_info:
            linkedin_ads_client(self.config, team_id=789)

        message = str(exc_info.value)
        assert "Failed to refresh token for LinkedIn Ads integration" in message
        # The message must be classified non-retryable so a dead token stops the sync instead of looping.
        patterns = LinkedInAdsSource().get_non_retryable_errors()
        assert any(pattern in message for pattern in patterns)


@mock.patch(
    "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.linkedin_ads.linkedin_ads_client"
)
class TestLinkedinAdsSource:
    """Test linkedin_ads_source function."""

    def test_linkedin_ads_source_with_incremental(self, mock_client_func):
        """Test linkedin_ads_source with incremental field."""
        mock_client = mock.MagicMock()
        # Analytics endpoints are single-shot: one page, no next_page_token.
        mock_client.get_data_by_resource.return_value = [
            ([{"impressions": 1000, "dateRange": {"start": {"year": 2024, "month": 1, "day": 1}}}], None)
        ]
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager()

        result = linkedin_ads_source(
            config=config,
            resource_name="campaign_stats",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
            should_use_incremental_field=True,
            incremental_field="date_start",
            incremental_field_type=IncrementalFieldType.Date,
            db_incremental_field_last_value=dt.date(2024, 1, 1),
        )

        # Process the rows to trigger the client call
        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)
        # One final-flush pa.Table containing the single row.
        assert len(rows) == 1
        assert isinstance(rows[0], pa.Table)
        assert rows[0].num_rows == 1

        # Verify client was called with correct date parameters
        mock_client.get_data_by_resource.assert_called_once()
        call_args = mock_client.get_data_by_resource.call_args
        assert call_args[1]["date_start"] == "2024-01-01"
        assert call_args[1]["starting_page_token"] is None
        # Single-shot endpoints never save state (no next_page_token).
        manager.save_state.assert_not_called()

    def test_fresh_run_small_data_saves_no_state_until_durable_flush(self, mock_client_func):
        """Small total payload: nothing flushes mid-stream, so no resume state is saved.

        Saving a token before the yielded data is durably written would risk skipping it
        on resume. The final flush at end-of-stream is always the last thing before a
        clean completion, so there's no durable intermediate checkpoint to record.
        """
        mock_client = mock.MagicMock()
        mock_client.get_data_by_resource.return_value = [
            ([{"id": "c1"}], "token-2"),
            ([{"id": "c2"}], "token-3"),
            ([{"id": "c3"}], None),
        ]
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager(can_resume=False)

        result = linkedin_ads_source(
            config=config,
            resource_name="campaigns",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
        )

        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)
        # Default Batcher chunk_size (5000) means three tiny pages all land in one final flush.
        assert len(rows) == 1
        assert isinstance(rows[0], pa.Table)
        assert rows[0].num_rows == 3

        mock_client.get_data_by_resource.assert_called_once()
        assert mock_client.get_data_by_resource.call_args[1]["starting_page_token"] is None

        manager.save_state.assert_not_called()
        manager.load_state.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.linkedin_ads.Batcher")
    def test_state_only_advances_past_fully_flushed_pages(self, mock_batcher_cls, mock_client_func):
        """Core safety property: the saved token must only point to pages whose rows are
        already durable (yielded as a flushed pa.Table). A page whose rows are still in
        the in-memory buffer must never have its `next_page_token` persisted, because a
        crash would otherwise leave those rows unwritten and unreachable on resume."""
        mock_batcher_cls.side_effect = _small_batcher_factory(chunk_size=2)

        mock_client = mock.MagicMock()
        # Two-record pages; with chunk_size=2 the batcher flushes whenever two records
        # have accumulated.
        mock_client.get_data_by_resource.return_value = [
            ([{"id": "p1-a"}, {"id": "p1-b"}], "token-2"),  # page 1 → fills buffer, flush, pending=None
            ([{"id": "p2-a"}, {"id": "p2-b"}], "token-3"),  # page 2 → fills buffer, flush, advances to token-2
            ([{"id": "p3-a"}, {"id": "p3-b"}], None),  # page 3 → fills buffer, flush, advances to token-3
        ]
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager(can_resume=False)

        result = linkedin_ads_source(
            config=config,
            resource_name="campaigns",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
        )

        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)
        assert all(isinstance(r, pa.Table) for r in rows)
        assert [r.num_rows for r in rows] == [2, 2, 2]

        # Flush order: (p1-a, p1-b) flush → nothing to commit yet; (p2-a, p2-b) flush →
        # commit token-2 (all of page 1 is durable); (p3-a, p3-b) flush → commit token-3
        # (all of page 2 is durable). token-3 is the last committed token because page 3
        # has no next_page_token.
        assert manager.save_state.call_args_list == [
            mock.call(LinkedInAdsResumeConfig(page_token="token-2")),
            mock.call(LinkedInAdsResumeConfig(page_token="token-3")),
        ]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.linkedin_ads.Batcher")
    def test_state_does_not_advance_when_page_straddles_flush_boundary(self, mock_batcher_cls, mock_client_func):
        """When a page's records straddle a flush boundary, its `next_page_token` must
        stay pending until a later flush captures the remaining records — otherwise the
        still-buffered tail of that page would be lost on crash-recovery, yet the saved
        token would already point past it.

        The final incomplete-chunk flush intentionally does NOT commit a new token: if
        that write fails we want the most recent durably-flushed checkpoint to remain
        authoritative, so resume re-fetches from there."""
        mock_batcher_cls.side_effect = _small_batcher_factory(chunk_size=3)

        mock_client = mock.MagicMock()
        # Pages of 1, 2, 2 records. With chunk_size=3 the flush happens at the 3rd
        # record batched (the 2nd record of page 2), leaving the trailing record of
        # page 2 and all of page 3 in the buffer for the final incomplete-chunk flush.
        mock_client.get_data_by_resource.return_value = [
            ([{"id": "p1-a"}], "token-2"),
            ([{"id": "p2-a"}, {"id": "p2-b"}], "token-3"),
            ([{"id": "p3-a"}, {"id": "p3-b"}], None),
        ]
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager(can_resume=False)

        result = linkedin_ads_source(
            config=config,
            resource_name="campaigns",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
        )

        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)
        assert all(isinstance(r, pa.Table) for r in rows)
        # Flush 1 at p2-b: [p1-a, p2-a, p2-b] — page 1 fully durable, "token-2" saved.
        # Final flush: [p3-a, p3-b] — page 2's tail had already been written by flush 1,
        # page 3 never triggered its own mid-stream flush, and no new token is committed.
        assert [r.num_rows for r in rows] == [3, 2]

        # Critically, "token-3" is never saved — because the only flush that followed
        # the end of page 2's loop was the final incomplete-chunk flush, which
        # deliberately skips save_state. On crash mid-final-flush, resume from "token-2"
        # still recovers everything safely.
        assert manager.save_state.call_args_list == [
            mock.call(LinkedInAdsResumeConfig(page_token="token-2")),
        ]

    def test_resume_run_seeds_starting_page_token_and_skips_initial(self, mock_client_func):
        """Resume run: load_state is called; the saved token is passed as starting_page_token."""
        mock_client = mock.MagicMock()
        mock_client.get_data_by_resource.return_value = [
            ([{"id": "c2"}], None),
        ]
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager(can_resume=True, loaded_state=LinkedInAdsResumeConfig(page_token="token-2"))

        result = linkedin_ads_source(
            config=config,
            resource_name="campaigns",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
        )

        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)
        assert len(rows) == 1
        assert isinstance(rows[0], pa.Table)
        assert rows[0].num_rows == 1
        assert rows[0].column("id").to_pylist() == ["c2"]

        manager.can_resume.assert_called_once()
        manager.load_state.assert_called_once()
        mock_client.get_data_by_resource.assert_called_once()
        assert mock_client.get_data_by_resource.call_args[1]["starting_page_token"] == "token-2"
        # Final page of a resume has no next token → no save.
        manager.save_state.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.linkedin_ads.Batcher")
    def test_daily_rate_limit_stops_gracefully_and_flushes_batched_rows(self, mock_batcher_cls, mock_client_func):
        """A daily rate limit raised mid-stream must not fail the job. We stop fetching, flush the
        rows already batched, and keep the most recent durable resume token so the next scheduled
        sync continues from there."""
        mock_batcher_cls.side_effect = _small_batcher_factory(chunk_size=2)

        def pages_then_rate_limit():
            yield ([{"id": "p1-a"}, {"id": "p1-b"}], "token-2")  # fills buffer, flush, pending=None
            yield ([{"id": "p2-a"}, {"id": "p2-b"}], "token-3")  # fills buffer, flush, advances to token-2
            yield ([{"id": "p3-a"}], "token-4")  # one record left buffered
            raise LinkedinAdsDailyRateLimitError('LinkedIn daily rate limit reached (429): {"status":429}')

        mock_client = mock.MagicMock()
        mock_client.get_data_by_resource.return_value = pages_then_rate_limit()
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager(can_resume=False)

        result = linkedin_ads_source(
            config=config,
            resource_name="campaigns",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
        )

        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)  # must not raise
        assert all(isinstance(r, pa.Table) for r in rows)
        # Two mid-stream flushes of 2 rows, then the final incomplete-chunk flush of the
        # single buffered p3-a row.
        assert [r.num_rows for r in rows] == [2, 2, 1]

        # Only token-2 is durably saved: it's committed once page 2's flush proves page 1's rows are
        # written. Page 3 holds a single record that never triggers its own mid-stream flush, so
        # token-3 stays pending and the final incomplete-chunk flush deliberately skips save_state.
        # Resume from token-2 re-fetches the rest — already-written rows are deduped by primary key.
        assert manager.save_state.call_args_list == [
            mock.call(LinkedInAdsResumeConfig(page_token="token-2")),
        ]

    def test_daily_rate_limit_on_first_page_yields_nothing_without_error(self, mock_client_func):
        """Hitting the daily limit before any data is fetched stops cleanly with no rows and no state."""

        def rate_limit_immediately():
            yield from ()  # makes this a generator that yields nothing before raising
            raise LinkedinAdsDailyRateLimitError('LinkedIn daily rate limit reached (429): {"status":429}')

        mock_client = mock.MagicMock()
        mock_client.get_data_by_resource.return_value = rate_limit_immediately()
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager(can_resume=False)

        result = linkedin_ads_source(
            config=config,
            resource_name="campaigns",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
        )

        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)
        assert rows == []
        manager.save_state.assert_not_called()

    def test_empty_first_page_does_not_save_state(self, mock_client_func):
        """Empty first page (no next token): no yields, no save_state."""
        mock_client = mock.MagicMock()
        mock_client.get_data_by_resource.return_value = iter([])
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager(can_resume=False)

        result = linkedin_ads_source(
            config=config,
            resource_name="campaigns",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
        )

        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)
        assert rows == []
        manager.save_state.assert_not_called()

    @pytest.mark.parametrize("should_use_incremental_field", [True, False])
    def test_initial_sync_starts_from_bounded_lookback_not_epoch(self, mock_client_func, should_use_incremental_field):
        """First sync of an analytics resource has no cursor. The start date must be the bounded
        lookback, not 1970 — syncing stats from the epoch fans out into decades of empty yearly
        windows that exhaust LinkedIn's daily call budget."""
        mock_client = mock.MagicMock()
        mock_client.get_data_by_resource.return_value = [([], None)]
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager()

        result = linkedin_ads_source(
            config=config,
            resource_name="campaign_stats",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
            should_use_incremental_field=should_use_incremental_field,
            incremental_field="date_start" if should_use_incremental_field else None,
            incremental_field_type=IncrementalFieldType.Date if should_use_incremental_field else None,
            db_incremental_field_last_value=None,
        )

        items = result.items()
        assert isinstance(items, Iterable)
        list(items)

        date_start = mock_client.get_data_by_resource.call_args[1]["date_start"]
        parsed = dt.date.fromisoformat(date_start)
        expected_floor = (dt.datetime.now() - dt.timedelta(days=INITIAL_ANALYTICS_LOOKBACK_DAYS)).date()
        assert abs((parsed - expected_floor).days) <= 1

    def test_incremental_resume_uses_saved_cursor_not_lookback(self, mock_client_func):
        """A resumed incremental sync must honour the saved cursor verbatim — the lookback floor
        only applies to the first sync, never clamps an existing cursor."""
        mock_client = mock.MagicMock()
        mock_client.get_data_by_resource.return_value = [([], None)]
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager()

        result = linkedin_ads_source(
            config=config,
            resource_name="campaign_stats",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
            should_use_incremental_field=True,
            incremental_field="date_start",
            incremental_field_type=IncrementalFieldType.Date,
            db_incremental_field_last_value=dt.date(2024, 1, 1),
        )

        items = result.items()
        assert isinstance(items, Iterable)
        list(items)

        assert mock_client.get_data_by_resource.call_args[1]["date_start"] == "2024-01-01"
