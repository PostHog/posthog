from products.warehouse_sources.sources.sdk import frozen


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
    "membership_categories": TeamupFitnessEndpoint(path="membership_categories"),
    "offering_types": TeamupFitnessEndpoint(path="offering_types"),
    "lead_sources": TeamupFitnessEndpoint(path="crm/lead_sources"),
    "payment_subscriptions": TeamupFitnessEndpoint(path="payment_subscriptions"),
    "membership_payment_plans": TeamupFitnessEndpoint(path="membership_payment_plans"),
    "customer_membership_holds": TeamupFitnessEndpoint(path="customer_membership_holds"),
    "discount_codes": TeamupFitnessEndpoint(path="discount_codes"),
    "crm_status_changes": TeamupFitnessEndpoint(path="crm/status_changes", partition_key="created_at"),
}

AUTH_ERROR = "TeamUp rejected the M2M token. Create a new token in your TeamUp business dashboard."
PERMISSION_ERROR = (
    "TeamUp denied access. Check that your M2M token has access to the specified provider ID "
    "and has the permissions this table needs."
)
PROVIDER_ERROR = "TeamUp could not select your business. Enter the numeric provider ID for your TeamUp business."

NON_RETRYABLE_ERRORS: dict[str, str | None] = {
    "401 Client Error": AUTH_ERROR,
    "403 Client Error": PERMISSION_ERROR,
    "code=authentication_failed": AUTH_ERROR,
    "code=provider_header_missing": PROVIDER_ERROR,
    "code=provider_header_invalid": PROVIDER_ERROR,
}
