from dataclasses import field
from datetime import timedelta
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

CHANNEL_IO_BASE_URL = "https://api.channel.io"
CHANNEL_IO_API_VERSION = "2026-06-01"

PAGE_LIMIT = 500
# `from` and `to` on the user chat and message lists may span 30 days at most.
MAX_FILTER_RANGE = timedelta(days=30)
# The user chat list returns one state at a time. With no `state` it returns only opened chats.
USER_CHAT_STATES: tuple[str, ...] = ("opened", "snoozed", "queued", "initial", "missed", "closed")

EndpointKind = Literal["list", "user_chats", "messages"]


@frozen
class ChannelIOEndpoint:
    name: str
    path: str
    # The response key that holds the rows.
    data_key: str
    primary_keys: tuple[str, ...] = ("id",)
    kind: EndpointKind = "list"
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)


ENDPOINTS: dict[str, ChannelIOEndpoint] = {
    "user_chats": ChannelIOEndpoint(
        name="user_chats",
        path="/open/user-chats",
        data_key="userChats",
        kind="user_chats",
        partition_key="createdAt",
        incremental_fields=[incremental_field("deskUpdatedAt")],
    ),
    "messages": ChannelIOEndpoint(
        name="messages",
        path="/open/user-chats/{user_chat_id}/messages",
        data_key="messages",
        primary_keys=("chatId", "id"),
        kind="messages",
        partition_key="createdAt",
        incremental_fields=[incremental_field("userChatDeskUpdatedAt")],
    ),
    "managers": ChannelIOEndpoint(name="managers", path="/open/managers", data_key="managers"),
    "groups": ChannelIOEndpoint(name="groups", path="/open/groups", data_key="groups"),
    "chat_tags": ChannelIOEndpoint(name="chat_tags", path="/open/chat-tags", data_key="chatTags"),
    "bots": ChannelIOEndpoint(name="bots", path="/open/bots", data_key="bots"),
    "campaigns": ChannelIOEndpoint(name="campaigns", path="/open/mkt/campaigns", data_key="campaigns"),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items()
}
