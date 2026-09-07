import uuid
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.dataclasses import frozen

from products.workflows.backend.api.hog_flow import MAX_LEGACY_WINDOW_MINUTES
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_revision import HogFlowRevision
from products.workflows.backend.services.timing_reschedule import parse_delay_duration_seconds

MINUTES_PER_DAY = 1440


@frozen
class RewrittenWindow:
    """A conversion whose window_minutes has been respelled as a duration string."""

    conversion: dict
    window: str
    minutes: int


@frozen
class ConvertedFlow:
    """What one locked row's conversion turned into, and whether its draft moved with it."""

    window: str
    minutes: int
    draft_converted: bool


class Command(BaseCommand):
    help = (
        "Move conversion.window_minutes onto conversion.window, the duration-string form. "
        "Only converts values the matcher already honors in full (at or under the legacy ceiling of "
        f"{MAX_LEGACY_WINDOW_MINUTES} minutes), which is a representation change with no effect on any "
        "conversion rate. A larger value is reported and left alone: it can be a real minute count or a "
        "seconds count in a minutes field, and either reading changes what the workflow measures, so "
        "which one is right needs a person. Default dry-run; pass --live-run to apply."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", default=None, type=int, help="Limit to a specific team ID")
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")

    def handle(self, *args: Any, **options: Any) -> None:
        live_run = options.get("live_run", False)
        team_id = options.get("team_id")
        mode = "LIVE RUN" if live_run else "DRY RUN"
        self.stdout.write(f"Starting migrate_conversion_window_to_duration ({mode})")

        flows = HogFlow.objects.filter(conversion__isnull=False)
        if team_id:
            flows = flows.filter(team_id=team_id)
            self.stdout.write(f"Filtering to team_id={team_id}")

        converted = 0
        drafts_with_rows = 0
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

            if not live_run:
                self.stdout.write(
                    f"  Would convert flow id={flow.id} team_id={flow.team_id} status={flow.status}: "
                    f"window_minutes={minutes} -> window={duration_string(minutes)}"
                )
                converted += 1
                continue

            result = self.convert_locked(flow.pk)
            if result is None:
                self.stdout.write(
                    f"  Skipped flow id={flow.id} team_id={flow.team_id}: conversion changed since the "
                    "scan, leaving it for a rerun"
                )
                continue

            drafts_with_rows += 1 if result.draft_converted else 0
            self.stdout.write(
                f"  Converting flow id={flow.id} team_id={flow.team_id} status={flow.status}: "
                f"window_minutes={result.minutes} -> window={result.window}"
            )
            converted += 1

        drafts = drafts_with_rows + self.convert_drafts(live_run, team_id)
        revisions = self.convert_revisions(live_run, team_id)

        self.report_needs_review(needs_review)

        verb = "converted" if live_run else "to convert"
        self.stdout.write(self.style.SUCCESS(f"Completed ({mode}): {converted} flow(s) {verb}"))
        self.stdout.write(self.style.SUCCESS(f"  plus {drafts} draft(s) and {revisions} revision snapshot(s)"))

    def convert_drafts(self, live_run: bool, team_id: int | None) -> int:
        """Drafts whose live conversion needed no change of its own. The pass above already rewrote a
        draft alongside its row; this catches the rest, where only the draft carries the old field."""
        flows = HogFlow.objects.filter(draft__isnull=False)
        if team_id:
            flows = flows.filter(team_id=team_id)

        count = 0
        for flow in flows.iterator():
            draft = flow.draft
            if not isinstance(draft, dict):
                continue
            rewritten = converted_conversion(draft.get("conversion"))
            if rewritten is None:
                continue
            self.stdout.write(
                f"  {'Converting' if live_run else 'Would convert'} draft on flow id={flow.id} "
                f"team_id={flow.team_id}: window={rewritten.window}"
            )
            if live_run:
                with transaction.atomic():
                    locked = HogFlow.objects.select_for_update().get(pk=flow.pk)
                    locked_draft = locked.draft
                    if not isinstance(locked_draft, dict):
                        continue
                    fresh = converted_conversion(locked_draft.get("conversion"))
                    if fresh is None:
                        continue
                    HogFlow.objects.filter(pk=flow.pk).update(draft={**locked_draft, "conversion": fresh.conversion})
            count += 1
        return count

    def convert_revisions(self, live_run: bool, team_id: int | None) -> int:
        """Snapshots a rollback copies back into the draft. Rewriting one keeps a restore from putting
        the deprecated field back. The value is unchanged, only how it is spelled, so the snapshot still
        records the same window it always did."""
        # Fail-closed manager: one team goes through for_team, and a whole-instance backfill is the
        # cross-team access unscoped() exists for.
        revisions = HogFlowRevision.objects.for_team(team_id) if team_id else HogFlowRevision.objects.unscoped().all()

        count = 0
        for revision in revisions.iterator():
            content = revision.content
            if not isinstance(content, dict):
                continue
            rewritten = converted_conversion(content.get("conversion"))
            if rewritten is None:
                continue
            self.stdout.write(
                f"  {'Converting' if live_run else 'Would convert'} revision id={revision.id} "
                f"flow={revision.hog_flow_id} v{revision.version}: window={rewritten.window}"
            )
            if live_run:
                # Append-only in practice — nothing edits a published snapshot — so no lock is needed.
                HogFlowRevision.objects.for_team(revision.team_id).filter(pk=revision.pk).update(
                    content={**content, "conversion": rewritten.conversion}
                )
            count += 1
        return count

    def convert_locked(self, pk: uuid.UUID) -> ConvertedFlow | None:
        # Re-read the row under a lock and convert the value it holds now, not the one the scan read.
        # A customer saving the workflow between the scan and this write would otherwise lose that edit
        # to the stale conversion this command is holding, the lost write the API save path and the
        # sibling backfills guard against. A locked row that no longer qualifies (a save added a window
        # or pushed the value above the ceiling) is left for a rerun. .update() keeps updated_at
        # untouched: this is a representation change, not a user edit, so it must not fail an open
        # editor's next save or re-sort untouched flows to the top. The cost is that an editor which loaded
        # the workflow before the run and saves after it writes its stale conversion back, returning that
        # one row to window_minutes. The value it restores is under the ceiling and still honored, and a
        # rerun converts it again, so this is the cheaper side of the trade.
        with transaction.atomic():
            locked = HogFlow.objects.select_for_update().get(pk=pk)
            rewritten = converted_conversion(locked.conversion or {})
            if rewritten is None:
                return None
            fields: dict[str, object] = {"conversion": rewritten.conversion}
            draft_converted = False
            # The draft holds its own copy of conversion, so leaving it behind would put the
            # deprecated field back on the live row the moment the draft is published.
            draft = locked.draft
            if isinstance(draft, dict):
                draft_conversion = converted_conversion(draft.get("conversion"))
                if draft_conversion is not None:
                    fields["draft"] = {**draft, "conversion": draft_conversion.conversion}
                    draft_converted = True
            HogFlow.objects.filter(pk=pk).update(**fields)
        return ConvertedFlow(window=rewritten.window, minutes=rewritten.minutes, draft_converted=draft_converted)

    def report_needs_review(self, needs_review: list[tuple[HogFlow, int]]) -> None:
        if not needs_review:
            return
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(f"{len(needs_review)} flow(s) left alone, each needs a person:"))
        self.stdout.write(f"  {'id':<36}  team_id  window_minutes  as minutes  as seconds  own delay steps  name")
        for flow, minutes in sorted(needs_review, key=lambda pair: pair[0].team_id):
            span = flow_span_days(flow)
            span_label = f"{span:.1f}d" if span else "none"
            self.stdout.write(
                f"  {str(flow.id):<36}  {flow.team_id:<7}  {minutes:<14}  {minutes / MINUTES_PER_DAY:>7.1f}d  "
                f"{minutes / (MINUTES_PER_DAY * 60):>8.1f}d  {span_label:>15}  {flow.name}"
            )
        self.stdout.write(
            "  Read it as whichever column sits closest to the workflow's own delay steps. A value that "
            "only makes sense as seconds was written by someone who meant that many days."
        )


def converted_conversion(conversion: object) -> RewrittenWindow | None:
    """The same conversion with window_minutes spelled as a duration string, or None when it must not
    be touched: already migrated, no usable value, or above the ceiling where the reading is in doubt."""
    if not isinstance(conversion, dict):
        return None
    minutes = conversion.get("window_minutes")
    if conversion.get("window") or not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
        return None
    if minutes > MAX_LEGACY_WINDOW_MINUTES:
        return None
    window = duration_string(minutes)
    rewritten = {k: v for k, v in conversion.items() if k != "window_minutes"}
    rewritten["window"] = window
    return RewrittenWindow(conversion=rewritten, window=window, minutes=minutes)


def duration_string(minutes: int) -> str:
    """The shortest exact duration string for a whole number of minutes."""
    if minutes % MINUTES_PER_DAY == 0:
        return f"{minutes // MINUTES_PER_DAY}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def flow_span_days(flow: HogFlow) -> float:
    """Rough timescale of the workflow's fixed delay steps, each clamped per unit the way the worker
    clamps a delay before it waits, so a step written 90d counts the 30 days it actually waits. This
    is only a sanity signal for the review table. It sums fixed delays without following branches, so
    mutually exclusive delays are added together, and it counts neither date-based delays nor
    condition-wait deadlines. Treat it as approximate, not the exact span any one run follows."""
    total_seconds = 0.0
    for action in flow.actions or []:
        if not isinstance(action, dict):
            continue
        seconds = parse_delay_duration_seconds((action.get("config") or {}).get("delay_duration"))
        if seconds is not None:
            total_seconds += seconds
    return total_seconds / (MINUTES_PER_DAY * 60)
