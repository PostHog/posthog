import uuid
import contextlib
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest import mock

from django.db.utils import InternalError, OperationalError
from django.test import override_settings

import requests
from asgiref.sync import sync_to_async
from parameterized import parameterized
from redis import exceptions as redis_exceptions
from structlog.types import FilteringBoundLogger

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.tasks.usage_report import ExternalDataJob

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.row_tracking import (
    finish_row_tracking,
    increment_rows,
    setup_row_tracking,
    will_hit_billing_limit,
)


class TestRowTrackingRedisUnavailable(BaseTest):
    @parameterized.expand(
        [
            (
                "connection_error",
                redis_exceptions.ConnectionError(
                    "Error connecting to redis:6379. Temporary failure in name resolution."
                ),
            ),
            (
                "misconf_error",
                redis_exceptions.ResponseError(
                    "MISCONF Redis is configured to save RDB snapshots, but it's currently unable to persist to "
                    "disk. Commands that may modify the data set are disabled, because this instance is configured "
                    "to report errors during writes if RDB snapshotting fails (stop-writes-on-bgsave-error option). "
                    "Please check the Redis logs for details about the RDB error."
                ),
            ),
        ]
    )
    @pytest.mark.asyncio
    async def test_setup_row_tracking_does_not_raise_when_redis_is_unreachable(self, _name, exception):
        # get_async_client only builds a lazy client - the ping is the first real
        # connection attempt. If it fails, the client must not be used again, or the
        # next command (hset) raises the same connection error, this time uncaught.
        # Row tracking already fails open when redis is unavailable, so a Redis-side
        # error (unreachable, or refusing writes because RDB snapshotting failed) is a
        # transient infra blip, not a bug, and must not be reported to error tracking.
        unreachable_client = mock.AsyncMock()
        unreachable_client.ping.side_effect = exception

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.row_tracking.get_async_client",
                return_value=unreachable_client,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.row_tracking.capture_exception"
            ) as mock_capture_exception,
            override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT="6379"),
        ):
            await setup_row_tracking(self.team.pk, str(uuid.uuid4()))

        unreachable_client.hset.assert_not_called()
        mock_capture_exception.assert_not_called()

    @pytest.mark.asyncio
    async def test_setup_row_tracking_does_not_raise_when_redis_rejects_writes(self):
        # A successful ping doesn't guarantee the following command succeeds - e.g. Redis
        # can refuse writes (MISCONF) if it can't persist an RDB snapshot to disk. That
        # must fail open like the unreachable-at-ping case above, not crash the sync.
        read_only_client = mock.AsyncMock()
        read_only_client.ping.return_value = True
        read_only_client.hset.side_effect = redis_exceptions.ResponseError(
            "MISCONF Redis is configured to save RDB snapshots, but it's currently "
            "unable to persist to disk. Commands that may modify the data set are "
            "disabled, because this instance is configured to report errors during "
            "writes if RDB snapshotting fails (stop-writes-on-bgsave-error option). "
            "Please check the Redis logs for details about the RDB error."
        )

        with (
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.row_tracking.get_async_client",
                return_value=read_only_client,
            ),
            override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT="6379"),
        ):
            await setup_row_tracking(self.team.pk, str(uuid.uuid4()))

        read_only_client.expire.assert_not_called()


@pytest.mark.timeout(600)
@mock.patch(
    "products.warehouse_sources.backend.temporal.data_imports.row_tracking.database_sync_to_async_pool",
    database_sync_to_async,
)
class TestRowTracking(BaseTest):
    def _logger(self) -> FilteringBoundLogger:
        return mock.AsyncMock()

    @contextlib.contextmanager
    def _setup_limits(self, limit: int):
        from ee.api.test.test_billing import create_billing_customer

        with mock.patch("ee.api.billing.requests.get") as mock_billing_request:
            mock_res = create_billing_customer()
            usage_summary = mock_res.get("usage_summary") or {}
            mock_billing_request.return_value.status_code = 200
            mock_billing_request.return_value.json.return_value = {
                "license": {
                    "type": "scale",
                },
                "customer": {
                    **mock_res,
                    "usage_summary": {**usage_summary, "rows_synced": {"limit": limit, "usage": 0}},
                },
            }

            yield

    @contextlib.asynccontextmanager
    async def _setup_redis_rows(self, rows: int, team_id: Optional[int] = None):
        with override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT="6379"):
            t_id = team_id or self.team.pk

            schema_id = str(uuid.uuid4())
            await setup_row_tracking(t_id, schema_id)
            await increment_rows(t_id, schema_id, rows)

            yield

            await finish_row_tracking(t_id, schema_id)

    async def _run(self, source: ExternalDataSource, limit: int) -> bool:
        from ee.models.license import License

        await sync_to_async(License.objects.create)(
            key="12345::67890",
            plan="enterprise",
            valid_until=datetime(2038, 1, 19, 3, 14, 7, tzinfo=ZoneInfo("UTC")),
        )

        with (
            override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT="6379"),
            self._setup_limits(limit),
            freeze_time("2024-01-01 12:00:00"),
        ):
            return await will_hit_billing_limit(team_id=self.team.pk, source=source, logger=self._logger())

    @sync_to_async
    def _create_source(self) -> ExternalDataSource:
        with freeze_time(datetime(2023, 12, 1)):
            return ExternalDataSource.objects.create(team=self.team)

    @pytest.mark.asyncio
    async def test_row_tracking(self):
        source = await self._create_source()
        assert await self._run(source, 10) is False

    @pytest.mark.asyncio
    async def test_row_tracking_with_previous_jobs(self):
        source = await self._create_source()
        await sync_to_async(ExternalDataJob.objects.create)(
            team=self.team,
            rows_synced=11,
            pipeline=source,
            finished_at=datetime.now(),
            billable=True,
            status=ExternalDataJob.Status.COMPLETED,
        )

        assert await self._run(source, 10) is True

    @pytest.mark.asyncio
    async def test_row_tracking_with_free_rows(self):
        source = await self._create_source()
        await sync_to_async(ExternalDataJob.objects.create)(
            team=self.team,
            rows_synced=11,
            pipeline=source,
            finished_at=datetime(2023, 12, 2),
            billable=True,
            status=ExternalDataJob.Status.COMPLETED,
        )

        # 11 rows were during the free sync period and so we've not hit the 10 row limit yet

        assert await self._run(source, 10) is False

    @pytest.mark.asyncio
    async def test_row_tracking_with_previous_incomplete_jobs(self):
        source = await self._create_source()
        await sync_to_async(ExternalDataJob.objects.create)(
            team=self.team,
            rows_synced=11,
            pipeline=source,
            finished_at=datetime.now(),
            billable=True,
            status=ExternalDataJob.Status.RUNNING,
        )

        assert await self._run(source, 10) is False

    @pytest.mark.asyncio
    async def test_row_tracking_with_previous_no_finished_at_jobs(self):
        source = await self._create_source()
        await sync_to_async(ExternalDataJob.objects.create)(
            team=self.team,
            rows_synced=11,
            pipeline=source,
            finished_at=None,
            billable=True,
            status=ExternalDataJob.Status.COMPLETED,
        )

        assert await self._run(source, 10) is False

    @pytest.mark.asyncio
    async def test_row_tracking_with_previous_unbillable_jobs(self):
        source = await self._create_source()
        await sync_to_async(ExternalDataJob.objects.create)(
            team=self.team,
            rows_synced=11,
            pipeline=source,
            finished_at=datetime.now(),
            billable=False,
            status=ExternalDataJob.Status.COMPLETED,
        )

        assert await self._run(source, 10) is False

    @pytest.mark.asyncio
    async def test_row_tracking_with_in_progress_rows(self):
        source = await self._create_source()
        async with self._setup_redis_rows(20):
            assert await self._run(source, 10) is True

    @pytest.mark.asyncio
    async def test_row_tracking_with_previous_rows_from_other_team_in_org(self):
        another_team = await sync_to_async(Team.objects.create)(organization=self.organization)
        source = await self._create_source()
        await sync_to_async(ExternalDataJob.objects.create)(
            team=another_team,
            rows_synced=11,
            pipeline=source,
            finished_at=datetime.now(),
            billable=True,
            status=ExternalDataJob.Status.COMPLETED,
        )

        assert await self._run(source, 10) is True

    @pytest.mark.asyncio
    async def test_row_tracking_with_in_progress_rows_from_other_team_in_org(self):
        another_team = await sync_to_async(Team.objects.create)(organization=self.organization)
        source = await self._create_source()

        async with self._setup_redis_rows(20, team_id=another_team.pk):
            assert await self._run(source, 10) is True

    @pytest.mark.asyncio
    async def test_row_tracking_fails_open_on_redis_error_without_capturing_exception(self):
        # A transient Redis connectivity blip while fetching billing data (e.g. a DNS
        # resolution failure reaching the quota-limiting cache) must fail open like any
        # other billing-check error, but shouldn't be reported to error tracking since
        # the check already tolerates it.
        source = await self._create_source()

        with (
            mock.patch("ee.billing.billing_manager.BillingManager.get_billing") as mock_get_billing,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.row_tracking.capture_exception"
            ) as mock_capture_exception,
        ):
            mock_get_billing.side_effect = redis_exceptions.ConnectionError(
                "Error -3 connecting to redis:6379. Temporary failure in name resolution."
            )

            assert await self._run(source, 10) is False

        mock_capture_exception.assert_not_called()

    @parameterized.expand(
        [
            (
                "operational_error",
                OperationalError(
                    'connection failed: connection to server at "127.0.0.1", port 5432 failed: '
                    "server closed the connection unexpectedly"
                ),
            ),
            (
                "internal_error",
                InternalError("cannot execute UPDATE in a read-only transaction"),
            ),
        ]
    )
    @pytest.mark.asyncio
    async def test_row_tracking_fails_open_on_database_error_without_capturing_exception(self, _name, exception):
        # A dropped Postgres connection, or hitting a read-only replica/failover blip,
        # while fetching billing data is a transient infra issue, not a bug, and must
        # fail open like any other billing-check error without being reported to error
        # tracking.
        source = await self._create_source()

        with (
            mock.patch("ee.billing.billing_manager.BillingManager.get_billing") as mock_get_billing,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.row_tracking.capture_exception"
            ) as mock_capture_exception,
        ):
            mock_get_billing.side_effect = exception

            assert await self._run(source, 10) is False

        mock_capture_exception.assert_not_called()

    @pytest.mark.asyncio
    async def test_row_tracking_fails_open_on_request_error_without_capturing_exception(self):
        # A network blip (e.g. a proxy timeout) reaching the billing service is a transient
        # infra issue, not a bug, and must fail open like any other billing-check error
        # without being reported to error tracking.
        source = await self._create_source()

        with (
            mock.patch("ee.billing.billing_manager.BillingManager.get_billing") as mock_get_billing,
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.row_tracking.capture_exception"
            ) as mock_capture_exception,
        ):
            mock_get_billing.side_effect = requests.exceptions.ProxyError(
                "HTTPSConnectionPool(host='billing.posthog.com', port=443): Max retries exceeded "
                "with url: /api/billing (Caused by ProxyError('Cannot connect to proxy.', "
                "OSError('Tunnel connection failed: 504 Gateway timeout')))"
            )

            assert await self._run(source, 10) is False

        mock_capture_exception.assert_not_called()
