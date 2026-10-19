from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://api-doc.channel.io/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "user_chats": {
        "description": "Conversations between end users and the team in the Channel desk.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique user chat identifier.",
            "channelId": "Id of the channel the chat belongs to.",
            "userId": "Id of the user who owns the chat.",
            "state": "Chat state: opened, snoozed, queued, initial, missed or closed.",
            "assigneeId": "Id of the manager the chat is assigned to.",
            "managerIds": "Ids of the managers taking part in the chat.",
            "tags": "Chat tags attached to the chat.",
            "name": "Chat name.",
            "createdAt": "Time the chat was created.",
            "updatedAt": "Time the chat was last updated.",
            "deskUpdatedAt": "Time of the most recent desk activity in the chat.",
            "openedAt": "Time the chat was last opened.",
            "closedAt": "Time the chat was closed.",
            "firstOpenedAt": "Time the chat was first opened.",
        },
    },
    "messages": {
        "description": "Messages in user chats, one row per message.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique message identifier.",
            "chatId": "Id of the user chat the message belongs to.",
            "chatType": "Type of chat the message was posted in.",
            "personType": "Type of author, such as user, manager or bot.",
            "personId": "Id of the author.",
            "plainText": "Message body without formatting.",
            "blocks": "Structured message body.",
            "files": "Files attached to the message.",
            "createdAt": "Time the message was created.",
            "updatedAt": "Time the message was last updated.",
            "userChatDeskUpdatedAt": "Desk activity time of the parent chat when the message was read. Drives incremental sync.",
        },
    },
    "managers": {
        "description": "Team members who handle chats in the Channel desk.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique manager identifier.",
            "accountId": "Id of the manager's Channel.io account.",
            "name": "Manager name.",
            "email": "Manager email address.",
            "operator": "Whether the manager is an operator who receives chats.",
            "removed": "Whether the manager was removed from the channel.",
            "createdAt": "Time the manager was added.",
            "updatedAt": "Time the manager was last updated.",
        },
    },
    "groups": {
        "description": "Public team chat groups in the channel.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique group identifier.",
            "title": "Group name.",
            "scope": "Group visibility scope.",
            "managerIds": "Ids of the managers in the group.",
            "createdAt": "Time the group was created.",
            "updatedAt": "Time the group was last updated.",
        },
    },
    "chat_tags": {
        "description": "Tags available for classifying user chats.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique chat tag identifier.",
            "name": "Tag name.",
            "key": "Tag key.",
            "description": "Tag description.",
            "createdAt": "Time the tag was created.",
        },
    },
    "bots": {
        "description": "Bots that post messages in the channel.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique bot identifier.",
            "name": "Bot name.",
            "description": "Bot description.",
            "createdAt": "Time the bot was created.",
        },
    },
    "campaigns": {
        "description": "Marketing campaigns that message users when they trigger an event.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique campaign identifier.",
            "name": "Campaign name.",
            "state": "Campaign state: active, stopped or draft.",
            "mediumType": "Channel the campaign sends through.",
            "triggerEventName": "Event that triggers the campaign.",
            "goalEventName": "Event that counts as the campaign goal.",
            "startAt": "Time the campaign starts.",
            "endAt": "Time the campaign ends.",
            "createdAt": "Time the campaign was created.",
            "updatedAt": "Time the campaign was last updated.",
        },
    },
}
