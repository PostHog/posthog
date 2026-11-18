"""How a derived scout note names the person whose inbox action produced it.

Scouts weigh a note by who wrote it. A dismissal from the owner of a surface outweighs one from
someone outside the area, and the same feedback from one person reads differently from the same
feedback from several. So every derived note (dismissal, discussion, feedback, reviewer correction)
names its actor the same way: `First Last (email, GitHub @login)`. The email makes the person
unambiguous and lets a scout match them to org members and to earlier scratchpad entries. The GitHub
login connects the note to the `reviewer:` routing memory, which scouts key by login.

Every part is user-controlled text in a prompt every scout reads while it holds privileged tools. So
each part is normalized to one line, so that it cannot start a new note section, and capped. Backticks
are stripped because the rendered actor never enters a backtick span:
`reviewer_correction_notes._logins_already_told` reads those spans back as suppression state, so a
quoted name could stand in for a login and silently swallow a later real correction.
"""

from __future__ import annotations

from posthog.models import User

from products.signals.backend.report_generation.resolve_reviewers import get_org_member_github_logins_by_user_uuid

_MAX_ACTOR_NAME_CHARS = 60
# The length Django's `EmailField` allows on `User.email`.
_MAX_EMAIL_CHARS = 254
_MAX_LOGIN_CHARS = 39
UNNAMED_ACTOR = "someone"


def note_actor(team_id: int, user: User | None) -> str:
    """The actor of one note, with the GitHub login looked up for the team's organization."""
    return render_actor(user, github_login=actor_github_login(team_id, user))


def actor_github_login(team_id: int, user: User | None) -> str | None:
    if user is None:
        return None
    return get_org_member_github_logins_by_user_uuid(team_id, [str(user.uuid)]).get(str(user.uuid))


def render_actor(user: User | None, *, github_login: str | None = None) -> str:
    """`First Last (email, GitHub @login)`, dropping the parts the account doesn't carry.

    Falls back to a neutral word only when nothing identifies the person, for example a dismissal
    with no user attached.
    """
    if user is None:
        return UNNAMED_ACTOR
    name = _one_line(f"{user.first_name or ''} {user.last_name or ''}", _MAX_ACTOR_NAME_CHARS)
    email = _one_line(user.email or "", _MAX_EMAIL_CHARS)
    login = _one_line(github_login or "", _MAX_LOGIN_CHARS)
    parts = [part for part in (name, email, f"GitHub @{login}" if login else "") if part]
    if not parts:
        return UNNAMED_ACTOR
    head, *details = parts
    return f"{head} ({', '.join(details)})" if details else head


def _one_line(text: str, limit: int) -> str:
    return " ".join(text.replace("`", "").split())[:limit].strip()
