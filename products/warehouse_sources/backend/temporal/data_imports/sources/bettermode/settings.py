from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# `posts` exposes a genuine server-side timestamp filter: `filterBy` accepts the typed
# PostListFilterByEnum keys createdAt / publishedAt / updatedAt with a `gte` operator
# (Bettermode's own frontend filters trending posts with `{key: createdAt, operator: gte}`).
_POST_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "createdAt",
        "type": IncrementalFieldType.DateTime,
        "field": "createdAt",
        "field_type": IncrementalFieldType.DateTime,
    },
    {
        "label": "publishedAt",
        "type": IncrementalFieldType.DateTime,
        "field": "publishedAt",
        "field_type": IncrementalFieldType.DateTime,
    },
    {
        "label": "updatedAt",
        "type": IncrementalFieldType.DateTime,
        "field": "updatedAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]

# Node selections stick to scalars (complexity 0 in Bettermode's query-cost model) plus the
# small `reactions {reaction count}` summary, keeping each page well under the API's
# per-query complexity ceiling.
_MEMBER_NODE_FIELDS = """
id
networkId
name
username
email
status
emailStatus
roleId
teammate
tagline
locale
timeZone
score
flagged
externalId
subscribersCount
createdAt
updatedAt
lastSeenAt
verifiedAt
relativeUrl
url
"""

_SPACE_NODE_FIELDS = """
id
networkId
name
slug
description
type
groupId
createdById
private
hidden
inviteOnly
nonAdminsCanInvite
isHomepage
membersCount
postsCount
subscribersCount
externalId
createdAt
updatedAt
relativeUrl
url
"""

_POST_NODE_FIELDS = """
id
networkId
spaceId
postTypeId
title
slug
shortContent
textContent
status
language
ownerId
createdById
repliedToId
repliesCount
totalRepliesCount
reactionsCount
reactions {
reaction
count
}
isAnonymous
isHidden
locked
tagIds
externalId
createdAt
publishedAt
updatedAt
lastActivityAt
relativeUrl
url
"""

_TAG_NODE_FIELDS = """
id
title
slug
description
"""

_MODERATION_NODE_FIELDS = """
id
status
flaggedBy
description
memberId
spaceId
entity {
__typename
... on Post {
id
}
... on Member {
id
}
}
createdAt
updatedAt
"""


@dataclass
class BettermodeEndpointConfig:
    # Root query field on the GraphQL schema (e.g. `posts`, `moderationItems`).
    query_field: str
    node_fields: str
    # Extra GraphQL variables beyond `limit`/`after`: name -> GraphQL type. Declared in the
    # query document and passed through when present in the request variables.
    extra_args: dict[str, str] = field(default_factory=dict)
    page_size: int = 50
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation timestamp for partitioning; None for endpoints with no timestamps.
    partition_key: str | None = "createdAt"
    # Fan out one `replies(postId: ...)` connection per post that has replies.
    fan_out_replies: bool = False


BETTERMODE_ENDPOINTS: dict[str, BettermodeEndpointConfig] = {
    "members": BettermodeEndpointConfig(
        query_field="members",
        node_fields=_MEMBER_NODE_FIELDS,
    ),
    "spaces": BettermodeEndpointConfig(
        query_field="spaces",
        node_fields=_SPACE_NODE_FIELDS,
    ),
    "posts": BettermodeEndpointConfig(
        query_field="posts",
        node_fields=_POST_NODE_FIELDS,
        extra_args={
            "filterBy": "[PostListFilterByInput!]",
            "orderBy": "PostListOrderByEnum",
            "reverse": "Boolean",
        },
        # Post nodes carry full text content; smaller pages keep response sizes and query
        # complexity manageable.
        page_size=30,
        incremental_fields=_POST_INCREMENTAL_FIELDS,
    ),
    "replies": BettermodeEndpointConfig(
        query_field="replies",
        node_fields=_POST_NODE_FIELDS,
        extra_args={
            "postId": "ID!",
            "orderBy": "PostListOrderByEnum",
            "reverse": "Boolean",
        },
        page_size=30,
        fan_out_replies=True,
    ),
    "tags": BettermodeEndpointConfig(
        query_field="tags",
        node_fields=_TAG_NODE_FIELDS,
        page_size=100,
        partition_key=None,
    ),
    "moderation_items": BettermodeEndpointConfig(
        query_field="moderationItems",
        node_fields=_MODERATION_NODE_FIELDS,
    ),
}

ENDPOINTS = tuple(BETTERMODE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BETTERMODE_ENDPOINTS.items() if config.incremental_fields
}
