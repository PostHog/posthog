"""Slack values that other products' read rules depend on, kept free of Django imports so HogQL can load them."""

# The conversation types whose Slack tasks the whole team may read, through the tasks API, the
# `system.*` tables and Signals scouts. Only a public channel is open to every member of the
# workspace. A private channel, a group DM and a direct message have a closed membership, and a
# thread nobody classified may be any of them, so only a thread known to be in a public channel
# qualifies. Values are `SlackThreadTaskMapping.ConversationType` values.
PUBLIC_CHANNEL_CONVERSATION_TYPES: frozenset[str] = frozenset({"public_channel"})

__all__ = ["PUBLIC_CHANNEL_CONVERSATION_TYPES"]
