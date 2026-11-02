from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://help.swarmia.com/settings/integrations/swarmia-apis/export-api"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "pull_requests": {
        "description": "Per-team pull request metrics aggregated over complete ISO weeks (Monday to Sunday).",
        "docs_url": _DOCS_URL,
        "columns": {
            "start_date": "First day of the reporting window (inclusive).",
            "end_date": "Last day of the reporting window (inclusive).",
            "parent_teams": "Parent team(s) of the team, when the organization uses a team hierarchy.",
            "team": "Name of the team the metrics are aggregated for.",
            "cycle_time_seconds": "Average time from first commit to deployed change, in seconds.",
            "review_rate_percent": "Share of merged pull requests that were reviewed, as a percentage.",
            "time_to_first_review_seconds": "Average time from review request to first review, in seconds.",
            "prs_merged_per_week": "Average number of pull requests merged per week in the window.",
            "merge_time_seconds": "Average time from pull request creation to merge, in seconds.",
            "prs_in_progress": "Number of pull requests in progress during the window.",
            "contributors": "Number of contributors active in the window.",
        },
    },
    "dora": {
        "description": "Organization-level DORA metrics aggregated over complete ISO weeks (Monday to Sunday).",
        "docs_url": _DOCS_URL,
        "columns": {
            "start_date": "First day of the reporting window (inclusive).",
            "end_date": "Last day of the reporting window (inclusive).",
            "deployment_frequency_per_day": "Average number of deployments per day in the window.",
            "change_lead_time_minutes": "Average time from first commit to production deployment, in minutes.",
            "average_time_to_deploy_minutes": "Average time from merge to production deployment, in minutes.",
            "change_failure_rate_percent": "Share of deployments causing a failure in production, as a percentage.",
            "mean_time_to_recovery_minutes": "Average time to recover from a production failure, in minutes.",
            "deployment_count": "Total number of deployments in the window.",
        },
    },
    "investment": {
        "description": "Investment balance statistics per investment category, aggregated over complete calendar months using Swarmia's Effort model (monthly FTE). Data for a month is generated around the 10th day of the following month.",
        "docs_url": _DOCS_URL,
        "columns": {
            "start_date": "First day of the reporting month (inclusive).",
            "end_date": "Last day of the reporting month (inclusive).",
            "investment_category": "Investment category the effort is attributed to.",
            "fte_months": "Full-time-equivalent months of effort attributed to the category.",
            "relative_percentage": "Share of the organization's total effort attributed to the category, as a percentage.",
            "commits": "Number of commits attributed to the category.",
            "pull_request_comments": "Number of pull request comments attributed to the category.",
            "pull_request_creations": "Number of pull requests created, attributed to the category.",
            "pull_request_merges": "Number of pull requests merged, attributed to the category.",
            "pull_request_reviews": "Number of pull request reviews attributed to the category.",
        },
    },
    "capex": {
        "description": "Software capitalization report: one row per employee per capitalizable issue per calendar month.",
        "docs_url": _DOCS_URL,
        "columns": {
            "month": "The reporting month.",
            "employee_id": "Employee identifier from Swarmia.",
            "name": "Employee name.",
            "email": "Employee email address.",
            "capitalizable_work": "Title of the issue the capitalizable work is attributed to.",
            "developer_months": "Developer months of effort attributed to the issue in the month.",
            "additional_context": "Value of the additional context field configured in Swarmia (Jira only).",
        },
    },
    "capex_employees": {
        "description": "Total full-time-equivalents per employee per month for software capitalization, unpivoted from Swarmia's one-column-per-month CSV into one row per employee per month.",
        "docs_url": _DOCS_URL,
        "columns": {
            "employee_id": "Employee identifier from Swarmia.",
            "name": "Employee name.",
            "email": "Employee email address.",
            "month": "The reporting month (first day of the month).",
            "fte": "Total full-time-equivalents for the employee in the month.",
        },
    },
    "fte": {
        "description": "Effort report: full-time-equivalent effort per author per issue per calendar month, grouped by the highest-level issue (subtask effort rolls up to its Epic or Story).",
        "docs_url": _DOCS_URL,
        "columns": {
            "month": "The reporting month.",
            "author_id": "Author identifier from Swarmia.",
            "email": "Author email address.",
            "fte": "Full-time-equivalent effort the author spent on the issue in the month.",
            "custom_field": "Value of the configured custom field, inherited from the nearest parent issue when missing.",
            "swarmia_issue_type": "Swarmia's issue type classification for the issue.",
            "issue_key": "Key of the issue the effort is attributed to.",
        },
    },
}
