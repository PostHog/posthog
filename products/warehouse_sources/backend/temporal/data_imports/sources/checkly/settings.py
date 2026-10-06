from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://api.checklyhq.com"
API_VERSION = "v2"
PAGE_SIZE = 100
RESULT_HISTORY_SECONDS = 30 * 24 * 60 * 60
RESULT_FIELDS = (
    "id,name,checkId,created_at,startedAt,stoppedAt,hasFailures,hasErrors,isDegraded,"
    "isCancelled,overMaxResponseTime,runLocation,responseTime,checkRunId,attempts,resultType"
)


@frozen
class ChecklyEndpoint:
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    paginated: bool = True


ENDPOINTS = {
    "checks": ChecklyEndpoint(path="/{api_version}/checks"),
    "check_groups": ChecklyEndpoint(path="/v1/check-groups"),
    "alert_channels": ChecklyEndpoint(path="/v1/alert-channels"),
    "check_statuses": ChecklyEndpoint(path="/v1/check-statuses", primary_keys=("checkId",), paginated=False),
    "check_results": ChecklyEndpoint(path="/{api_version}/check-results/{checkId}", primary_keys=("checkId", "id")),
}
INCREMENTAL_FIELDS = {"check_results": [incremental_field("created_at")]}

AUTH_ERRORS = {
    401: "Checkly rejected your API key. Create a new key and reconnect.",
    403: "Your API key cannot read this Checkly account. Check the account ID and key permissions.",
}
