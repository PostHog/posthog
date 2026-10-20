from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from products.alerts.backend.facade.destinations import flow_port_report_lines, flow_ports
from products.logs.backend.alert_destinations import LOGS_ALERT_EVENT_IDS, TRANSITION_BY_LOGS_EVENT_ID
from products.logs.backend.destination_buckets import named_logs_alerts


class Command(BaseCommand):
    help = (
        "Report the workflow that would replace each customized destination of a team's logs alerts, "
        "or what stops it. Writes nothing."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--alert-id", type=UUID, default=None, help="Report one logs alert only.")

    def handle(self, *args: Any, **options: Any) -> None:
        alert_id = str(options["alert_id"]) if options["alert_id"] else None
        alerts = named_logs_alerts(team_id=options["team_id"], alert_id=alert_id)
        if alert_id and not alerts:
            raise CommandError(f"No logs alert {alert_id} in team {options['team_id']}.")
        ports = flow_ports(
            team_id=options["team_id"],
            alerts=alerts,
            allowed_event_ids=LOGS_ALERT_EVENT_IDS,
            transition_by_event_id=TRANSITION_BY_LOGS_EVENT_ID,
        )
        for line in flow_port_report_lines(ports):
            self.stdout.write(line)
