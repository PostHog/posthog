from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class IntervieweeIdentity:
    """Parsed interviewee identifier — display name plus optional email.

    `email` is None when the identifier was a PostHog distinct_id rather than an
    email address.
    """

    display_name: str
    email: str | None
