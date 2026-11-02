"""Canonical, documentation-sourced descriptions for Beamer endpoints and columns.

Sourced from the official Beamer API reference (https://www.getbeamer.com/help/beamer-api-documentation).
Keyed by the endpoint names in `settings.py` `BEAMER_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Beamer table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "posts": {
        "description": "A changelog post / announcement (the notifications shown in the Beamer feed and widget).",
        "docs_url": "https://www.getbeamer.com/help/beamer-api-documentation",
        "columns": {
            "id": "Unique identifier for the post.",
            "date": "Date the post was published.",
            "dueDate": "Date the post is scheduled to expire, if set.",
            "published": "Whether the post is currently published.",
            "pinned": "Whether the post is pinned to the top of the feed.",
            "category": "The post's category (e.g. new, improvement, fix).",
            "translations": "Per-language title, content, and link for the post.",
            "feedbackEnabled": "Whether readers can leave feedback on the post.",
            "reactionsEnabled": "Whether readers can react to the post.",
            "views": "Total number of views.",
            "uniqueViews": "Number of unique users who viewed the post.",
            "clicks": "Number of clicks on the post's link.",
            "feedbacks": "Number of feedback responses received.",
            "positiveReactions": "Count of positive reactions.",
            "neutralReactions": "Count of neutral reactions.",
            "negativeReactions": "Count of negative reactions.",
        },
    },
    "feature_requests": {
        "description": "An Idea / feature request submitted on the Beamer roadmap, with vote and comment counts.",
        "docs_url": "https://www.getbeamer.com/help/beamer-api-documentation",
        "columns": {
            "id": "Unique identifier for the feature request.",
            "date": "Date the feature request was created.",
            "visible": "Whether the feature request is publicly visible.",
            "category": "The feature request's category.",
            "status": "Current roadmap status (e.g. open, planned, in progress, done).",
            "translations": "Per-language title and content for the feature request.",
            "votesCount": "Number of votes the feature request has received.",
            "commentsCount": "Number of comments on the feature request.",
            "userId": "Your identifier for the user who submitted the request.",
            "userEmail": "Email of the user who submitted the request.",
        },
    },
    "nps": {
        "description": "A Net Promoter Score (NPS) survey response, including the score and optional feedback.",
        "docs_url": "https://www.getbeamer.com/help/beamer-api-documentation",
        "columns": {
            "id": "Unique identifier for the NPS response.",
            "date": "Date the NPS response was submitted.",
            "score": "The NPS score the user gave (0-10).",
            "feedback": "Free-text feedback the user left with the score.",
            "userId": "Your identifier for the responding user.",
            "userEmail": "Email of the responding user.",
            "url": "URL the user was on when they responded.",
        },
    },
    "users": {
        "description": "An end user tracked by Beamer (Scale plan only), with first/last seen and location data.",
        "docs_url": "https://www.getbeamer.com/help/beamer-api-documentation",
        "columns": {
            "beamerId": "Beamer's internal unique identifier for the user.",
            "userId": "Your identifier for the user.",
            "userEmail": "The user's email address.",
            "firstSeen": "Timestamp the user was first seen.",
            "lastSeen": "Timestamp the user was last seen.",
            "browser": "The user's browser.",
            "os": "The user's operating system.",
            "city": "The user's city, derived from IP.",
            "country": "The user's country, derived from IP.",
        },
    },
    "post_comments": {
        "description": "A comment left by a user on a changelog post.",
        "docs_url": "https://www.getbeamer.com/help/beamer-api-documentation",
        "columns": {
            "id": "Unique identifier for the comment.",
            "post_id": "Identifier of the post the comment belongs to (injected during sync).",
            "date": "Date the comment was created.",
            "text": "The comment text.",
            "postTitle": "Title of the post the comment is on.",
            "userId": "Your identifier for the commenting user.",
            "userEmail": "Email of the commenting user.",
        },
    },
    "post_reactions": {
        "description": "A reaction left by a user on a changelog post.",
        "docs_url": "https://www.getbeamer.com/help/beamer-api-documentation",
        "columns": {
            "id": "Unique identifier for the reaction.",
            "post_id": "Identifier of the post the reaction belongs to (injected during sync).",
            "date": "Date the reaction was created.",
            "reaction": "The reaction type (e.g. positive, neutral, negative).",
            "postTitle": "Title of the post the reaction is on.",
            "userId": "Your identifier for the reacting user.",
            "userEmail": "Email of the reacting user.",
        },
    },
    "feature_request_comments": {
        "description": "A comment left on a feature request / Idea.",
        "docs_url": "https://www.getbeamer.com/help/beamer-api-documentation",
        "columns": {
            "id": "Unique identifier for the comment.",
            "feature_request_id": "Identifier of the feature request the comment belongs to (injected during sync).",
            "date": "Date the comment was created.",
            "text": "The comment text.",
            "featureRequestTitle": "Title of the feature request the comment is on.",
            "userId": "Your identifier for the commenting user.",
            "userEmail": "Email of the commenting user.",
        },
    },
    "feature_request_votes": {
        "description": "A vote cast by a user on a feature request / Idea.",
        "docs_url": "https://www.getbeamer.com/help/beamer-api-documentation",
        "columns": {
            "id": "Unique identifier for the vote.",
            "feature_request_id": "Identifier of the feature request the vote belongs to (injected during sync).",
            "date": "Date the vote was cast.",
            "featureRequestTitle": "Title of the feature request the vote is on.",
            "userId": "Your identifier for the voting user.",
            "userEmail": "Email of the voting user.",
        },
    },
}
