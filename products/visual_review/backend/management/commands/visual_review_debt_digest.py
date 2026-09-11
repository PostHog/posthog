"""Run one repo's visual review debt digest synchronously, in the mode you name."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.models.scoping import team_scope

from products.visual_review.backend.logic import debt_digest
from products.visual_review.backend.models import Repo


class Command(BaseCommand):
    help = "Evaluate and render (or post) the visual review debt digest for one repo"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--repo", type=str, required=True, help="Repository as owner/name.")
        parser.add_argument(
            "--mode",
            type=str,
            default=debt_digest.MODE_PREVIEW,
            choices=list(debt_digest.MODES),
            help="preview renders and prints, live posts to each team's channel.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # nosemgrep: idor-lookup-without-team — operator-run command, repo named on the command line
        repo = Repo.objects.unscoped().filter(repo_full_name=options["repo"]).order_by("created_at").first()
        if repo is None:
            raise CommandError(f"No visual review repo named {options['repo']}")
        with team_scope(repo.team_id):
            rendered = debt_digest.send_debt_digest(repo, mode=options["mode"])
        self.stdout.write("\n\n".join(rendered) or "Nothing owed.")
