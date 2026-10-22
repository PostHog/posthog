"""Score a trends insight's series for anomalies and print the result. Writes nothing.

python manage.py score_insight_anomalies --insight 123
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.anomaly_scores.scoring import InsightScores, UnsupportedInsightError, score_insight


class Command(BaseCommand):
    help = "Score a trends insight's series for anomalies and print value, score, flag and details per bucket"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--insight", type=int, required=True, help="Insight id")

    def handle(self, *args: Any, **options: Any) -> None:
        insight = (
            Insight.objects.select_related("team", "created_by").filter(pk=options["insight"], deleted=False).first()
        )
        if insight is None:
            raise CommandError(f"Insight {options['insight']} not found")
        try:
            scores = score_insight(insight, insight.team, now=timezone.now())
        except UnsupportedInsightError as err:
            raise CommandError(f"Not scored: {err}")
        self._print(scores)

    def _print(self, scores: InsightScores) -> None:
        self.stdout.write(
            f"interval={scores.interval.value} detector={scores.detector} version={scores.detector_version}"
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
