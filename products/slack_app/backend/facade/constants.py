"""Slack values that other products' read rules depend on, kept free of Django imports so HogQL can load them."""

# Narrower than "not private", for a reader that acts for no person, such as a Signals scout or a
# `system.*` table. What such a reader returns can reach the whole project, and only a public channel
# is open to every member of the workspace. A private channel and a group DM have a closed
# membership, and a thread nobody classified may be either, so only a thread known to be in a public
# channel qualifies. Values are `SlackThreadTaskMapping.ConversationType` values.
PUBLIC_CHANNEL_CONVERSATION_TYPES: frozenset[str] = frozenset({"public_channel"})

__all__ = ["PUBLIC_CHANNEL_CONVERSATION_TYPES"]
