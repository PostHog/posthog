from __future__ import annotations

import datetime as dt
from argparse import ArgumentParser
from typing import cast
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from asgiref.sync import async_to_sync

from posthog.temporal.common.client import async_connect

from products.managed_warehouse.backend.external_tables import enroll_external_table
from products.managed_warehouse.backend.temporal.external_table_schedule import configure_external_table_schedule
from products.warehouse_sources.backend.facade.external_delta import get_external_delta_table


class Command(BaseCommand):
    help = "Enroll manually linked Delta tables for scheduled managed warehouse registration."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--table-id", type=UUID, action="append", required=True)
        parser.add_argument("--interval-minutes", type=int, default=60)

    @async_to_sync
    async def _schedule(self, team_id: int, table_id: UUID, interval: dt.timedelta) -> str:
        client = await async_connect()
        return await configure_external_table_schedule(client, team_id, table_id, interval)

    def handle(self, *args: object, **options: object) -> None:
        team_id = cast(int, options["team_id"])
        table_ids = cast(list[UUID], options["table_id"])
        interval = dt.timedelta(minutes=cast(int, options["interval_minutes"]))
        if interval < dt.timedelta(minutes=5):
            raise CommandError("The refresh interval must be at least five minutes.")
        try:
            for table_id in table_ids:
                get_external_delta_table(team_id, table_id)
            for table_id in table_ids:
                registration = enroll_external_table(team_id, table_id)
                schedule_id = self._schedule(team_id, table_id, interval)
                self.stdout.write(f"{registration.table_id}: {schedule_id}")
        except ValueError as error:
            raise CommandError(str(error)) from error
