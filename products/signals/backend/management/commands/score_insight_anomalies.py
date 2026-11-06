"""Score a trends insight's series for anomalies and print the result. Writes nothing.

python manage.py score_insight_anomalies --team 1 --insight 123
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from posthog.models import Team

from products.product_analytics.backend.facade.api import insights_including_soft_deleted_for_team
from products.signals.backend.anomaly_scores.scoring import InsightScores, UnsupportedInsightError, score_insight


class Command(BaseCommand):
    help = "Score a trends insight's series for anomalies and print value, score, flag and details per bucket"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team", type=int, required=True, help="Team id")
        parser.add_argument("--insight", type=int, required=True, help="Insight id")

    def handle(self, *args: Any, **options: Any) -> None:
        team = Team.objects.filter(pk=options["team"]).first()
        if team is None:
            raise CommandError(f"Team {options['team']} not found")
        insights = insights_including_soft_deleted_for_team(team_id=team.pk, insight_ids=[options["insight"]])
        insight = next((insight for insight in insights if not insight.deleted), None)
        if insight is None:
            raise CommandError(f"Insight {options['insight']} not found in team {team.pk}")
        try:
            scores = score_insight(insight, team, now=timezone.now())
        except UnsupportedInsightError as err:
            raise CommandError(f"Not scored: {err}")
        self._print(scores)

    def _print(self, scores: InsightScores) -> None:
        self.stdout.write(
            f"interval={scores.interval.value} profile={scores.profile} detector={scores.detector} version={scores.detector_version}"
        )
        for series in scores.series:
            name = series.label if series.breakdown_value is None else f"{series.label} [{series.breakdown_value}]"
            self.stdout.write(f"\nseries {series.series_key} {name}")
            for point in series.points:
                score = "-" if point.score is None else f"{point.score:.3f}"
                flag = "-" if point.flag is None else str(int(point.flag))
                self.stdout.write(
                    f"  {point.bucket_start.isoformat()}  value={point.value:g}  score={score}  flag={flag}  details={point.details}"
                )
