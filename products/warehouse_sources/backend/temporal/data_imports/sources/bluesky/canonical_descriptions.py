"""Canonical, documentation-sourced descriptions for Bluesky (AT Protocol) endpoints and columns.

Sourced from the official Bluesky HTTP API reference (https://docs.bsky.app/docs/category/http-reference).
Keyed by the resource names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Bluesky table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Profile": {
        "description": "The configured account's public Bluesky profile.",
        "docs_url": "https://docs.bsky.app/docs/api/app-bsky-actor-get-profile",
        "columns": {
            "did": "The account's decentralized identifier, a stable, globally unique account id.",
            "handle": "The account's current handle (e.g. jay.bsky.team).",
            "displayName": "The account's display name.",
            "description": "The account's bio text.",
            "avatar": "URL of the account's avatar image.",
            "banner": "URL of the account's profile banner image.",
            "followersCount": "Number of accounts following this account.",
            "followsCount": "Number of accounts this account follows.",
            "postsCount": "Number of posts this account has made.",
            "createdAt": "Time the account was created.",
            "indexedAt": "Time the AppView last indexed this profile.",
        },
    },
    "Posts": {
        "description": "Posts and reposts from the configured account's feed, newest first.",
        "docs_url": "https://docs.bsky.app/docs/api/app-bsky-feed-get-author-feed",
        "columns": {
            "uri": "The post's AT-URI, globally unique across the network.",
            "cid": "The post record's content hash.",
            "author": "The author's profile, embedded in the post.",
            "record": "The raw post record, including its text and creation time.",
            "replyCount": "Number of replies to the post.",
            "repostCount": "Number of reposts of the post.",
            "likeCount": "Number of likes on the post.",
            "quoteCount": "Number of quote posts of the post.",
            "indexedAt": "Time the AppView first indexed the post.",
        },
    },
    "Followers": {
        "description": "Accounts following the configured account.",
        "docs_url": "https://docs.bsky.app/docs/api/app-bsky-graph-get-followers",
        "columns": {
            "did": "The follower's decentralized identifier.",
            "handle": "The follower's current handle.",
            "displayName": "The follower's display name.",
            "description": "The follower's bio text.",
            "createdAt": "Time the follower's account was created.",
            "indexedAt": "Time the AppView last indexed the follower's profile.",
        },
    },
    "Follows": {
        "description": "Accounts the configured account follows.",
        "docs_url": "https://docs.bsky.app/docs/api/app-bsky-graph-get-follows",
        "columns": {
            "did": "The followed account's decentralized identifier.",
            "handle": "The followed account's current handle.",
            "displayName": "The followed account's display name.",
            "description": "The followed account's bio text.",
            "createdAt": "Time the followed account was created.",
            "indexedAt": "Time the AppView last indexed the followed account's profile.",
        },
    },
}
