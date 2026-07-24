from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "repositories": {
        "description": "A repository indexed by the Sourcegraph instance, mirrored from a code host such as GitHub, GitLab, or Bitbucket.",
        "docs_url": "https://sourcegraph.com/docs/api/graphql",
        "columns": {
            "id": "Unique identifier for the repository (opaque GraphQL ID).",
            "databaseID": "The repository's numeric ID in the Sourcegraph database.",
            "name": "The repository's name, including the code host prefix (e.g. github.com/org/repo).",
            "description": "The repository's description from the code host.",
            "language": "The primary programming language of the repository, as detected by Sourcegraph.",
            "createdAt": "When the repository was added to the Sourcegraph instance.",
            "updatedAt": "When the repository's metadata was last updated on the Sourcegraph instance.",
            "isPrivate": "Whether the repository is private on its code host.",
            "isFork": "Whether the repository is a fork of another repository.",
            "isArchived": "Whether the repository is archived on its code host.",
            "stars": "The number of stars the repository has on its code host.",
            "url": "The repository's URL path on the Sourcegraph instance.",
            "externalRepository": "The code host the repository is mirrored from (service type and service ID).",
            "defaultBranch": "The repository's default branch ref (e.g. refs/heads/main).",
        },
    },
    "users": {
        "description": "A user account on the Sourcegraph instance. Listing users requires a site-admin access token.",
        "docs_url": "https://sourcegraph.com/docs/api/graphql",
        "columns": {
            "id": "Unique identifier for the user (opaque GraphQL ID).",
            "username": "The user's username on the Sourcegraph instance.",
            "displayName": "The user's display name.",
            "avatarURL": "URL of the user's avatar image.",
            "url": "The user's profile URL path on the Sourcegraph instance.",
            "createdAt": "When the user account was created.",
            "updatedAt": "When the user account was last updated.",
            "siteAdmin": "Whether the user is a site admin of the Sourcegraph instance.",
            "builtinAuth": "Whether the user authenticates with Sourcegraph's built-in username/password auth.",
            "emails": "The email addresses associated with the user, with primary and verification status.",
        },
    },
    "organizations": {
        "description": "An organization on the Sourcegraph instance, used to group users and share settings. Listing organizations requires a site-admin access token.",
        "docs_url": "https://sourcegraph.com/docs/api/graphql",
        "columns": {
            "id": "Unique identifier for the organization (opaque GraphQL ID).",
            "name": "The organization's unique name.",
            "displayName": "The organization's display name.",
            "createdAt": "When the organization was created.",
            "url": "The organization's URL path on the Sourcegraph instance.",
        },
    },
}
