from posthog.dataclasses import frozen


@frozen
class TeamupFitnessEndpoint:
    path: str
    primary_key: str = "id"
    sort: str | None = None
    partition_key: str | None = None


# Schedule and membership start dates do not track later changes to these records.
ENDPOINTS: dict[str, TeamupFitnessEndpoint] = {
    "customers": TeamupFitnessEndpoint(path="customers", partition_key="created_at"),
    "customer_memberships": TeamupFitnessEndpoint(path="customer_memberships", sort="start_date"),
    "memberships": TeamupFitnessEndpoint(path="memberships"),
    "events": TeamupFitnessEndpoint(path="events", sort="start"),
    "attendances": TeamupFitnessEndpoint(path="attendances", sort="event_starts_at"),
    "invoices": TeamupFitnessEndpoint(path="invoices", sort="due_date", partition_key="created_at"),
    "venues": TeamupFitnessEndpoint(path="venues"),
    "instructors": TeamupFitnessEndpoint(path="instructors"),
}

AUTH_ERROR = "TeamUp rejected the M2M token. Create a new token in your TeamUp business dashboard."
PERMISSION_ERROR = "TeamUp denied access. Check that your M2M token has access to the specified provider ID."
PROVIDER_ERROR = "TeamUp could not select your business. Enter the numeric provider ID for your TeamUp business."

NON_RETRYABLE_ERRORS: dict[str, str | None] = {
    "401 Client Error": AUTH_ERROR,
    "403 Client Error": PERMISSION_ERROR,
    "code=authentication_failed": AUTH_ERROR,
    "code=provider_header_missing": PROVIDER_ERROR,
    "code=provider_header_invalid": PROVIDER_ERROR,
}
