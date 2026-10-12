from posthog.dataclasses import frozen

BASE_URL = "https://api.arcade.software"
API_DOCS_URL = "https://docs.arcade.software/kb/leverage/advanced-features/rest-api"
INSIGHTS_DOCS_URL = f"{API_DOCS_URL}/insights-api"
PAGE_SIZE = 100

AUTH_ERROR = "Arcade rejected your API key. Create a new key in Settings > Advanced."
PLAN_ERROR = "Arcade API access requires an Enterprise workspace. Check your plan with Arcade."
PROVISIONING_ERROR = "Enable User provisioning on your Arcade API key to sync teams and users."
INSIGHTS_ERROR = "Enable insights access on your Arcade API key to sync engagement data."
PERMISSION_ERROR = "Arcade denied access. Check your API key permissions and Enterprise plan."


@frozen
class ArcadeEndpoint:
    path: str
    selector: str
    primary_keys: tuple[str, ...]
    insight_type: str | None = None


ENDPOINTS = {
    "teams": ArcadeEndpoint(path="teams", selector="teams", primary_keys=("id",)),
    "users": ArcadeEndpoint(path="users", selector="users", primary_keys=("id",)),
    "flow_engagement": ArcadeEndpoint(
        path="insights", selector="$", primary_keys=("team_id", "flowId"), insight_type="overviewPlays"
    ),
    "company_leads": ArcadeEndpoint(
        path="insights", selector="$", primary_keys=("team_id", "id"), insight_type="companiesForLeads"
    ),
}
