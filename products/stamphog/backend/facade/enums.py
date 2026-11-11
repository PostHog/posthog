"""
Exported enums for stamphog.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic/, models.py).
"""

from enum import StrEnum

from posthog.enums import LabeledStrEnum


class ReviewMode(LabeledStrEnum):
    # Every relevant PR event triggers a review.
    ALL = "all", "All pull requests"
    # Reviews run only for PRs carrying the repo's trigger label (Action-style opt-in, the default).
    LABEL = "label", "Labeled pull requests"


class RoutingMode(LabeledStrEnum):
    """When reviewer routing requests the owners of the changed code."""

    OFF = "off", "Off"
    # Request owners when a pull request opens ready for review or is marked ready.
    ALWAYS = "always", "Always"
    # Request owners only when stamphog does not approve. An approval requests only pinned owners.
    FALLBACK = "fallback", "When stamphog does not approve"


class RoutingStatus(LabeledStrEnum):
    """The phase of a pull request's latest reviewer routing record."""

    # FALLBACK only: the head waits for stamphog's verdict or for the safety net.
    WAITING = "waiting", "Waiting for stamphog's verdict"
    # A task holds the claim and has not requested anybody yet.
    ROUTING = "routing", "Routing"
    # The review requests went out and the routing comment is not finished yet.
    REQUESTED = "requested", "Requested"
    DONE = "done", "Done"


class OwnersFileStatus(LabeledStrEnum):
    """Whether a repository's default branch has the root owners.yaml that reviewer routing reads."""

    FOUND = "found", "Found"
    MISSING = "missing", "Missing"
    # The check could not ask GitHub: no installation to read with, or GitHub answered with an error.
    UNAVAILABLE = "unavailable", "Unavailable"


class RoutingScope(LabeledStrEnum):
    """Which owners one reviewer routing run may request."""

    FULL = "full", "Every owner"
    # A stamphog approval asks only the owners of sensitive and new paths.
    PINNED = "pinned", "Pinned owners only"


class OwnerKind(LabeledStrEnum):
    """Whether an owners.yaml owner is a GitHub team (`team-devex`) or a person (`@alice`)."""

    TEAM = "team", "Team"
    PERSON = "person", "Person"


class PinReason(LabeledStrEnum):
    """Why a changed path pins its owner, so the cut step can never remove them."""

    SENSITIVE = "sensitive", "Sensitive path"
    NEW_PATH = "new_path", "New path"


class LlmSkipReason(LabeledStrEnum):
    """Why reviewer routing made no model call for a pull request."""

    SINGLE_CANDIDATE = "single_candidate", "Single candidate"
    # Fork pull requests get the deterministic list: the author of a fork controls the whole prompt.
    FORK = "fork", "Fork"
    NOTHING_CUTTABLE = "nothing_cuttable", "Nothing cuttable"
    NO_ANSWER = "no_answer", "No answer"
    # Kept for older runs: an approved head once skipped the model. Approved heads now ask it like any other.
    STAMPHOG_APPROVED = "stamphog_approved", "Stamphog approved"
    # GitHub listed fewer files than the pull request changes, so the model would judge a partial diff.
    FILES_TRUNCATED = "files_truncated", "Files truncated"


class RoutingOwnerOutcome(LabeledStrEnum):
    """What one reviewer routing run did with one owner of the changed code."""

    REQUESTED = "requested", "Requested"
    # A fork pull request labels a team that has a fork label, instead of requesting its review.
    LABELED = "labeled", "Labeled"
    # Requested, and GitHub refused the request, for example for a team without access to the repository.
    REFUSED = "refused", "Refused by GitHub"
    CUT = "cut", "Cut"
    # Stamphog approved the head, so the routing asked only the owners of sensitive and new paths. The model
    # kept this owner, so routing would have asked it without the approval. On an older run whose llm_skipped is
    # STAMPHOG_APPROVED, no model ran, and it means only that the owner owns changed code.
    NOT_REQUESTED = "not_requested", "Not requested"
    # A pinned owner that an earlier routing of the pull request already requested.
    ALREADY_REQUESTED = "already_requested", "Already requested"


class RoutingOwnerReason(LabeledStrEnum):
    """Why one reviewer routing run kept or cut one owner."""

    # The same values as `PinReason`, because a pin is the reason.
    SENSITIVE = "sensitive", "Owns a sensitive path"
    NEW_PATH = "new_path", "Owns a new path"
    # The guards keep the owner with the largest part, so a pull request always keeps a reviewer.
    LARGEST_OWNER = "largest_owner", "Has the largest part"
    # Some of the owner's diff did not fit the prompt, so the model could not judge the owner.
    DIFF_NOT_SEEN = "diff_not_seen", "Diff not shown to the model"
    # The cut step made no model call. The run's llm_skipped says why.
    CUT_SKIPPED = "cut_skipped", "Cut step skipped"
    MODEL_KEPT = "model_kept", "Kept by the model"
    MODEL_CUT = "model_cut", "Cut by the model"
    # Kept for older runs, which logged every unpinned owner of an approved head with this reason.
    STAMPHOG_APPROVED = "stamphog_approved", "Stamphog approved"


# The pull_request actions that start a reviewer routing run. The webhook consumer imports this at
# module level, so it lives in this light module.
ROUTING_ACTIONS = frozenset({"opened", "ready_for_review"})


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


class ReviewTrigger(LabeledStrEnum):
    """What caused a run to exist, derived from the run and its repo config.

    Not stored: a run records `inbox_review` or `manual_review` provenance on its output (a silent
    run only its stamped `review_trigger`) and inherits the repo's review_mode, and this collapses
    them into the one answer a reader wants — why did stamphog look at this PR at all.
    """

    # Self-driving: stamphog reviewed a bot-authored PR off its own inbox provenance.
    SELF_DRIVING = "self_driving", "Self-driving"
    # The repo policy names the PR's bot author under `bot_authors`.
    BOT_ADMISSION = "bot_admission", "Bot author"
    # A project member asked for this review through the API.
    MANUAL = "manual", "Manual"
    # A clean PostHog Review run started this review. It is silent: only an approval reaches the PR.
    REVIEWHOG_CLEAN = "reviewhog_clean", "Clean PostHog Review"
    # The repo is in LABEL mode, so the trigger label opted this PR in.
    LABEL = "label", "Label"
    # The repo reviews every relevant PR event.
    ALL = "all", "All"


class ReviewRequestRefusal(StrEnum):
    """Why a manual review request did not queue a run. The message carries the specific reason."""

    NOT_FOUND = "not_found"
    NOT_REVIEWABLE = "not_reviewable"
    GITHUB_UNAVAILABLE = "github_unavailable"


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
