"""Permissions that gate publishing a skill to the community marketplace."""

from typing import TYPE_CHECKING, cast

from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from .community_skills import CommunitySkillFeatureFlagPermission
from .skill_services import get_skill_by_name_from_db, resolve_skill_owners

if TYPE_CHECKING:
    from .skills import LLMSkillViewSet


class CommunityPublishFeatureFlagPermission(CommunitySkillFeatureFlagPermission):
    """Gates publishing to the community marketplace, and nothing else on this viewset.

    The Skills product is GA and the marketplace is not, so the flag can only bind to the one action —
    otherwise the whole product goes dark, and without it publish goes live everywhere the moment the
    GitHub App is installed and the 503 fail-safe stops firing.
    """

    def has_permission(self, request, view) -> bool:
        if getattr(view, "action", None) != "publish_to_community":
            return True
        return super().has_permission(request, view)


class CommunityPublishOwnerPermission(BasePermission):
    """Restricts publishing to the community to the skill's own owners, and gates nothing else here.

    Publishing writes the skill into a public repository, so it asks for a stronger claim on the skill
    than editing it does. The claim must also be per skill. `AccessControlPermission.has_permission`
    passes a member who holds an object-level grant on any one skill, and the `name/<slug>` actions
    then load whichever skill the URL names, so edit access alone reaches every skill in the project.

    A skill with no current owners is publishable by nobody. Owners leave the set when a member loses
    project access, and a skill can be created with an explicit empty owner list, so the alternative is
    a fallback to edit access for exactly the skills that have nobody to answer for them. Adding an
    owner is the remedy, and the message says so.
    """

    NO_OWNERS_MESSAGE = "This skill has no owners. Add an owner to publish it."
    NOT_OWNER_MESSAGE = (
        "Only an owner can publish this skill to the community. Ask an owner to publish it, or to add you as one."
    )

    def has_permission(self, request: Request, view: APIView) -> bool:
        if getattr(view, "action", None) != "publish_to_community":
            return True

        user = request.user
        if not user or not user.is_authenticated:
            return False

        skill_view = cast("LLMSkillViewSet", view)
        try:
            team = skill_view.team
        except (ValueError, KeyError, AttributeError):
            return False

        skill_name = skill_view.kwargs.get("skill_name") or ""
        owners = resolve_skill_owners(team, skill_name)
        if any(owner.pk == user.pk for owner in owners):
            return True

        # A slug that names no skill answers 404, the way every other `name/<slug>` action answers it,
        # because a skill that does not exist has no owners either. Raising here rather than passing
        # keeps the action from loading a skill another request creates in between.
        if get_skill_by_name_from_db(team, skill_name) is None:
            raise NotFound(f"Skill with name '{skill_name}' not found.")

        self.message = self.NO_OWNERS_MESSAGE if not owners else self.NOT_OWNER_MESSAGE
        return False
