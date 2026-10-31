"""Tell each team whose active flags target a deleted cohort, with one in-app notice per team.

The dry run is the default. It prints each team's flags, the notice it would get, and whether the
notice would reach anyone. `--send` needs `--team-id`, so a send covers only the teams someone
reviewed in a dry run.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from posthog.models import Team
from posthog.utils import pluralize

from products.feature_flags.backend.deleted_cohort_notices import (
    AffectedFlag,
    DeletedCohort,
    build_notice,
    find_flags_on_deleted_cohorts,
    preview_delivery,
)
from products.notifications.backend.facade.api import create_notification


class Command(BaseCommand):
    help = "Notify teams whose active feature flags target a deleted cohort (dry run by default)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, nargs="+", help="Only scan these teams")
        parser.add_argument("--send", action="store_true", help="Create the notices (requires --team-id)")

    def handle(self, *args: Any, **options: Any) -> None:
        team_ids: list[int] | None = options["team_id"]
        send: bool = options["send"]
        if send and not team_ids:
            raise CommandError("--send requires --team-id with the teams approved from a dry run")

        affected = find_flags_on_deleted_cohorts(team_ids)
        for team_id in team_ids or []:
            if team_id not in affected:
                self.stdout.write(f"Team {team_id}: no active flag targets a deleted cohort. Skipped.")

        deliverable: list[int] = []
        sent = 0
        started_at = timezone.now()
        teams = Team.objects.in_bulk(affected.keys())
        for team_id, flags in sorted(affected.items()):
            team = teams[team_id]
            notice = build_notice(team_id, flags)
            self.stdout.write(
                f"\nTeam {team_id} ({team.name}), organization {team.organization_id}: {pluralize(len(flags), 'flag')}"
            )
            for flag in flags:
                self.stdout.write(f"  {_describe_flag(flag)}")
            self.stdout.write(f"  Title: {notice.title}")
            self.stdout.write(f"  Body: {notice.body}")
            if notice.source_type:
                self.stdout.write(f"  Link: {notice.source_type.value} {notice.source_id}")
            else:
                self.stdout.write(f"  Link: {notice.source_url}")
            if send:
                event = create_notification(notice)
                if event is None:
                    self.stdout.write(
                        "  Not delivered: real-time notifications are off for this organization, "
                        "or nobody in the project can view it."
                    )
                elif event.created_at < started_at:
                    # The idempotency key returns the notice an earlier run created, unchanged.
                    self.stdout.write(f"  Already sent notice {event.id} on {event.created_at.date().isoformat()}.")
                else:
                    sent += 1
                    self.stdout.write(
                        f"  Sent notice {event.id} to {pluralize(len(event.resolved_user_ids), 'person', 'people')}."
                    )
                continue
            preview = preview_delivery(team, notice)
            if not preview.notifications_enabled:
                self.stdout.write("  Would not deliver: real-time notifications are off for this organization.")
            elif not preview.recipient_count:
                self.stdout.write("  Would not deliver: nobody in the project can view it.")
            else:
                deliverable.append(team_id)
                self.stdout.write(f"  Would deliver to up to {pluralize(preview.recipient_count, 'person', 'people')}.")

        flag_count = sum(len(flags) for flags in affected.values())
        self.stdout.write(f"\n{pluralize(len(affected), 'team')}, {pluralize(flag_count, 'flag')}.")
        if send:
            self.stdout.write(f"Sent {pluralize(sent, 'notice')}.")
        else:
            self.stdout.write(f"{pluralize(len(deliverable), 'team')} would receive the notice.")
            if deliverable:
                self.stdout.write(f"--team-id {' '.join(str(team_id) for team_id in deliverable)}")


def _describe_flag(flag: AffectedFlag) -> str:
    owner = f" ({flag.owner.kind.replace('_', ' ')} '{flag.owner.name}' {flag.owner.id})" if flag.owner else ""
    called = flag.last_called_at.date().isoformat() if flag.last_called_at else "never"
    cohorts = ", ".join(_describe_cohort(cohort) for cohort in flag.cohorts)
    return f"flag {flag.flag_id} '{flag.key}'{owner}, last called {called}: {cohorts}"


def _describe_cohort(cohort: DeletedCohort) -> str:
    if cohort.missing:
        return f"missing cohort {cohort.id}"
    return f"deleted cohort {cohort.id} '{cohort.name or ''}'"
