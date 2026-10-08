from products.warehouse_sources.backend.temporal.data_imports.sources.arcade.settings import (
    API_DOCS_URL,
    INSIGHTS_DOCS_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "teams": {
        "description": "Active teams and their active members in the Arcade workspace.",
        "docs_url": API_DOCS_URL,
        "columns": {"id": "Team identifier.", "slug": "Team slug.", "members": "Active team members."},
    },
    "users": {
        "description": "Active users in the Arcade workspace.",
        "docs_url": API_DOCS_URL,
        "columns": {"id": "User identifier.", "email": "User email address.", "role": "Workspace role."},
    },
    "flow_engagement": {
        "description": "Engagement totals for each flow during the requested period.",
        "docs_url": INSIGHTS_DOCS_URL,
        "columns": {
            "flowId": "Flow identifier.",
            "flowName": "Flow name.",
            "team_id": "Arcade team identifier supplied with the request.",
            "period_start": "Start of the requested engagement period, added by the connector.",
            "period_end": "End of the requested engagement period, added by the connector.",
            "players": "Unique viewers.",
            "plays": "Unique play sessions.",
            "completers": "Unique viewers who completed the flow.",
            "completions": "Sessions that completed the flow.",
            "anyCtaClicks": "Clicks on any call to action.",
            "finalCtaClicks": "Clicks on the final call to action.",
        },
    },
    "company_leads": {
        "description": "Companies that played flows, with company details and engagement metrics.",
        "docs_url": INSIGHTS_DOCS_URL,
        "columns": {
            "id": "Company identifier.",
            "team_id": "Arcade team identifier supplied with the request.",
            "domain": "Company domain.",
            "industry": "Company industry.",
            "employeeRange": "Employee count range.",
            "flows": "Flows played by viewers from this company.",
        },
    },
}
