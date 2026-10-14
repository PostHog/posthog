"""Compare the stored CI rows of one repository with the raw tables, query by query.

It needs the ``engineering-analytics-stored-reads`` flag on for the team, and the stored days of the
reads. The first run of the command starts a refresh if none ran in the last hour, so run it again
once the refresh is done. Each stored read runs twice, so expect about twice the warehouse cost of
the reads. A difference is a lead to check, not proof of a bug: stored rows can be minutes old.

Usage:
    python manage.py compare_stored_ci_reads --team-id 2 --repo PostHog/posthog
    python manage.py compare_stored_ci_reads --team-id 2 --repo PostHog/posthog --days 7
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.team import Team

from products.engineering_analytics.backend.logic.stored_read_parity import compare_stored_reads


class Command(BaseCommand):
    help = "Compare the stored CI rows of one repository with the raw warehouse tables."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--repo", help="owner/name. Defaults to the repository of the team's first source.")
        parser.add_argument("--source-id", help="The GitHub source to read. Defaults to the one that syncs --repo.")
        parser.add_argument("--days", type=int, default=30, help="The window of the reads.")

    def handle(self, *args: Any, **options: Any) -> None:
        team = Team.objects.filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"No team {options['team_id']}")
        try:
            queries = compare_stored_reads(
                team=team, source_id=options["source_id"], repo=options["repo"], days=options["days"]
            )
        except ValueError as error:
            raise CommandError(str(error)) from error
        if not queries:
            raise CommandError("No read took the stored rows. Check the flag, then run again after a refresh.")
        for query in queries:
            self.stdout.write(f"{query.query_type}: {query.stored_rows} stored, {query.raw_rows} raw rows")
            if query.raw_error:
                self.stdout.write(f"  the raw read failed: {query.raw_error}")
            elif not query.equal:
                self.stdout.write(f"  {query.only_stored} rows only stored, for example {query.sample_only_stored}")
                self.stdout.write(f"  {query.only_raw} rows only raw, for example {query.sample_only_raw}")
        differing = sum(not query.equal for query in queries)
        self.stdout.write(f"{differing} of {len(queries)} stored reads differ from the raw tables.")
