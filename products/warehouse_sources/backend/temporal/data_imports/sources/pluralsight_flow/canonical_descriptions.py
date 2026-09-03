"""Canonical, documentation-sourced descriptions for Pluralsight Flow endpoints and columns.

Sourced from the official Flow Customer API and Metrics API reference
(https://appfire.atlassian.net/wiki/spaces/FD/pages/1802076213/Flow+REST+API+introduction).
Keyed by the resource names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Flow table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Users": {
        "description": "A person tracked by Flow, aggregated from one or more git/ticket-host identities.",
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802404091",
        "columns": {
            "id": "User's unique identifier.",
            "name": "User's display name.",
            "email": "User's email address.",
            "hidden_from_reports": "Whether the user is excluded from Flow reports.",
            "org_id": "Identifier of the organization the user belongs to.",
            "has_login": "Whether the user has a Flow login (as opposed to a data-only identity).",
            "created_at": "Time the user record was created in Flow.",
            "last_activity_at": "Time of the user's most recent tracked activity.",
            "first_activity_at": "Time of the user's earliest tracked activity.",
        },
    },
    "Teams": {
        "description": "A group of Flow users, optionally nested under a parent team.",
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802011038",
        "columns": {
            "id": "Team's unique identifier.",
            "name": "Team name.",
            "description": "Team description.",
            "vendor": "Name of the vendor/integration the team originates from, if any.",
            "parent": "Identifier of the parent team, if this team is nested.",
            "is_visible": "Whether the team is shown in report menus.",
            "created_at": "Time the team was created.",
        },
    },
    "Commits": {
        "description": (
            "A raw git commit synced from an integrated repository. Does not exactly match the "
            "aggregated and filtered commit data shown in Flow reports."
        ),
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802568104",
        "columns": {
            "id": "Commit's unique identifier.",
            "hexsha": "Unique commit hash (SHA).",
            "user_alias_id": "Identifier of the git identity that authored the commit.",
            "apex_user_id": "Identifier of the Flow user the commit is attributed to.",
            "repo_id": "Identifier of the repository the commit belongs to.",
            "is_merge": "Whether the commit is a merge commit.",
            "is_pr_orphan": "Whether the commit isn't associated with any pull request.",
            "is_outlier": "Whether Flow flags the commit as a statistical outlier.",
            "author_date": "Date and time the commit was authored (recommended for time filtering).",
            "committer_date": "Date and time the commit was committed.",
        },
    },
    "PullRequests": {
        "description": "An author's request to merge a set of commits into a repository branch.",
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802011014",
        "columns": {
            "id": "Pull request's unique identifier.",
            "title": "Pull request title.",
            "number": "Pull request number in its repository.",
            "state": "Current state of the pull request.",
            "vendor": "Name of the git host the pull request originates from.",
            "url": "URL of the pull request.",
            "project_id": "Identifier of the associated repository/project.",
            "created_at": "Time the pull request was created.",
            "closed_at": "Time the pull request was closed.",
            "pr_start": "Time the pull request was opened.",
            "pr_end": "Time the pull request was merged or closed.",
            "first_comment_at": "Time of the first comment on the pull request.",
            "comment_count": "Number of comments on the pull request.",
            "reviewer_count": "Number of reviewers on the pull request.",
            "additions": "Number of lines added.",
            "deletions": "Number of lines deleted.",
        },
    },
    "Repos": {
        "description": "A git repository imported into Flow from an integrated vendor.",
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802600473",
        "columns": {
            "id": "Repository's unique identifier.",
            "name": "Repository name.",
            "vendor": "Name of the git host the repository is imported from (e.g. github).",
        },
    },
    "Tickets": {
        "description": "An issue filed in an integrated issue-tracking application.",
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1801912714",
        "columns": {
            "id": "Ticket's unique identifier.",
            "title": "Ticket title.",
            "number": "Ticket number in its issue tracker.",
            "state": "Current state of the ticket (e.g. Defined, InProgress, Completed).",
            "vendor": "Name of the issue-tracking application the ticket originates from.",
            "url": "URL of the ticket.",
            "closed_at": "Time the ticket was closed.",
            "created_at": "Time the ticket was created.",
            "updated_at": "Time the ticket was last modified.",
            "type": "Ticket type.",
            "comment_count": "Number of comments on the ticket.",
        },
    },
    "CodingMetrics": {
        "description": (
            "Aggregate coding activity metrics (coding days, commits per day, impact, efficiency) "
            "for the requested date range. One row per sync, covering the trailing window."
        ),
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/2208239236",
        "columns": {
            "date_range": "The `[start:end]` date window the metrics were computed over.",
        },
    },
    "CollaborationMetrics": {
        "description": (
            "Aggregate pull request collaboration metrics (time to merge, time to first comment, "
            "review thoroughness, PR count) for the requested date range. One row per sync."
        ),
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802076189",
        "columns": {
            "date_range": "The `[start:end]` date window the metrics were computed over.",
        },
    },
}
