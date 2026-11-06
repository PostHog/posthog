from typing import Any

from django.core.management.base import BaseCommand

from products.alerts.backend.facade.destinations import bucket_report_lines
from products.logs.backend.alert_destinations import LOGS_ALERT_EVENT_IDS
from products.logs.backend.destination_buckets import enabled_logs_alerts


class Command(BaseCommand):
    help = "List every destination of an enabled logs alert with the bucket it goes to at cutover."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Report one team only.")

    def handle(self, *args: Any, **options: Any) -> None:
        for line in bucket_report_lines(
            enabled_logs_alerts(team_id=options["team_id"]), allowed_event_ids=LOGS_ALERT_EVENT_IDS
        ):
            self.stdout.write(line)
