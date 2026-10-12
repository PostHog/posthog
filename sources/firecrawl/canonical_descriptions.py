from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the public Firecrawl v2 API reference (https://docs.firecrawl.dev/api-reference).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "team_activity": {
        "description": "Your team's job activity from the past 24 hours - one row per API job (scrape, crawl, search, etc.).",
        "docs_url": "https://docs.firecrawl.dev/api-reference/endpoint/activity",
        "columns": {
            "id": "The job ID, used to fetch the full result from the matching retrieval endpoint.",
            "endpoint": "The endpoint used for the job (scrape, crawl, batch_scrape, search, extract, map, agent, ...).",
            "api_version": "The API version used for the request.",
            "created_at": "When the job was created.",
            "target": "The URL or query that was submitted.",
        },
    },
    "credit_usage_historical": {
        "description": "Credits used per billing period, month by month.",
        "docs_url": "https://docs.firecrawl.dev/api-reference/endpoint/credit-usage-historical",
        "columns": {
            "startDate": "Start date of the billing period.",
            "endDate": "End date of the billing period.",
            "apiKey": "The API key the usage is attributed to, or null for the team total (the default).",
            "totalCredits": "Total number of credits used in the billing period.",
        },
    },
    "token_usage_historical": {
        "description": "Tokens used per billing period, month by month.",
        "docs_url": "https://docs.firecrawl.dev/api-reference/endpoint/token-usage-historical",
        "columns": {
            "startDate": "Start date of the billing period.",
            "endDate": "End date of the billing period.",
            "apiKey": "The API key the usage is attributed to, or null for the team total (the default).",
            "totalTokens": "Total number of tokens used in the billing period.",
        },
    },
    "active_crawls": {
        "description": "Crawls that are currently in progress for your team.",
        "docs_url": "https://docs.firecrawl.dev/api-reference/endpoint/crawl-active",
        "columns": {
            "id": "The unique identifier of the crawl.",
            "teamId": "The ID of the team that owns the crawl.",
            "url": "The origin URL of the crawl.",
            "options": "The crawler options used for this crawl.",
        },
    },
    "monitors": {
        "description": "Change-detection monitors that periodically re-scrape targets and report what changed.",
        "docs_url": "https://docs.firecrawl.dev/api-reference/endpoint/monitor-list",
        "columns": {
            "id": "The unique identifier of the monitor.",
            "name": "The monitor's name.",
            "status": "Monitor status (active, paused, deleted).",
            "schedule": "The monitor's run schedule (cron expression and timezone).",
            "nextRunAt": "When the monitor is next scheduled to run.",
            "lastRunAt": "When the monitor last ran.",
            "targets": "The scrape, crawl, or search targets the monitor watches.",
            "retentionDays": "How many days of checks are retained.",
            "estimatedCreditsPerMonth": "Upper-bound monthly credit estimate for the monitor.",
            "createdAt": "When the monitor was created.",
            "updatedAt": "When the monitor was last updated.",
        },
    },
    "monitor_checks": {
        "description": "Individual change-detection runs for a monitor, including credit cost and a page-change summary.",
        "docs_url": "https://docs.firecrawl.dev/api-reference/endpoint/monitor-checks-list",
        "columns": {
            "id": "The unique identifier of the check.",
            "monitorId": "The monitor this check belongs to.",
            "status": "Check status (queued, running, completed, failed, partial, skipped_overlap).",
            "trigger": "What triggered the check (scheduled or manual).",
            "startedAt": "When the check started.",
            "finishedAt": "When the check finished.",
            "actualCredits": "Credits actually consumed by the check.",
            "summary": "Page-change summary (totalPages, same, changed, new, removed, error).",
            "createdAt": "When the check was created.",
            "updatedAt": "When the check was last updated.",
        },
    },
}
