import uuid
import contextlib
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest import mock

from django.test import override_settings

from asgiref.sync import sync_to_async
from parameterized import parameterized
from structlog.types import FilteringBoundLogger

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.tasks.usage_report import ExternalDataJob

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.row_tracking import (
    decrement_rows,
    finish_row_tracking,
    get_all_rows_for_team,
    get_rows,
    increment_rows,
    setup_row_tracking,
    will_hit_billing_limit,
)


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

    @parameterized.expand(
        [
            ("setup_row_tracking", lambda t, s: setup_row_tracking(t, s), None),
            ("increment_rows", lambda t, s: increment_rows(t, s, 5), None),
            ("decrement_rows", lambda t, s: decrement_rows(t, s, 5), None),
            ("finish_row_tracking", lambda t, s: finish_row_tracking(t, s), None),
            ("get_rows", lambda t, s: get_rows(t, s), 0),
            ("get_all_rows_for_team", lambda t, s: get_all_rows_for_team(t), 0),
        ]
    )
    @pytest.mark.asyncio
    async def test_row_tracking_degrades_gracefully_when_redis_unreachable(self, _name, call, expected):
        # A failed ping must not hand out a broken client that then raises on use - row tracking is best-effort.
        schema_id = str(uuid.uuid4())
        broken_client = mock.AsyncMock()
        broken_client.ping.side_effect = ConnectionError("Redis is down")

        with (
            override_settings(DATA_WAREHOUSE_REDIS_HOST="localhost", DATA_WAREHOUSE_REDIS_PORT="6379"),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.row_tracking.get_async_client",
                return_value=broken_client,
            ),
        ):
            assert await call(self.team.pk, schema_id) == expected

        # No row-tracking operation should have been attempted on the broken client.
        broken_client.hset.assert_not_called()
        broken_client.hincrby.assert_not_called()

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
