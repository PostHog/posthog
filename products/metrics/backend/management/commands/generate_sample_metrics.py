"""Send realistic sample metrics to a dev stack, through the OTLP capture endpoint."""

import time
import datetime as dt
from typing import Any

from django.core.management.base import BaseCommand, CommandError

import requests

from posthog.models import Team

from products.metrics.backend import sample_metrics


class Command(BaseCommand):
    help = "Send sample metrics (Envoy, hosts, Redis, a checkout service and an inference gateway) to a team."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="The team that receives the metrics.")
        parser.add_argument("--url", default="http://localhost:8010", help="Base URL of the capture endpoint.")
        parser.add_argument("--hours", type=float, default=6.0, help="Hours of history to send first (at most 23).")
        parser.add_argument("--step", type=float, default=60.0, help="Seconds between history points.")
        parser.add_argument(
            "--follow", action="store_true", help="Keep sending current points until the command is stopped."
        )
        parser.add_argument("--interval", type=float, default=15.0, help="Seconds between live points.")

    def handle(self, *args: Any, **options: Any) -> None:
        team = Team.objects.filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"No team with id {options['team_id']}.")
        if not 0 <= options["hours"] <= 23:
            raise CommandError("Capture keeps points of the last 24 hours only, so use at most 23 hours.")
        services = sample_metrics.sample_services()
        now = time.time()
        history = list(sample_metrics.time_steps(now - options["hours"] * 3600, now, options["step"]))
        for start in range(0, len(history), 30):
            batch = history[start : start + 30]
            sample_metrics.send(options["url"], team.api_token, sample_metrics.export_request(services, batch))
        self.stdout.write(f"Sent {len(history)} history points for {len(services)} services to team {team.id}.")
        while options["follow"]:
            time.sleep(options["interval"])
            try:
                sample_metrics.send(
                    options["url"], team.api_token, sample_metrics.export_request(services, [time.time()])
                )
            except requests.RequestException as error:
                # Keep the feed alive while the dev stack restarts. The next point goes out after the interval.
                self.stderr.write(f"{dt.datetime.now(dt.UTC):%H:%M:%S} could not send live points: {error}")
                continue
            self.stdout.write(f"{dt.datetime.now(dt.UTC):%H:%M:%S} sent live points")
