"""
Exported enums for stamphog.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic/, models.py).
"""

from enum import StrEnum


class ReviewRunStatus(StrEnum):
    QUEUED = "queued"
    GATED = "gated"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"


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
