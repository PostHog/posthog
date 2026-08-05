from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.settings import ENDPOINT_NAME

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    ENDPOINT_NAME: {
        "description": (
            "Engagement and frustration-signal metrics (traffic, scroll depth, engagement time, "
            "popular pages, dead/rage/quickback/error clicks, script errors) from the Microsoft "
            "Clarity Data Export API, aggregated over the requested reporting window and optionally "
            "broken down by up to three dimensions. Each sync appends a new snapshot rather than "
            "replacing prior data, since the API only ever returns the last 1-3 days."
        ),
        "docs_url": "https://learn.microsoft.com/en-us/clarity/setup-and-installation/clarity-data-export-api",
        "columns": {
            "metric_name": (
                "The Clarity metric this row belongs to (e.g. Traffic, ScrollDepth, EngagementTime, "
                "PopularPages, DeadClickCount, RageClickCount, QuickbackClick, ScriptErrorCount, "
                "ErrorClickCount)."
            ),
            "synced_at": (
                "UTC timestamp this row was pulled at. Used to distinguish daily snapshots, since the "
                "API has no historical cursor and only ever returns the trailing 1-3 day window."
            ),
            "num_of_days": "The reporting window requested: 1, 2, or 3 (last 24/48/72 hours).",
            "row_index": "Position of this row within its metric's result set for this sync.",
            "totalSessionCount": "Number of sessions counted for this metric/dimension combination.",
            "totalBotSessionCount": "Number of bot sessions counted for this metric/dimension combination.",
            "distantUserCount": "Number of distinct users counted for this metric/dimension combination.",
            "PagesPerSessionPercentage": "Average pages-per-session percentage for this metric/dimension combination.",
        },
    },
}
