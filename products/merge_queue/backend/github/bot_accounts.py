"""Per-agent bot accounts.

Each agent author gets a distinct GitHub identity so authorship, approvals, and queue actions
are attributed correctly — and, critically, so an agent's own approval can't satisfy
`approved` on its own PR. The self-approval guard lives here.
"""

from dataclasses import dataclass

from products.merge_queue.backend.facade.types import Actor, ActorKind


@dataclass(frozen=True)
class Review:
    reviewer_login: str
    state: str  # GitHub review state: "approved", "changes_requested", "commented", ...


class BotRegistry:
    """Known per-agent bot logins. Used for attribution and the self-approval guard."""

    def __init__(self, bot_logins: set[str] | None = None) -> None:
        self._bots = {login.lower() for login in (bot_logins or set())}

    def is_bot(self, login: str) -> bool:
        return login.lower() in self._bots

    def actor_for(self, login: str) -> Actor:
        kind = ActorKind.AGENT if self.is_bot(login) else ActorKind.HUMAN
        return Actor(id=login, kind=kind, display=login)


def has_valid_approval(reviews: list[Review], *, pr_author_login: str) -> bool:
    """True iff some review APPROVES the PR and was not authored by the PR's own author.

    Excluding the author covers the agent case: a bot that opened the PR cannot approve it to
    clear `approved` — its approval is a self-approval regardless of bot identity.
    """
    author = pr_author_login.lower()
    return any(review.state.lower() == "approved" and review.reviewer_login.lower() != author for review in reviews)
