from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_POST_COLUMNS = {
    "id": "Unique identifier of the post.",
    "text": "The content of the post.",
    "created_at": "Creation time of the post.",
    "author_id": "Unique identifier of the user who posted it.",
    "conversation_id": "The post ID of the original post in the conversation this post belongs to.",
    "in_reply_to_user_id": "If the post is a reply, the user ID of the account the reply answers.",
    "referenced_tweets": "A list of posts this post refers to, with the type of reference (replied_to, quoted, retweeted).",
    "public_metrics": "Engagement counts anyone can see: retweet_count, reply_count, like_count, quote_count, bookmark_count and impression_count.",
    "lang": "Language of the post, as a BCP47 tag detected by X.",
    "entities": "Entities X parsed out of the text: hashtags, cashtags, mentions, URLs and annotations.",
    "attachments": "Media keys and poll IDs for the media and polls attached to the post.",
    "geo": "Place ID and coordinates attached to the post.",
    "possibly_sensitive": "Whether the content may be recognized as sensitive.",
    "reply_settings": "Who can reply to the post: everyone, mentionedUsers or followers.",
    "edit_controls": "When the post's edit window closes, how many edits remain, and whether it is still editable.",
    "edit_history_tweet_ids": "Post IDs of every version of this post, oldest first.",
    "note_tweet": "The full text and entities of a long-form post, which `text` truncates.",
    "withheld": "Countries the post is withheld in, and the reason.",
}

_USER_COLUMNS = {
    "id": "Unique identifier of the account.",
    "username": "The account's handle, without the leading @.",
    "name": "The account's display name.",
    "created_at": "Creation time of the account.",
    "description": "The account's bio text.",
    "entities": "URLs, hashtags, cashtags and mentions parsed out of the bio and the profile URL.",
    "location": "The location the account reports in its profile. Free text, not validated.",
    "most_recent_tweet_id": "Post ID of the account's most recent post.",
    "pinned_tweet_id": "Post ID of the post pinned to the account's profile.",
    "profile_image_url": "URL of the account's profile image.",
    "protected": "Whether the account's posts are visible only to its followers.",
    "public_metrics": "Audience counts anyone can see: followers_count, following_count, tweet_count, listed_count and like_count.",
    "url": "The URL in the account's profile.",
    "verified": "Whether the account is verified.",
    "verified_type": "The kind of verification on the account: blue, business, government or none.",
    "withheld": "Countries the account is withheld in, and the reason.",
}

_DOCS_POSTS = "https://docs.x.com/x-api/posts/user-posts-timeline-by-user-id"
_DOCS_USERS = "https://docs.x.com/x-api/users/user-lookup-by-usernames"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Profile": {
        "description": "The public profile of the X account this source is connected to, one row per sync.",
        "docs_url": _DOCS_USERS,
        "columns": _USER_COLUMNS,
    },
    "Posts": {
        "description": "Posts composed by the connected account, including replies and reposts.",
        "docs_url": _DOCS_POSTS,
        "columns": _POST_COLUMNS,
    },
    "Mentions": {
        "description": "Posts by other accounts that mention the connected account.",
        "docs_url": "https://docs.x.com/x-api/posts/user-mention-timeline-by-user-id",
        "columns": _POST_COLUMNS,
    },
    "LikedPosts": {
        "description": "Posts the connected account has liked.",
        "docs_url": "https://docs.x.com/x-api/users/get-liked-posts",
        "columns": _POST_COLUMNS,
    },
    "Followers": {
        "description": "Accounts that follow the connected account, one row per follower.",
        "docs_url": "https://docs.x.com/x-api/users/followers-by-user-id",
        "columns": _USER_COLUMNS,
    },
    "Following": {
        "description": "Accounts the connected account follows, one row per followed account.",
        "docs_url": "https://docs.x.com/x-api/users/following-by-user-id",
        "columns": _USER_COLUMNS,
    },
    "OwnedLists": {
        "description": "Lists owned by the connected account.",
        "docs_url": "https://docs.x.com/x-api/users/get-owned-lists",
        "columns": {
            "id": "Unique identifier of the list.",
            "name": "The name of the list.",
            "created_at": "Creation time of the list.",
            "description": "A short description of the list.",
            "follower_count": "Number of accounts following the list.",
            "member_count": "Number of accounts on the list.",
            "owner_id": "Unique identifier of the account that owns the list.",
            "private": "Whether the list is visible only to its owner.",
        },
    },
}
