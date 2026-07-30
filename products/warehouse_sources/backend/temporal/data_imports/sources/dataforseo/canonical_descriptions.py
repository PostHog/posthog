from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "domain_rank_overview": {
        "description": "Current organic and paid search ranking distribution for each target domain, including estimated traffic and keyword position counts.",
        "docs_url": "https://docs.dataforseo.com/v3/dataforseo_labs/google/domain_rank_overview/live/",
        "columns": {
            "target": "The tracked domain this row belongs to, as configured on the source.",
            "se_type": "Search engine type the metrics were collected from (e.g. google).",
            "location_code": "DataForSEO location identifier the metrics are scoped to.",
            "language_code": "Language identifier the metrics are scoped to.",
            "metrics": "Ranking data grouped by result type (organic, paid), including position distribution buckets (pos_1, pos_2_3, ...), estimated traffic volume (etv), estimated paid traffic cost, and counts of new, up, down, and lost rankings.",
        },
    },
    "historical_rank_overview": {
        "description": "Monthly historical ranking and traffic metrics for each target domain, from October 2020 onward.",
        "docs_url": "https://docs.dataforseo.com/v3/dataforseo_labs/google/historical_rank_overview/live/",
        "columns": {
            "target": "The tracked domain this row belongs to, as configured on the source.",
            "year": "Calendar year of the measurement.",
            "month": "Calendar month of the measurement (1-12).",
            "date": "First day of the measurement month (derived from year and month).",
            "metrics": "Ranking data for the month grouped by result type (organic, paid), including position distribution buckets, estimated traffic volume (etv), and estimated paid traffic cost.",
        },
    },
    "ranked_keywords": {
        "description": "Keywords each target domain ranks for in Google search results, with keyword metrics and the ranked SERP element.",
        "docs_url": "https://docs.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live/",
        "columns": {
            "target": "The tracked domain this row belongs to, as configured on the source.",
            "keyword": "The search query the domain ranks for.",
            "item_type": "Type of the ranked SERP element (organic, paid, featured_snippet, local_pack, ai_overview_reference).",
            "rank_group": "Position within the group of equivalent SERP elements.",
            "rank_absolute": "Absolute position among all SERP elements for the keyword.",
            "ranked_url": "URL of the page that ranks for the keyword.",
            "se_type": "Search engine type the ranking was collected from.",
            "keyword_data": "Full keyword payload, including keyword_info with search volume, CPC, competition, and monthly search trends.",
            "ranked_serp_element": "Full SERP element payload describing how and where the page appears in the results.",
        },
    },
    "competitors_domain": {
        "description": "Competitor domains that rank for the same keywords as each target domain, with shared keyword counts and ranking metrics.",
        "docs_url": "https://docs.dataforseo.com/v3/dataforseo_labs/google/competitors_domain/live/",
        "columns": {
            "target": "The tracked domain this row belongs to, as configured on the source.",
            "domain": "The competitor domain.",
            "avg_position": "Average SERP position across the keywords shared with the target domain.",
            "sum_position": "Sum of SERP positions across shared keyword results.",
            "intersections": "Number of keywords the competitor shares with the target domain.",
            "full_domain_metrics": "Ranking metrics for the competitor across all of its keywords.",
            "metrics": "Ranking metrics for the competitor across only the keywords shared with the target domain.",
        },
    },
    "backlinks_summary": {
        "description": "Backlink profile summary for each target domain from the DataForSEO Backlinks API (requires a Backlinks API subscription).",
        "docs_url": "https://docs.dataforseo.com/v3/backlinks/summary/live/",
        "columns": {
            "target": "The tracked domain this row belongs to, as configured on the source.",
            "rank": "DataForSEO domain rank on a 0-1000 scale.",
            "backlinks": "Total number of backlinks pointing at the target.",
            "backlinks_spam_score": "Average spam score of the backlinks pointing at the target.",
            "referring_domains": "Number of unique domains linking to the target.",
            "referring_main_domains": "Number of unique main (root) domains linking to the target.",
            "referring_pages": "Number of unique pages linking to the target.",
            "referring_ips": "Number of unique IP addresses hosting linking pages.",
            "referring_subnets": "Number of unique subnets hosting linking pages.",
            "broken_backlinks": "Number of backlinks pointing at unreachable pages on the target.",
            "broken_pages": "Number of target pages that return an error and still receive backlinks.",
        },
    },
}
