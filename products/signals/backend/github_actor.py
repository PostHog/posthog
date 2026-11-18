"""The GitHub handle of the person behind a report transition.

Suppressing or resolving a report closes the implementation pull request and the tracker issue
through the team's GitHub App, so GitHub credits the App for both closes and the person who made
the call is invisible on GitHub. The comment we leave next to the close is the only place that can
carry them, and this module renders the mention it uses.

Only a GitHub login is ever rendered. A PostHog name or email address would put an identity into a
repository whose audience we do not know, and it would link to nothing on GitHub.

Best-effort by contract: the report is already dismissed by the time any of this runs, so a handle
that will not resolve degrades to an unattributed comment instead of holding up the close.
"""

from __future__ import annotations

import re

import structlog

from posthog.models.user import User

logger = structlog.get_logger(__name__)

# The mention is interpolated into markdown we post to GitHub, and a login reaches us from
# integration config rather than from GitHub's API on every read. GitHub itself allows only these
# characters in a login, so anything else is not a handle worth rendering.
GITHUB_LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def github_mention_for_user(user_id: int | None) -> str | None:
    """The actor's ``@handle`` for a GitHub comment, or ``None`` when no handle resolves.

    ``None`` covers every case where naming somebody would be wrong or impossible: an automated
    transition with no person behind it, a person who never connected a GitHub identity, and a
    lookup that failed.
    """
    if user_id is None:
        return None
    try:
        user = User.objects.filter(id=user_id).first()
        login = user.get_github_login() if user is not None else None
    except Exception:
        logger.warning("signals.github_actor_lookup_failed", user_id=user_id, exc_info=True)
        return None
    if not login or not GITHUB_LOGIN_PATTERN.match(login):
        return None
    return f"@{login}"
