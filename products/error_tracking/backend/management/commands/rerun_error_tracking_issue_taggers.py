"""Re-run the issue taggers on a team's recent active issues.

A tag re-runs on an issue that has no answer for it, or whose answer came from an older rule or question. A team with
the error-tracking-issue-tags flag off is skipped. Without --live-run, the command counts the issues and writes nothing.

Usage:
    # Dry run (default): count the issues to re-run
    python manage.py rerun_error_tracking_issue_taggers --team-id 2

    # Re-run the rules on the 500 newest issues of the last 3 days
    python manage.py rerun_error_tracking_issue_taggers --team-id 2 --tagger rule --days 3 --limit 500 --live-run

    # Re-run one tag
    python manage.py rerun_error_tracking_issue_taggers --team-id 2 --tag big_order --live-run
"""

from django.core.management.base import BaseCommand, CommandError

from products.error_tracking.backend.logic.issue_tags.rerun import IssueTaggerRerun, rerun_issue_taggers
from products.error_tracking.backend.logic.issue_tags.runner import TAGGERS, IssueTaggingSkipReason


class Command(BaseCommand):
    help = "Re-run the error tracking issue taggers on a team's recent active issues."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="The team whose issues to re-run.")
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Re-run issues created in this many days (default: %(default)s).",
        )
        parser.add_argument(
            "--tagger",
            action="append",
            choices=[tagger.source for tagger in TAGGERS],
            help="Run only this tagger. Repeat it for more than one (default: every tagger).",
        )
        parser.add_argument(
            "--tag",
            action="append",
            help="Re-run only this tag key. Repeat it for more than one (default: every enabled tag).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=1000,
            help="Re-run at most this many issues, newest first (default: %(default)s).",
        )
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Re-run the taggers and store their answers (default: count the issues and write nothing).",
        )

    def handle(
        self,
        *,
        team_id: int,
        days: int,
        tagger: list[str] | None,
        tag: list[str] | None,
        limit: int,
        live_run: bool,
        **options,
    ) -> None:
        if days < 1 or limit < 1:
            raise CommandError("--days and --limit must be at least 1.")
        taggers = TAGGERS if tagger is None else tuple(t for t in TAGGERS if t.source in tagger)
        try:
            result = rerun_issue_taggers(
                team_id, days=days, taggers=taggers, keys=tag, limit=limit, dry_run=not live_run
            )
        except ValueError as error:
            raise CommandError(str(error)) from error

        match result:
            case IssueTaggingSkipReason.DISABLED:
                self.stdout.write(f"Issue tags are off for team {team_id}, so nothing ran.")
            case IssueTaggingSkipReason():
                raise CommandError(f"Team {team_id} does not exist.")
            case IssueTaggerRerun() if not live_run:
                self.stdout.write(
                    f"Dry run: {result.selected} issues of team {team_id} have a tag to re-run. "
                    "Pass --live-run to re-run them."
                )
            case IssueTaggerRerun():
                self.stdout.write(
                    f"Re-ran {result.ran} of {result.selected} issues of team {team_id}. "
                    f"Skipped {result.skipped}, failed {result.failed}."
                )
