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
    # Why a digest run went to the channel it went to.
    # No longer produced: routing comes from the repositories, so nobody sets a destination by hand.
    # Retained because migration 0001 names this member as a field default, and a migration reads
    # the live enum, so deleting it makes the whole migration chain fail to load.
    MANUAL = "manual"
    # No declaration anywhere, so the slug matched a same-named Slack channel.
    SLACK_NAME_MATCH = "slack_name_match"
    # Repo declared its digest channel under digest: in .stamphog/policy.yml (logic/digest_config.py).
    STAMPHOG_CONFIG = "stamphog_config"
    # A teams: entry in a root owners.yaml named the channel, either the repo's own or an inherited one.
    OWNERS_CONTACT = "owners_contact"


class AudienceReason(StrEnum):
    # Why a merged PR landed in an audience's digest.
    # No longer produced: routing the author's own team a copy of everything they touched told a
    # team about code it did not own. Retained because rows written before that change still read
    # back through this enum.
    AUTHORED = "authored"
    # The repo declared one channel for every merge of its own, regardless of who owns what.
    REPO_DECLARED = "repo_declared"
    # A team that owns at least one changed file, from the review's ownership resolution.
    OWNED = "owned"
