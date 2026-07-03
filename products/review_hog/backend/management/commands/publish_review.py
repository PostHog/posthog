import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from github import Github, GithubException

from posthog.models.integration import GitHubIntegration

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.constants import DEFAULT_URGENCY_THRESHOLD, published_priorities_for
from products.review_hog.backend.reviewer.tools.github_meta import PRParser
from products.review_hog.backend.reviewer.tools.publish_review import publish_persisted_review

logger = logging.getLogger(__name__)


def _stale_head_warning(*, token: str, repository: str, pr_number: int, reviewed_head: str) -> str | None:
    """Best-effort note if the PR head moved past the reviewed commit — we still publish the reviewed one."""
    try:
        current = Github(token).get_repo(repository).get_pull(pr_number).head.sha
    except GithubException as e:
        logger.warning("Could not check the PR's current head for staleness: %s", e)
        return None
    if current == reviewed_head:
        return None
    return (
        f"PR head is now {current[:12]} but the stored review is for {reviewed_head[:12]}; publishing the "
        "reviewed commit — its inline comments anchor to that SHA, not the latest one."
    )


class Command(BaseCommand):
    help = "Publish an already-computed ReviewHog review to its PR (no re-review, no sandbox cost)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--pr-url", required=True, help="GitHub PR URL the review was computed for")
        parser.add_argument("--team-id", type=int, required=True, help="Team the review is persisted under")

    def handle(self, *args: Any, **options: Any) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        pr_info = PRParser().parse_github_pr_url(options["pr_url"])
        owner, repo, pr_number = str(pr_info["owner"]), str(pr_info["repo"]), int(pr_info["pr_number"])
        repository = f"{owner}/{repo}"
        team_id = options["team_id"]

        report = ReviewReport.objects.for_team(team_id).filter(repository=repository, pr_number=pr_number).first()
        if report is None:
            raise CommandError(f"No review found for {repository}#{pr_number} on team {team_id}. Run run_review first.")
        if report.run_count == 0 or not report.report_markdown:
            raise CommandError(f"Review for {repository}#{pr_number} hasn't completed a run yet; nothing to publish.")
        head_sha = report.head_sha
        if not head_sha:
            raise CommandError(f"Review for {repository}#{pr_number} has no reviewed head_sha; nothing to publish.")

        github = GitHubIntegration.first_for_team_repository(team_id, repository)
        if github is None:
            raise CommandError(
                f"No GitHub App installation for team {team_id} that can access {repository} "
                "(publishing needs `pull_requests: write`)."
            )
        token = github.get_access_token()

        warning = _stale_head_warning(token=token, repository=repository, pr_number=pr_number, reviewed_head=head_sha)
        if warning:
            self.stdout.write(self.style.WARNING(warning))

        # The latest completed turn's findings live under run_index == run_count: fetch sets
        # run_index = run_count + 1, and finalize bumps run_count after they're persisted.
        run_index = report.run_count
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"ReviewHog ▶ publishing {repository}#{pr_number} · report {report.id} · head {head_sha[:12]}"
            )
        )
        # A local-only ops command: always the default threshold (should_fix), not a per-user one —
        # keeps the frozen body and the freshly built inline comments consistent without needing to
        # track which threshold the run itself used.
        outcome = publish_persisted_review(
            team_id=team_id,
            report_id=str(report.id),
            head_sha=head_sha,
            run_index=run_index,
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            token=token,
            published_priorities=published_priorities_for(DEFAULT_URGENCY_THRESHOLD),
        )
        if outcome.posted:
            self.stdout.write(self.style.SUCCESS(f"ReviewHog ✓ published {repository}#{pr_number}"))
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"ReviewHog · nothing posted for {repository}#{pr_number} "
                    "(already published at this head, or no publishable findings)."
                )
            )
