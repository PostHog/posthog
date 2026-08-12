"""Business logic for user_interviews.

Holds the parsing rules and ORM queries that back the facade. The facade
(`facade/api.py`) stays thin and delegates here; tests and other internal
modules within this product may call these helpers directly, but external
products must keep going through the facade.
"""

import re
import uuid
from uuid import UUID

from products.user_interviews.backend.facade.contracts import IntervieweeIdentity
from products.user_interviews.backend.models import (
    EmailWithDisplayNameValidator,
    UserInterview,
    UserInterviewClassification,
)

# distinct_id rules ported from rust/capture (`CAPTURE_V1_DISTINCT_ID_MAX_SIZE` and
# `ILLEGAL_DISTINCT_IDS` in v1/analytics/constants.rs). On the shared interview link these are
# best-effort person/session linkage hints from an untrusted public page, so an invalid value is
# dropped (ignored), never a reason to reject the interview.
DISTINCT_ID_MAX_CHARS = 200
ILLEGAL_DISTINCT_IDS = frozenset(
    {
        "0",
        "00000000-0000-0000-0000-000000000000",
        "[object object]",
        "anonymous",
        "anonymous-user",
        "backend",
        "distinct_id",
        "distinctid",
        "email",
        "false",
        "guest",
        "id",
        "nan",
        "none",
        "not_authenticated",
        "null",
        "system",
        "true",
        "undefined",
        "user",
    }
)


def valid_distinct_id(value: object) -> str:
    """Return a usable distinct_id, or "" if it fails the canonical capture rules (empty, longer
    than the 200-char limit, or a known-bad sentinel). Dropped, not rejected — it's a linkage hint.
    A too-long id is dropped rather than truncated: a truncated distinct_id would never match a real
    person, so keeping it would be misleading."""
    if not value:
        return ""
    candidate = str(value).strip()
    if not candidate or len(candidate) > DISTINCT_ID_MAX_CHARS or candidate.lower() in ILLEGAL_DISTINCT_IDS:
        return ""
    return candidate


def valid_session_id(value: object) -> str:
    """Return the session_id only if it's a valid UUIDv7 (PostHog session IDs are UUIDv7), else "".
    Dropped, not rejected — it's a best-effort linkage hint."""
    if not value:
        return ""
    candidate = str(value).strip()
    try:
        return candidate if uuid.UUID(candidate).version == 7 else ""
    except ValueError:
        return ""


# A shared (non-personalised) interview link is modelled as an IntervieweeContext carrying this
# reserved identifier — the same machinery as a per-invitee link (and the test/dogfood link), but
# the token belongs to the whole topic and every visitor is a new anonymous respondent. Using a
# sentinel row (rather than a new field, or a new FK on the main-app SharingConfiguration) keeps this
# experiment's blast radius entirely inside the user_interviews product.
SHARED_INTERVIEWEE_IDENTIFIER = "__posthog_shared_link__"


def is_shared_interviewee_context(interviewee_identifier: str) -> bool:
    """Whether an IntervieweeContext identifier marks the topic's shared (anonymous) link."""
    return interviewee_identifier == SHARED_INTERVIEWEE_IDENTIFIER


def parse_interviewee_identifier(identifier: str) -> IntervieweeIdentity:
    """Split an interviewee identifier into a display name and (optional) email.

    Accepts the same display-name format the topic validator accepts —
    ``"Display Name <email@host>"`` — falling back to a best-effort
    title-cased local-part for raw emails and the identifier as-is for
    distinct IDs.
    """
    identifier = identifier.strip()
    display_match = re.match(EmailWithDisplayNameValidator.display_name_regex, identifier)
    if display_match:
        return IntervieweeIdentity(
            display_name=display_match.group(1).strip(),
            email=display_match.group(2).strip(),
        )
    if "@" in identifier:
        local_part = identifier.split("@", 1)[0]
        return IntervieweeIdentity(
            display_name=local_part.replace(".", " ").replace("_", " ").strip().title() or identifier,
            email=identifier,
        )
    return IntervieweeIdentity(display_name=identifier, email=None)


def has_replied(*, team_id: int, topic_id: UUID, interviewee_identifier: str) -> bool:
    """Whether a personalised (invited) interviewee has already completed an interview for this topic.

    Abandoned interviews don't count: an accidental refresh mid-call leaves an abandoned
    partial behind, and treating that as "replied" would lock the interviewee out of ever
    finishing. Only a non-abandoned response gates the personalised link.

    Shared-link responses never count: they carry a `respondent_key` and a namespaced
    `interviewee_identifier`, so this filter is defense-in-depth against a shared respondent
    (whose distinct_id is untrusted) ever being able to mark a targeted invitee as replied.
    """
    return (
        UserInterview.objects.filter(
            team_id=team_id,
            topic_id=topic_id,
            interviewee_identifier=interviewee_identifier,
            respondent_key="",
        )
        .exclude(classifications__contains=[UserInterviewClassification.ABANDONED])
        .exists()
    )
