from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from products.alerts.backend.facade.destinations import create_flow_drafts, flow_port_report_lines
from products.logs.backend.alert_destinations import LOGS_ALERT_EVENT_IDS, TRANSITION_BY_LOGS_EVENT_ID
from products.logs.backend.destination_buckets import named_logs_alerts


class Command(BaseCommand):
    help = (
        "Create a draft workflow for each customized destination of one logs alert. "
        "The HogFunctions keep sending, and the drafts send nothing until someone publishes them."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--alert-id", type=UUID, required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        alerts = named_logs_alerts(team_id=options["team_id"], alert_id=str(options["alert_id"]))
        if not alerts:
            raise CommandError(f"No logs alert {options['alert_id']} in team {options['team_id']}.")
        (alert,) = alerts
        drafts = create_flow_drafts(
            team_id=options["team_id"],
            alert=alert,
            allowed_event_ids=LOGS_ALERT_EVENT_IDS,
            transition_by_event_id=TRANSITION_BY_LOGS_EVENT_ID,
        )
        for line in flow_port_report_lines(drafts.ports):
            self.stdout.write(line)
        if drafts.refusal is not None:
            raise CommandError(f"Created nothing. {drafts.refusal}")
        for workflow_id in drafts.workflow_ids:
            self.stdout.write(f"Created draft workflow {workflow_id}")
