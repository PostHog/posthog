"""The notes a published review ends with, and the comment-commands rollout check they depend on."""

from posthog.models.team import Team
from posthog.permissions import posthog_feature_flag_enabled

# The rollout flag of `@posthog` pull request comments (products/commands). Read here by key,
# because the commands product already depends on this product.
COMMENT_COMMANDS_FLAG = "github-commands"


def comment_commands_enabled(team_id: int) -> bool:
    """Whether `@posthog` comments run for this project's organization, so the review may point to them."""
    organization_id = Team.objects.values_list("organization_id", flat=True).filter(id=team_id).first()
    if organization_id is None:
        return False
    return posthog_feature_flag_enabled(
        COMMENT_COMMANDS_FLAG, f"review-hog-team-{team_id}", organization_id=organization_id, team_id=team_id
    )


def _review_trigger(comment_commands_on: bool) -> str:
    return "Comment `@posthog review`" if comment_commands_on else "Start a review in PostHog Review"


def draft_review_notice(comment_commands_on: bool) -> str:
    """The note an automatic review of a draft with findings ends with: draft pushes get no automatic review."""
    return (
        "This is the only automatic review while this pull request is a draft. "
        f"{_review_trigger(comment_commands_on)} to review new changes sooner. "
        "Otherwise, a review of the new changes runs when you mark it ready for review."
    )


def last_review_notice(comment_commands_on: bool) -> str:
    """The note an automatic review with findings ends with when the repository does not review later pushes."""
    return (
        "This is the last automatic review of this pull request. "
        f"{_review_trigger(comment_commands_on)} to review new changes."
    )


def first_review_note(review_link: str, deep_command: bool) -> str:
    """The note the first review on a pull request ends with: where to see the review, and how to ask for Deep."""
    note = f"See this review and its findings in [PostHog Review]({review_link})."
    if deep_command:
        note = (
            f"{note} Comment `@posthog review --deep` for a Deep review. "
            "A Deep review takes longer and looks deeper than a Standard review."
        )
    return note
