"""Backfill `llm_skill` AccessControl rows from existing `llm_analytics` rows.

`llm_skill` used to inherit its access control from `llm_analytics` (RESOURCE_INHERITANCE_MAP).
Now that it's an independent resource, a team with no `llm_skill` AccessControl rows falls back
to the default access level (editor, for everyone) - a silent access change for any team that
previously restricted `llm_analytics`. This mirrors each such team's existing `llm_analytics`
grants onto `llm_skill` so effective access doesn't change.

`llm_skill` is also the scope_object for review_hog's config viewsets (blind spots, perspectives,
validators), which reused it rather than getting their own resource - so this covers teams that
use those without ever touching Skills too. Scoped to teams with an existing `llm_analytics`
AccessControl row (nothing to copy, and no behavior change, for any other team).

Usage:
    # Dry-run (default) - logs what would be created, writes nothing
    python manage.py backfill_llm_skill_access_control

    # Live run - actually creates the llm_skill rows
    python manage.py backfill_llm_skill_access_control --live-run

    # Specific team
    python manage.py backfill_llm_skill_access_control --live-run --team-id 2
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

import structlog

from ee.models.rbac.access_control import AccessControl

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Backfill llm_skill AccessControl rows from existing llm_analytics rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually create the llm_skill rows (default is dry-run).",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Backfill only this team.",
        )

    def handle(self, *, live_run: bool, team_id: int | None, **options):
        logger.setLevel(logging.INFO)
        logger.info("backfill_starting", mode="LIVE" if live_run else "DRY-RUN (use --live-run to write)")

        team_ids = self._get_team_ids_with_llm_analytics_access_controls(team_id=team_id)
        logger.info("backfill_teams_found", count=len(team_ids))

        created = 0
        skipped_existing = 0

        for current_team_id in team_ids:
            existing_skill_keys = set(
                AccessControl.objects.filter(team_id=current_team_id, resource="llm_skill").values_list(
                    "resource_id", "organization_member_id", "role_id"
                )
            )

            analytics_rows = AccessControl.objects.filter(team_id=current_team_id, resource="llm_analytics").iterator()

            for row in analytics_rows:
                key = (row.resource_id, row.organization_member_id, row.role_id)
                if key in existing_skill_keys:
                    skipped_existing += 1
                    continue

                logger.info(
                    "backfill_row",
                    team_id=current_team_id,
                    access_level=row.access_level,
                    resource_id=row.resource_id,
                    organization_member_id=row.organization_member_id,
                    role_id=row.role_id,
                )

                if live_run:
                    AccessControl.objects.create(
                        team_id=current_team_id,
                        resource="llm_skill",
                        resource_id=row.resource_id,
                        access_level=row.access_level,
                        organization_member_id=row.organization_member_id,
                        role_id=row.role_id,
                    )
                created += 1

        logger.info(
            "backfill_complete",
            mode="LIVE" if live_run else "DRY-RUN",
            created=created,
            skipped_existing=skipped_existing,
        )

    def _get_team_ids_with_llm_analytics_access_controls(self, *, team_id: int | None) -> list[int]:
        qs = AccessControl.objects.filter(resource="llm_analytics")
        if team_id is not None:
            qs = qs.filter(team_id=team_id)
        return list(qs.values_list("team_id", flat=True).distinct().order_by("team_id"))
