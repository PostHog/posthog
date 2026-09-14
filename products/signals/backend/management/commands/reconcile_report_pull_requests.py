from argparse import ArgumentParser
from collections.abc import Iterator
from typing import cast

from django.core.management.base import BaseCommand

from products.signals.backend.models import SignalReportPullRequest
from products.signals.backend.pull_requests import TERMINAL_PR_STATES, verify_pull_request_state


def reconcile_report_pull_requests(*, team_id: int, after: str | None, batch_size: int) -> Iterator[tuple[str, str]]:
    """Read every unverified terminal pull request state back from GitHub, one row at a time.

    These rows hold a close or a merge a task run or a legacy assignment claimed, so a report may
    have been resolved on a merge that never happened. Safe to rerun: a row GitHub confirms drops
    out of the batch on the next pass.
    """
    while True:
        prs = SignalReportPullRequest.objects.for_team(team_id).filter(
            state__in=TERMINAL_PR_STATES, checked_at__isnull=True
        )
        if after:
            prs = prs.filter(id__gt=after)
        rows = list(prs.order_by("id").values_list("id", "url")[:batch_size])
        if not rows:
            return
        for pr_id, url in rows:
            yield url, verify_pull_request_state(team_id=team_id, pr_url=url) or "unverified"
            after = str(pr_id)


class Command(BaseCommand):
    help = (
        "Verify stored pull request states against GitHub and reopen falsely resolved reports. Safe to rerun. "
        "Reads stored pull request rows only, so run backfill_report_pull_requests first to import legacy "
        "assignment links."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--after", help="Resume after this pull request UUID.")
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args: object, **options: object) -> None:
        for url, state in reconcile_report_pull_requests(
            team_id=cast(int, options["team_id"]),
            after=cast(str | None, options["after"]),
            batch_size=max(1, min(cast(int, options["batch_size"]), 1000)),
        ):
            self.stdout.write(f"{url}: {state}")
