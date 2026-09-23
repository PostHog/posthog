"""Run one repo's visual review debt digest synchronously, in the mode you name."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.models.scoping import team_scope

from products.visual_review.backend.logic import debt_digest
from products.visual_review.backend.models import Repo


def find_repo(repo_full_name: str, team_id: int | None) -> Repo:
    """The one repo that goes by this name, or a CommandError saying why there is no single answer.

    A name is unique inside a team, not across them, so two teams can register the same repository
    and each carries its own debt.
    """
    # nosemgrep: idor-lookup-without-team — operator-run command, repo named on the command line
    matches = Repo.objects.unscoped().filter(repo_full_name=repo_full_name)
    if team_id is not None:
        matches = matches.filter(team_id=team_id)
    found = list(matches.order_by("created_at"))
    if not found:
        raise CommandError(f"No visual review repo named {repo_full_name}")
    if len(found) > 1:
        teams = ", ".join(str(repo.team_id) for repo in found)
        raise CommandError(f"{repo_full_name} is registered by more than one team ({teams}). Pick one with --team-id.")
    return found[0]


class Command(BaseCommand):
    help = "Evaluate and render (or post) the visual review debt digest for one repo"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--repo", type=str, required=True, help="Repository as owner/name.")
        parser.add_argument("--team-id", type=int, help="Team that registered the repository.")
        parser.add_argument(
            "--mode",
            type=str,
            default=debt_digest.MODE_PREVIEW,
            choices=list(debt_digest.MODES),
            help="preview renders and prints, live posts to each team's channel.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        repo = find_repo(options["repo"], options.get("team_id"))
        with team_scope(repo.team_id):
            rendered = debt_digest.send_debt_digest(repo, mode=options["mode"])
        self.stdout.write("\n\n".join(rendered) or "Nothing owed.")
