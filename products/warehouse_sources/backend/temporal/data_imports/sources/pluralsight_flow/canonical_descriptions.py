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
    "UserAliases": {
        "description": (
            "One identity (email address or user ID) under which a person shows up in an integrated "
            "vendor such as GitHub or Jira. Many aliases can merge into one apex user."
        ),
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802305876",
        "columns": {
            "id": "User alias's unique identifier.",
            "username": "User alias username.",
            "name": "User alias name.",
            "email": "User alias email address.",
            "integration": "Integration the user alias is associated with.",
            "vendor_type": "Vendor the user alias comes from (e.g. github).",
            "apex_user": "Flow user that this alias is merged into.",
            "created_at": "Date and time the user alias was created.",
            "first_activity_at": "Time of the user alias's earliest tracked activity.",
            "last_activity_at": "Time of the user alias's most recent tracked activity.",
        },
    },
    "TeamMemberships": {
        "description": "A relationship between a Flow user and a team.",
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802371338",
        "columns": {
            "id": "Unique identifier for the team membership.",
            "membership_type": "Membership type (e.g. contributor).",
            "apex_user": "Flow user that is a member of the team.",
            "apex_user_id": "Unique identifier of the Flow user that is a member of the team.",
            "team": "Team that the user is a member of.",
        },
    },
    "PullRequestProjects": {
        "description": (
            "An entity that receives pull requests. Every pull request belongs to one pull request "
            "project, and a pull request project is usually bound to a repository."
        ),
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802535281",
        "columns": {
            "id": "Unique identifier for the pull request project.",
            "name": "Pull request project name.",
            "url": "URL for the pull request project.",
            "vendor_type": "Vendor type.",
            "repo_id": "Unique identifier for the repository the project is bound to.",
            "added_by_id": "Unique identifier for the person who added the pull request project.",
            "created_at": "Date and time the pull request project was created.",
            "updated_at": "Date and time the pull request project was updated.",
            "integration": "Name of the integration used to import the project.",
            "last_processing_success_at": "Date and time of the last successful processing.",
            "processing_status": "Processing status.",
        },
    },
    "TicketProjects": {
        "description": (
            "A project in an integrated issue-tracking application that contains tickets. Every ticket "
            "belongs to one ticket project."
        ),
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802535305",
        "columns": {
            "id": "Unique identifier for the ticket project.",
            "name": "Name of the ticket project.",
            "url": "URL for the ticket project.",
            "vendor_type": "Vendor type.",
            "repo_id": "Unique identifier for a repository.",
            "added_by": "Unique identifier for the user that added the ticket project.",
            "created_at": "Date and time the ticket project was created.",
            "updated_at": "Date and time the ticket project was updated.",
            "integration": "Unique identifier for the integration.",
            "last_processing_success_at": "Date and time the project was last successfully updated.",
            "processing_status": "Status of the project.",
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
    "PullRequestComments": {
        "description": "A comment a user made on a pull request.",
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802502374",
        "columns": {
            "id": "Unique identifier for the pull request comment.",
            "user_alias_id": "Identifier of the user alias that wrote the comment.",
            "apex_user_id": "Identifier of the main user record for the comment author's aliases.",
            "pull_request_id": "Identifier of the pull request the comment belongs to.",
            "body": "Pull request comment body.",
            "word_count": "Total number of words in the comment.",
            "comment_robustness": "How robust the comment is: robust, regular, or trivial.",
            "is_extension_comment": "Whether the comment is a follow-on comment (a second consecutive comment by the same author).",
            "parent_id": "Identifier of the parent pull request comment.",
            "reaction_time": "Time in seconds it took to respond to the comment.",
            "created_at": "Date and time the comment was created.",
            "updated_at": "Date and time the comment was updated.",
            "is_reply": "Whether the comment was made in reply to another comment.",
            "was_influential": "Whether the comment resulted in the submitter adding a follow-on commit.",
            "comment_type": "Type of comment.",
        },
    },
    "TicketEvents": {
        "description": "A state change in a ticket's lifecycle in the issue-tracking system.",
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802568132",
        "columns": {
            "id": "Unique identifier for the ticket event.",
            "user_alias_id": "Identifier of the user alias associated with the ticket event.",
            "created_at": "Date and time the ticket event was created.",
            "params": "Parameters for the ticket event.",
            "ticket_id": "Identifier of the ticket.",
            "to_state": "State the ticket moved to: N/A, Defined, In-Progress, Completed, or Accepted.",
            "vendor": "Name of the issue-tracking system.",
        },
    },
    "TicketMetrics": {
        "description": (
            "Aggregate ticket delivery metrics (tickets completed, velocity, cycle time, queue time, "
            "backflow rate, jitter) for tickets moved to Done in the requested date range. One row per sync."
        ),
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802141797",
        "columns": {
            "date_range": "The date window the metrics were computed over.",
            "tickets_completed": "Number of tickets completed in the date range.",
            "total_jitter": "Total jitter in the ticket completion times.",
            "backflow_rate": "Rate of tickets that were reopened after completion.",
            "median_cycle_time": "Median time taken to complete a ticket.",
            "tickets_queue_time": "Total time tickets spent in the queue.",
            "velocity": "Rate at which tickets are completed.",
            "active_time": "Total time tickets spent actively being worked on.",
        },
    },
    "DoraLeadTime": {
        "description": "DORA lead time for changes (median, trend, performance) for the requested date range. One row per sync.",
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802338351",
        "columns": {
            "date_range": "The date window the metric was computed over.",
            "median": "Median lead time for changes.",
            "trend": "Change in the metric compared to the previous period.",
            "performance": "DORA performance level for the metric.",
            "timeseries": "The metric broken down by time period.",
        },
    },
    "DoraDeploymentFrequency": {
        "description": "DORA deployment frequency (total, weekly median, trend, performance) for the requested date range. One row per sync.",
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802338351",
        "columns": {
            "date_range": "The date window the metric was computed over.",
            "weekly_median": "Median number of deployments per week.",
            "total": "Total number of deployments.",
            "trend": "Change in the metric compared to the previous period.",
            "frequency": "Deployment frequency bucket, e.g. daily.",
            "performance": "DORA performance level for the metric.",
            "timeseries": "Deployment counts broken down by time period.",
        },
    },
    "DoraChangeFailureRate": {
        "description": "DORA change failure rate with its related trends, deployments and incidents for the requested date range. One row per sync.",
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802338351",
        "columns": {
            "date_range": "The date window the metric was computed over.",
            "overall_failure_rate": "Change failure rate over the whole date range.",
            "timeseries": "Failure rate, deployments and failures broken down by time period.",
            "incidents": "Incidents counted as failures in the date range.",
        },
    },
    "DoraTimeToRestore": {
        "description": "DORA time to restore service with its related trends and incidents for the requested date range. One row per sync.",
        "docs_url": "https://appfire.atlassian.net/wiki/spaces/FD/pages/1802338351",
        "columns": {
            "date_range": "The date window the metric was computed over.",
            "time_to_restore": "Time to restore service in the date range.",
            "trend": "Change in the metric compared to the previous period.",
            "performance": "DORA performance level for the metric.",
            "timeseries": "Incident counts and recovery time broken down by time period.",
            "incidents": "Incidents resolved in the date range, with their time to restore.",
        },
    },
}
