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
    "total_plays": {
        "description": "Engagement totals across every flow in the team during the requested period.",
        "docs_url": INSIGHTS_DOCS_URL,
        "columns": {
            "team_id": "Arcade team identifier supplied with the request.",
            "period_start": "Start of the requested engagement period, added by the connector.",
            "period_end": "End of the requested engagement period, added by the connector.",
            "players": "Unique viewers across all flows.",
            "plays": "Unique play sessions.",
            "completers": "Unique viewers who completed a flow.",
            "completions": "Sessions that completed a flow.",
            "anyCtaClickers": "Unique viewers who clicked any call to action.",
            "anyCtaClicks": "Clicks on any call to action.",
            "finalCtaClickers": "Unique viewers who clicked the final call to action.",
            "finalCtaClicks": "Clicks on the final call to action.",
        },
    },
    "flow_views": {
        "description": "Unique viewers of each flow during the requested period.",
        "docs_url": INSIGHTS_DOCS_URL,
        "columns": {
            "flowId": "Flow identifier, added by the connector.",
            "team_id": "Arcade team identifier supplied with the request.",
            "period_start": "Start of the requested engagement period, added by the connector.",
            "period_end": "End of the requested engagement period, added by the connector.",
            "viewers": "Unique viewers of the flow.",
        },
    },
    "flow_dropoff": {
        "description": "Step dropoff for each flow during the requested period.",
        "docs_url": INSIGHTS_DOCS_URL,
        "columns": {
            "flowId": "Flow identifier, added by the connector.",
            "stepId": "Step identifier.",
            "team_id": "Arcade team identifier supplied with the request.",
            "period_start": "Start of the requested engagement period, added by the connector.",
            "period_end": "End of the requested engagement period, added by the connector.",
            "reached": "Viewers who reached the step.",
            "droppedOff": "Viewers who left the flow at the step.",
            "transitions": "Viewer counts for each next step, keyed by step identifier.",
        },
    },
    "authenticated_views": {
        "description": "Identified viewers of each flow during the requested period, with completion status.",
        "docs_url": INSIGHTS_DOCS_URL,
        "columns": {
            "flowId": "Flow identifier, added by the connector.",
            "team_id": "Arcade team identifier supplied with the request.",
            "period_start": "Start of the requested engagement period, added by the connector.",
            "period_end": "End of the requested engagement period, added by the connector.",
            "email": "Viewer email address.",
            "userName": "Viewer name.",
            "userPhotoURL": "URL of the viewer photo.",
            "companyName": "Viewer company name.",
            "companyLogo": "URL of the viewer company logo.",
            "lastViewedDate": "Time the viewer last viewed the flow.",
            "completed": "Whether the viewer completed the flow.",
        },
    },
}
