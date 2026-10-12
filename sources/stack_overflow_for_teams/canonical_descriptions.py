"""Canonical, documentation-sourced descriptions for Stack Overflow for Teams v3 endpoints.

Sourced from the official v3 OpenAPI spec (https://api.stackoverflowteams.com/v3/swagger.json).
Keyed by the endpoint names in `settings.py` `STACK_OVERFLOW_FOR_TEAMS_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_API_DOCS_URL = "https://api.stackoverflowteams.com/docs"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Questions": {
        "description": "A question posted to your Stack Overflow for Teams knowledge base.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "id": "The question's unique identifier.",
            "title": "The actual question, stated briefly in one sentence.",
            "body": "The main content of the question, in HTML format.",
            "tags": "Tags associated with the question.",
            "owner": "The user who posted the question.",
            "lastEditor": "The user who last edited the question, if any.",
            "creationDate": "The date and time the question was created.",
            "lastActivityDate": "The date and time the question or one of its answers last had significant activity (edit, rollback, tag change, new answer, bounty added, bump).",
            "score": "Number of upvotes minus downvotes.",
            "isAnswered": "True if the question has at least one upvoted answer.",
            "answerCount": "Number of answers to the question.",
            "commentCount": "Number of comments on the question.",
            "viewCount": "Number of times users have viewed this question.",
            "webUrl": "The question's direct URL.",
            "shareUrl": "The question's URL for sharing.",
            "isDeleted": "True if the question was deleted.",
            "isObsolete": "True if the question was marked by a moderator as obsolete.",
            "isClosed": "True if the question was closed by a moderator.",
        },
    },
    "Answers": {
        "description": "An answer posted to a question in your Stack Overflow for Teams knowledge base.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "id": "The answer's unique identifier.",
            "questionId": "The ID of the question this answer belongs to.",
            "body": "The main content of the answer, in HTML format.",
            "score": "Number of upvotes minus downvotes.",
            "isAccepted": "True if this is the accepted answer for the question.",
            "isDeleted": "True if the answer was deleted.",
            "creationDate": "The date and time the answer was created.",
            "lockedDate": "The date and time the answer was locked, if any.",
            "lastEditDate": "The date and time the answer was last edited, if any.",
            "lastActivityDate": "The date and time the answer last had activity.",
            "deletionDate": "The date and time the answer was deleted, if any.",
            "owner": "The user who posted the answer.",
            "lastEditor": "The user who last edited the answer, if any.",
            "commentCount": "Number of comments on the answer.",
            "webUrl": "The answer's direct URL.",
            "isSubjectMatterExpert": "True if the answer is from a subject matter expert.",
        },
    },
    "Articles": {
        "description": "A knowledge-base article (Business/Enterprise tier) in your Stack Overflow for Teams site.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "id": "The article's unique identifier.",
            "type": "The article's type (e.g. knowledge article, how-to guide, policy).",
            "title": "The article's title, stated briefly in one sentence.",
            "body": "The main content of the article, in HTML format.",
            "tags": "Tags associated with the article.",
            "owner": "The user who authored the article.",
            "lastEditor": "The user who last edited the article, if any.",
            "creationDate": "The date and time the article was created.",
            "lastActivityDate": "The date and time the article last had significant activity.",
            "score": "Number of upvotes minus downvotes.",
            "commentCount": "Number of comments on the article.",
            "viewCount": "Number of times users have viewed this article.",
            "webUrl": "The article's direct URL.",
            "shareUrl": "The article's URL for sharing.",
            "isDeleted": "True if the article was deleted.",
            "isObsolete": "True if the article was marked by a moderator as obsolete.",
            "isClosed": "True if the article was closed by a moderator.",
        },
    },
    "Tags": {
        "description": "A tag used to categorize questions and articles in your Stack Overflow for Teams site.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "id": "The tag's unique identifier.",
            "name": "The tag's name.",
            "description": "The tag's description.",
            "postCount": "Number of posts that have this tag.",
            "subjectMatterExpertCount": "Total number of users who are subject matter experts for this tag (individually assigned plus members of any SME groups). Null if SMEs aren't enabled for the tag.",
            "watcherCount": "Number of users watching this tag.",
            "creationDate": "The date and time the tag was created.",
            "hasSynonyms": "True if the tag has one or more synonyms.",
            "webUrl": "The tag's web URL.",
        },
    },
    "Users": {
        "description": "A user on your Stack Overflow for Teams site.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "id": "The user's unique identifier on this site.",
            "accountId": "The user's unique account identifier across all Stack Overflow sites.",
            "externalId": "Unique external ID for the user, set via SCIM or SAML.",
            "name": "The user's name.",
            "email": "The user's email address. Only visible to admins, or for the current user.",
            "department": "The user's organizational department, set via SAML.",
            "jobTitle": "The user's organizational job title, set via SAML.",
            "avatarUrl": "URL to the user's avatar (profile picture).",
            "webUrl": "URL to the user's profile.",
            "reputation": "The user's numerical reputation.",
            "role": "The user's role on the site.",
        },
    },
    "Collections": {
        "description": "A curated collection of questions and articles in your Stack Overflow for Teams site.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "id": "The collection's unique identifier.",
            "title": "A brief title to distinguish the collection and its contents.",
            "description": "A detailed description of what the collection contains. Supports Markdown.",
            "owner": "The user who created the collection.",
            "creationDate": "The date and time the collection was created.",
            "isDeleted": "True if the collection was deleted.",
            "tags": "Tags associated with the content items in the collection.",
        },
    },
}
