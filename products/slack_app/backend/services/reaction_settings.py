"""The emoji reactions PostHog adds to Slack messages, stored in ``SlackSettings.reactions``.

A personal row and the workspace-wide row store the same shape, keyed by ``SlackReactionKind``:
``{"working": {"emoji": "eyes", "enabled": true}}``. Each reaction falls back field by field: the
personal choice, then the workspace choice, then ``DEFAULT_REACTIONS``. The defaults match what
PostHog did before reactions could be configured.
"""

from __future__ import annotations

import re

from products.slack_app.backend.facade.enums import SlackReactionKind
from products.slack_app.backend.facade.types import SlackReactionChoice, SlackResolvedReaction

# Slack emoji names: lowercase letters, digits, and the characters - _ + ', with an optional skin tone
# such as ``thumbsup::skin-tone-3``.
EMOJI_NAME = re.compile(r"^[a-z0-9_+'\-]{1,100}(::skin-tone-[2-6])?$")

DEFAULT_REACTIONS: dict[SlackReactionKind, SlackResolvedReaction] = {
    SlackReactionKind.WORKING: SlackResolvedReaction(emoji="eyes", enabled=True),
    SlackReactionKind.DONE: SlackResolvedReaction(emoji="white_check_mark", enabled=False),
    SlackReactionKind.ERROR: SlackResolvedReaction(emoji="warning", enabled=False),
    SlackReactionKind.POLITE: SlackResolvedReaction(emoji="orange_heart", enabled=True),
}

ReactionSettings = dict[SlackReactionKind, SlackReactionChoice]


def normalize_emoji_name(value: str) -> str:
    """Accept ``:tada:`` as well as ``tada``, the way people copy emoji names out of Slack."""
    return value.strip().strip(":").strip().lower()


def is_emoji_name(value: str) -> bool:
    return EMOJI_NAME.match(value) is not None


def parse_reactions(stored: object) -> ReactionSettings:
    """Read a stored ``reactions`` value. Unknown kinds and malformed fields are left out."""
    if not isinstance(stored, dict):
        return {}
    parsed: ReactionSettings = {}
    for key, value in stored.items():
        if key not in SlackReactionKind.values or not isinstance(value, dict):
            continue
        emoji = value.get("emoji")
        enabled = value.get("enabled")
        parsed[SlackReactionKind(key)] = SlackReactionChoice(
            emoji=emoji if isinstance(emoji, str) and is_emoji_name(emoji) else None,
            enabled=enabled if isinstance(enabled, bool) else None,
        )
    return parsed


def serialize_reactions(reactions: ReactionSettings) -> dict[str, dict[str, str | bool]] | None:
    """The JSON to store. Choices that inherit everything are left out, and an empty result stores NULL."""
    stored: dict[str, dict[str, str | bool]] = {}
    for kind, choice in reactions.items():
        entry: dict[str, str | bool] = {}
        if choice.emoji is not None:
            entry["emoji"] = choice.emoji
        if choice.enabled is not None:
            entry["enabled"] = choice.enabled
        if entry:
            stored[kind.value] = entry
    return stored or None


def with_every_kind(reactions: ReactionSettings) -> ReactionSettings:
    return {kind: reactions.get(kind, SlackReactionChoice()) for kind in SlackReactionKind}


def resolve_reactions(
    workspace: ReactionSettings, personal: ReactionSettings
) -> dict[SlackReactionKind, SlackResolvedReaction]:
    resolved: dict[SlackReactionKind, SlackResolvedReaction] = {}
    for kind, default in DEFAULT_REACTIONS.items():
        mine = personal.get(kind, SlackReactionChoice())
        theirs = workspace.get(kind, SlackReactionChoice())
        resolved[kind] = SlackResolvedReaction(
            emoji=next((e for e in (mine.emoji, theirs.emoji) if e is not None), default.emoji),
            enabled=next((e for e in (mine.enabled, theirs.enabled) if e is not None), default.enabled),
        )
    return resolved


def load_reactions(slack_workspace_id: str, slack_user_id: str | None) -> ReactionSettings:
    """The stored choices of one row: the personal row for a Slack user, or the workspace row for None."""
    from products.slack_app.backend.models import SlackSettings

    stored = (
        SlackSettings.objects.filter(slack_workspace_id=slack_workspace_id, slack_user_id=slack_user_id)
        .values_list("reactions", flat=True)
        .first()
    )
    return parse_reactions(stored)


def save_reactions(slack_workspace_id: str, slack_user_id: str | None, reactions: ReactionSettings) -> None:
    """Replace the stored choices of one row. The caller checks that the actor may change it."""
    from products.slack_app.backend.models import SlackSettings

    SlackSettings.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_user_id=slack_user_id,
        defaults={"reactions": serialize_reactions(reactions)},
    )
