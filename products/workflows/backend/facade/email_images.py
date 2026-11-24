"""Copying images another email tool hosts into the team's email media library."""

from collections.abc import Iterable, Sequence

from posthog.models import Team, User
from posthog.scopes.checks import scopes_not_covered

from products.workflows.backend.facade.api import can_edit_media
from products.workflows.backend.facade.contracts import CopiedImages, EmailImageSource, ImageBudget
from products.workflows.backend.services import email_images


def can_upload_media(*, team_id: int, user_id: int | None, scopes: Sequence[str] | None) -> bool:
    """Whether a request may write to the media library. `scopes` is None for a session, which has no scopes."""
    if scopes is not None and "*" not in scopes and scopes_not_covered(list(scopes), ["uploaded_media:write"]):
        return False
    return can_edit_media(team_id=team_id, user_id=user_id)


def is_hosted(url: str, source: EmailImageSource) -> bool:
    """Whether `url` is an https address on one of the tool's image hosts."""
    return email_images.is_hosted(url, source)


def copy_images_for_team(
    team_id: int, user_id: int, urls: Iterable[str], source: EmailImageSource, *, max_images: int, deadline: float
) -> CopiedImages:
    """Copy at most `max_images` images, until `deadline`, a `time.monotonic()` value."""
    team = Team.objects.get(id=team_id)
    # nosemgrep: idor-lookup-without-team (the caller checked this user's access to the team)
    user = User.objects.get(id=user_id)
    budget = ImageBudget(remaining=max_images, deadline=deadline)
    copies = email_images.copy_images(team, user, urls, source, budget)
    return CopiedImages(copies=copies, downloads=max_images - budget.remaining)
