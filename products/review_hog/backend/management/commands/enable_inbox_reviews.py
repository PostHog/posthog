"""Enable inbox PR reviews for every member of the organization that owns a team.

`review_inbox_prs` and `stamphog_review_inbox_prs` default to off per user because they are the
budget gate for 100%-coverage review cost, so turning them on for a whole team is a deliberate
operator action rather than a default change: this command upserts a `ReviewUserSettings` row with
both toggles on for every active member of the team's organization. Other fields on existing rows
(urgency threshold, label and resolution opt-outs) are untouched, users can still opt back out in
the Code review settings afterwards, and members who join later keep the off default until the
command is re-run.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from posthog.models.organization import OrganizationMembership
from posthog.models.scoping.manager import TeamScopeError, resolve_effective_team_id
from posthog.models.team import Team

from products.review_hog.backend.models import ReviewUserSettings

ENABLED_FIELDS: tuple[str, ...] = ("review_inbox_prs", "stamphog_review_inbox_prs")


class Command(BaseCommand):
    help = (
        "Enable ReviewHog and Stamphog inbox PR reviews (review_inbox_prs + stamphog_review_inbox_prs) "
        "for every active member of the organization that owns the given team."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="The team whose org members get inbox reviews enabled.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without touching the database.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Environment ids resolve to the root team, mirroring the settings API: the rows must land
        # on the same team the inbox trigger's `ReviewUserSettings.load_many` reads them from.
        try:
            team_id = resolve_effective_team_id(options["team_id"])
            team = Team.objects.get(id=team_id)
        except (TeamScopeError, Team.DoesNotExist) as err:
            raise CommandError(str(err)) from err

        member_ids = list(
            OrganizationMembership.objects.filter(
                organization_id=team.organization_id, user__is_active=True
            ).values_list("user_id", flat=True)
        )
        existing = {
            row.user_id: row
            for row in ReviewUserSettings.objects.for_team(team_id, canonical=True).filter(user_id__in=member_ids)
        }
        to_create = [user_id for user_id in member_ids if user_id not in existing]
        to_flip = [row for row in existing.values() if not (row.review_inbox_prs and row.stamphog_review_inbox_prs)]
        already_on = len(existing) - len(to_flip)
        summary = (
            f"team {team_id}: {len(member_ids)} active org member(s), {len(to_create)} row(s) to create, "
            f"{len(to_flip)} existing row(s) to enable, {already_on} already enabled"
        )

        if options["dry_run"]:
            self.stdout.write(self.style.NOTICE(f"[dry-run] {summary}. Nothing written."))
            return

        with transaction.atomic():
            for user_id in to_create:
                # get_or_create because a settings GET auto-creates rows with the off defaults: a
                # user opening the Code review tab between the read above and this write must end
                # enabled, not crash the run on the unique (team, user) constraint.
                row, created = ReviewUserSettings.objects.for_team(team_id, canonical=True).get_or_create(
                    team_id=team_id,
                    user_id=user_id,
                    defaults=dict.fromkeys(ENABLED_FIELDS, True),
                )
                if not created:
                    to_flip.append(row)
            for row in to_flip:
                for field in ENABLED_FIELDS:
                    setattr(row, field, True)
                row.save(update_fields=[*ENABLED_FIELDS, "updated_at"])

        self.stdout.write(self.style.SUCCESS(f"Done. {summary}."))
