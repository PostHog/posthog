import re

from django.core.management.base import BaseCommand

from products.workflows.backend.api.hog_flow import MAX_LEGACY_WINDOW_MINUTES, duration_to_minutes
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

DURATION_RE = re.compile(r"^\d*\.?\d+[dhms]$")

MINUTES_PER_DAY = 1440


class Command(BaseCommand):
    help = (
        "Move conversion.window_minutes onto conversion.window, the duration-string form. "
        "Only converts values the matcher already honors in full (at or under the legacy ceiling of "
        f"{MAX_LEGACY_WINDOW_MINUTES} minutes), which is a representation change with no effect on any "
        "conversion rate. A larger value is reported and left alone: it can be a real minute count or a "
        "seconds count in a minutes field, and either reading changes what the workflow measures, so "
        "which one is right needs a person. Default dry-run; pass --live-run to apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Limit to a specific team ID")
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")

    def handle(self, *args, **options):
        live_run = options.get("live_run", False)
        team_id = options.get("team_id")
        mode = "LIVE RUN" if live_run else "DRY RUN"
        self.stdout.write(f"Starting migrate_conversion_window_to_duration ({mode})")

        flows = HogFlow.objects.filter(conversion__isnull=False)
        if team_id:
            flows = flows.filter(team_id=team_id)
            self.stdout.write(f"Filtering to team_id={team_id}")

        converted = 0
        needs_review = []
        for flow in flows.iterator():
            conversion = flow.conversion or {}
            minutes = conversion.get("window_minutes")
            # A row that already carries a window was written by a client that knows the new field.
            if conversion.get("window") or not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
                continue

            if minutes > MAX_LEGACY_WINDOW_MINUTES:
                needs_review.append((flow, minutes))
                continue

            window = duration_string(minutes)
            new_conversion = {k: v for k, v in conversion.items() if k != "window_minutes"}
            new_conversion["window"] = window

            self.stdout.write(
                f"  {'Converting' if live_run else 'Would convert'} flow id={flow.id} team_id={flow.team_id} "
                f"status={flow.status}: window_minutes={minutes} -> window={window}"
            )
            if live_run:
                # .update() avoids bumping updated_at / firing save signals for a backfill.
                HogFlow.objects.filter(pk=flow.pk).update(conversion=new_conversion)
            converted += 1

        self.report_needs_review(needs_review)

        verb = "converted" if live_run else "to convert"
        self.stdout.write(self.style.SUCCESS(f"Completed ({mode}): {converted} flow(s) {verb}"))

    def report_needs_review(self, needs_review):
        if not needs_review:
            return
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(f"{len(needs_review)} flow(s) left alone, each needs a person:"))
        self.stdout.write("  team_id  window_minutes  as minutes  as seconds  own delay steps  name")
        for flow, minutes in sorted(needs_review, key=lambda pair: pair[0].team_id):
            span = flow_span_days(flow)
            span_label = f"{span:.1f}d" if span else "none"
            self.stdout.write(
                f"  {flow.team_id:<7}  {minutes:<14}  {minutes / MINUTES_PER_DAY:>7.1f}d  "
                f"{minutes / (MINUTES_PER_DAY * 60):>8.1f}d  {span_label:>15}  {flow.name}"
            )
        self.stdout.write(
            "  Read it as whichever column sits closest to the workflow's own delay steps. A value that "
            "only makes sense as seconds was written by someone who meant that many days."
        )


def duration_string(minutes: int) -> str:
    """The shortest exact duration string for a whole number of minutes."""
    if minutes % MINUTES_PER_DAY == 0:
        return f"{minutes // MINUTES_PER_DAY}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def flow_span_days(flow: HogFlow) -> float:
    """How long the workflow's own delay steps run, which is what says whether a window is plausible."""
    total = 0.0
    for action in flow.actions or []:
        if not isinstance(action, dict):
            continue
        duration = (action.get("config") or {}).get("delay_duration")
        if isinstance(duration, str) and DURATION_RE.match(duration):
            total += duration_to_minutes(duration)
    return total / MINUTES_PER_DAY
