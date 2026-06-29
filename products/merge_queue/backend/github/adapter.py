"""GitHub adapter.

Inbound: PR webhooks (review submitted, check-suite completed, push, label) become a
normalized `PullRequestSignal`, which the adapter turns into `PRFacts`, evaluates against the
queue-admission predicate (the condition grammar), and — when eligible — enrolls via the
facade. Outbound: merges and commit statuses, routed through the engine's `ShadowGuard` (the
engine is currently shadow, so they record and do not act).

Reuses the GitHub App integration model `products/tasks` uses (`github_integration`).

The HTTP webhook entrypoint (signature verification, event routing) and the live outbound
wiring come later; for now this implements the ingest/eligibility/enroll core and the
outbound seam.
"""

import logging
from dataclasses import dataclass, field

from products.merge_queue.backend.engine import lifecycle
from products.merge_queue.backend.facade import api
from products.merge_queue.backend.facade.types import Actor, ActorKind, EnrollmentStatus, PRRef
from products.merge_queue.backend.github import bot_accounts, refs
from products.merge_queue.backend.github.bot_accounts import BotRegistry, Review
from products.merge_queue.backend.grammar.evaluator import PRFacts, evaluate
from products.merge_queue.backend.shadow import GitHubOut

logger = logging.getLogger(__name__)

# Queue-admission predicate. Partition predicates layer on top once the router lands.
DEFAULT_ELIGIBILITY = "approved checks-green"

# GitHub check conclusions that count as green.
GREEN_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})

# The adapter is the actor for auto-enroll.
ADAPTER_ACTOR = Actor(id="github-adapter", kind=ActorKind.SYSTEM, display="Stampede GitHub adapter")


@dataclass
class PullRequestSignal:
    """A normalized snapshot of a PR's mergeability facts, assembled from webhook + API data."""

    repo: str
    number: int
    head_sha: str
    author_login: str
    reviews: list[Review] = field(default_factory=list)
    checks: dict[str, str] = field(default_factory=dict)  # check name → conclusion
    required_checks: list[str] = field(default_factory=list)  # incl. the Visual Review gate
    changed_files: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


def to_facts(signal: PullRequestSignal) -> PRFacts:
    """Build the `PRFacts` the grammar evaluates against."""
    approved = bot_accounts.has_valid_approval(signal.reviews, pr_author_login=signal.author_login)
    # Conservative: green requires a known set of required checks, all green. An empty set is
    # not green — nothing has certified the PR.
    checks_green = bool(signal.required_checks) and all(
        signal.checks.get(name) in GREEN_CONCLUSIONS for name in signal.required_checks
    )
    return PRFacts(
        approved=approved,
        checks_green=checks_green,
        changed_files=frozenset(signal.changed_files),
        labels=frozenset(signal.labels),
    )


def ingest(signal: PullRequestSignal, *, predicate: str = DEFAULT_ELIGIBILITY) -> EnrollmentStatus | None:
    """Enroll the PR if it is eligible; return its status, or None if not eligible.

    Idempotent: a webhook for an already-enrolled PR returns its current status.
    """
    facts = to_facts(signal)
    if not evaluate(predicate, facts):
        return None
    pr = PRRef(repo=signal.repo, number=signal.number, head_sha=signal.head_sha)
    try:
        return api.enroll(pr, actor=ADAPTER_ACTOR)
    except api.AlreadyEnrolled:
        return api.status(pr)


class GitHubAdapterOut(GitHubOut):
    """Outbound side: merges and commit statuses via the GitHub App integration.

    Only used once a partition is promoted out of shadow. Currently the engine holds a
    `ShadowGuard(github=None)`, so these are never called.
    """

    def __init__(self, integration_id: int) -> None:
        self._integration_id = integration_id

    def merge(self, repo: str, number: int, sha: str) -> None:
        raise NotImplementedError("live merge lands with hybrid/exclusive promotion")

    def set_status(self, repo: str, sha: str, *, state: str, context: str, description: str) -> None:
        raise NotImplementedError("live commit-status lands with hybrid/exclusive promotion")


def install_engine_bindings(*, integration_id: int) -> None:
    """Wire the engine's external seams to this GitHub integration (called by the webhook setup)."""
    lifecycle.set_master_head_resolver(lambda repo: refs.master_head(repo, integration_id=integration_id))


def actor_for(login: str, *, registry: BotRegistry | None = None) -> Actor:
    return (registry or BotRegistry()).actor_for(login)
