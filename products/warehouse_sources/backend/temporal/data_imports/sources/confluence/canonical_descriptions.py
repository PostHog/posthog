"""Canonical, documentation-sourced descriptions for Confluence endpoints and columns.

Sourced from the official Confluence Cloud REST API v2 reference
(https://developer.atlassian.com/cloud/confluence/rest/v2/). Keyed by the endpoint names in
`settings.py` `CONFLUENCE_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
Confluence table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Confluence v2 content objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "title": "Title of the object.",
    "status": "Status of the object (e.g. current, draft, archived, trashed).",
    "createdAt": "Date and time the object was created.",
    "version": "Version metadata for the object, including number and creation time.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "spaces": {
        "description": "A Confluence space — a top-level container that groups related pages and content.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-space/",
        "columns": {
            "id": "Unique identifier for the space.",
            "key": "Unique key of the space, used in URLs.",
            "name": "Display name of the space.",
            "type": "Type of the space (e.g. global, personal, collaboration).",
            "status": "Status of the space (e.g. current, archived).",
            "authorId": "Account ID of the user who created the space.",
            "homepageId": "ID of the space's homepage.",
            "description": "Description of the space.",
            "createdAt": "Date and time the space was created.",
        },
    },
    "pages": {
        "description": "A Confluence page — a unit of content that lives within a space.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-page/",
        "columns": _columns(
            spaceId="ID of the space the page belongs to.",
            parentId="ID of the parent page, if the page is nested.",
            parentType="Type of the parent object (e.g. page).",
            authorId="Account ID of the user who created the page.",
            ownerId="Account ID of the page's owner.",
            position="Position of the page among its siblings.",
            body="Body content of the page in the requested representation.",
        ),
    },
    "blogposts": {
        "description": "A Confluence blog post — a dated post that lives within a space.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-blog-post/",
        "columns": _columns(
            spaceId="ID of the space the blog post belongs to.",
            authorId="Account ID of the user who created the blog post.",
            body="Body content of the blog post in the requested representation.",
        ),
    },
    "attachments": {
        "description": "A file attachment associated with a page, blog post, or other Confluence content.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-attachment/",
        "columns": _columns(
            mediaType="MIME type of the attached file.",
            mediaTypeDescription="Human-readable description of the file's media type.",
            fileSize="Size of the attached file in bytes.",
            fileId="Identifier of the underlying file in media storage.",
            comment="Comment associated with the attachment.",
            pageId="ID of the page the attachment is associated with, if any.",
            blogPostId="ID of the blog post the attachment is associated with, if any.",
            downloadLink="Relative URL to download the attachment.",
        ),
    },
    "tasks": {
        "description": "An action item (checkbox task) embedded within Confluence content.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-task/",
        "columns": {
            "id": "Unique identifier for the task.",
            "localId": "Identifier of the task within its containing content.",
            "spaceId": "ID of the space the task belongs to.",
            "pageId": "ID of the page the task is on, if any.",
            "blogPostId": "ID of the blog post the task is on, if any.",
            "status": "Status of the task (complete or incomplete).",
            "body": "Body content of the task.",
            "createdBy": "Account ID of the user who created the task.",
            "assignedTo": "Account ID of the user the task is assigned to.",
            "completedBy": "Account ID of the user who completed the task.",
            "createdAt": "Date and time the task was created.",
            "updatedAt": "Date and time the task was last updated.",
            "dueAt": "Date and time the task is due.",
            "completedAt": "Date and time the task was completed.",
        },
    },
    "labels": {
        "description": "A label (tag) that can be applied to Confluence content for categorization.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-label/",
        "columns": {
            "id": "Unique identifier for the label.",
            "name": "Name of the label.",
            "prefix": "Prefix of the label (e.g. global, my, team).",
        },
    },
    "footer_comments": {
        "description": "A footer comment left at the bottom of a Confluence page or blog post.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-comment/",
        "columns": {
            "id": "Unique identifier for the comment.",
            "status": "Status of the comment (e.g. current, deleted).",
            "pageId": "ID of the page the comment is on, if any.",
            "blogPostId": "ID of the blog post the comment is on, if any.",
            "parentCommentId": "ID of the parent comment, if this is a threaded reply.",
            "body": "Body content of the comment.",
            "version": "Version metadata for the comment.",
        },
    },
    "inline_comments": {
        "description": "An inline comment anchored to specific text within a Confluence page or blog post.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-comment/",
        "columns": {
            "id": "Unique identifier for the comment.",
            "status": "Status of the comment (e.g. current, deleted, resolved).",
            "pageId": "ID of the page the comment is on, if any.",
            "blogPostId": "ID of the blog post the comment is on, if any.",
            "parentCommentId": "ID of the parent comment, if this is a threaded reply.",
            "body": "Body content of the comment.",
            "resolutionStatus": "Resolution status of the inline comment.",
            "properties": "Inline comment properties, including the highlighted text it anchors to.",
            "version": "Version metadata for the comment.",
        },
    },
    "page_versions": {
        "description": "One entry of a page's edit history: who saved a version of the page, when, and why.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-version/",
        "columns": {
            "pageId": "ID of the page this version belongs to.",
            "number": "The version number.",
            "createdAt": "Date and time the version was created.",
            "message": "Message the author left with this version.",
            "minorEdit": "Whether the version was saved as a minor edit, which sends no notifications.",
            "authorId": "Account ID of the user who created this version.",
            "page": "Summary of the page the version belongs to, including its title and status.",
        },
    },
    "blogpost_versions": {
        "description": "One entry of a blog post's edit history: who saved a version of the post, when, and why.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-version/",
        "columns": {
            "blogpostId": "ID of the blog post this version belongs to.",
            "number": "The version number.",
            "createdAt": "Date and time the version was created.",
            "message": "Message the author left with this version.",
            "minorEdit": "Whether the version was saved as a minor edit, which sends no notifications.",
            "authorId": "Account ID of the user who created this version.",
            "blogpost": "Summary of the blog post the version belongs to, including its title and status.",
        },
    },
    "users": {
        "description": (
            "A user of the Confluence site. Resolves the account IDs that pages, blog posts, comments and "
            "versions refer to. The directory listing returns at most 10,000 users."
        ),
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-user/",
        "columns": {
            "accountId": "The account ID that uniquely identifies the user across all Atlassian products.",
            "accountType": "Type of account, for example atlassian for a person or app for a bot user.",
            "type": "Whether the user is known, unknown or anonymous.",
            "email": "Email address of the user. Empty when the user's privacy settings hide it.",
            "publicName": "Public name or nickname of the user. Always set.",
            "displayName": "Display name of the user. Matches publicName when privacy settings hide the real name.",
            "timeZone": "Time zone of the user. Empty when the user's privacy settings hide it.",
            "profilePicture": "Links and dimensions of the user's profile picture.",
            "isExternalCollaborator": "Whether the user is a guest rather than a licensed member of the site.",
        },
    },
    "groups": {
        "description": "A user group on the Confluence site, used to grant permissions to sets of people.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-group/",
        "columns": {
            "id": "Unique identifier for the group.",
            "name": "Name of the group.",
            "type": "Object type, always group.",
            "usageType": "Whether the collection of users is used as a group or as a team.",
            "managedBy": "Who manages the group: admins, an external directory, its members, or nobody.",
        },
    },
    "group_members": {
        "description": "The membership junction between groups and users: one row per user per group.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-group/",
        "columns": {
            "groupId": "ID of the group the user belongs to.",
            "accountId": "The account ID that uniquely identifies the member.",
            "accountType": "Type of account, for example atlassian for a person or app for a bot user.",
            "email": "Email address of the member. Empty when the user's privacy settings hide it.",
            "publicName": "Public name or nickname of the member.",
            "displayName": "Display name of the member.",
        },
    },
    "page_views": {
        "description": "The total number of times a page has been viewed.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-analytics/",
        "columns": {
            "pageId": "ID of the page the count belongs to.",
            "id": "The content ID the API reported the count for.",
            "count": "Total number of views for the page.",
        },
    },
    "page_viewers": {
        "description": "The number of distinct people who have viewed a page.",
        "docs_url": "https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-analytics/",
        "columns": {
            "pageId": "ID of the page the count belongs to.",
            "id": "The content ID the API reported the count for.",
            "count": "Total number of distinct viewers for the page.",
        },
    },
}
