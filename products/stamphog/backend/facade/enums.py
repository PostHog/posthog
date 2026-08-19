"""
Exported enums for stamphog.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic/, models.py).
"""

from enum import StrEnum


class ReviewMode(StrEnum):
    # Every relevant PR event triggers a review (the default).
    ALL = "all"
    # Reviews run only for PRs carrying the repo's trigger label (Action-style opt-in).
    LABEL = "label"


class ReviewRunStatus(StrEnum):
    QUEUED = "queued"
    GATED = "gated"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


# A run in one of these states is done and must not be superseded or rewritten. GATED is terminal
# too: a deterministic gate block is a completed outcome (completed_at is set), and superseding it
# on the next webhook would rewrite the gate result out of the run history.
TERMINAL_STATUSES = frozenset(
    {ReviewRunStatus.COMPLETED, ReviewRunStatus.FAILED, ReviewRunStatus.SUPERSEDED, ReviewRunStatus.GATED}
)


class ReviewTrigger(StrEnum):
    """What caused a run to exist, derived from the run and its repo config.

    Not stored: a run records `inbox_review` provenance on its output and inherits the repo's
    review_mode, and this collapses the two into the one answer a reader wants — why did stamphog
    look at this PR at all.
    """

    # Self-driving: stamphog reviewed a bot-authored PR off its own inbox provenance.
    SELF_DRIVING = "self_driving"
    # The repo is in LABEL mode, so the trigger label opted this PR in.
    LABEL = "label"
    # The repo reviews every relevant PR event.
    ALL = "all"


class ReviewVerdict(StrEnum):
    NONE = "none"
    APPROVED = "approved"
    REFUSED = "refused"
    ESCALATE = "escalate"
    WAIT = "wait"
    ERROR = "error"


class DigestRunStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ChannelResolutionSource(StrEnum):
    # How a DigestChannel row came to exist.
    MANUAL = "manual"
    SLACK_NAME_MATCH = "slack_name_match"
    # Repo declared its digest channel under digest: in .stamphog/policy.yml (logic/digest_config.py).
    STAMPHOG_CONFIG = "stamphog_config"
    # Reserved for the future owners.yaml contact.slack step (PR #68872) — not implemented yet.
    OWNERS_CONTACT = "owners_contact"


class AudienceReason(StrEnum):
    # Why a merged PR landed in an audience's digest.
    # The PR author's own team, or the channel the repo declared under digest:.
    AUTHORED = "authored"
    REPO_DECLARED = "repo_declared"
    # A team that owns at least one changed file, from the review's ownership resolution.
    OWNED = "owned"
