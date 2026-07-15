from dataclasses import dataclass, field


@dataclass
class SageHREndpointConfig:
    name: str
    path: str
    # Most collection endpoints paginate with a `page` query param and a `meta` block; a couple
    # (policies, document categories) return everything in a single unpaginated response.
    paginated: bool = True
    # Time off requests only return the current month unless an explicit `from`/`to` window is
    # passed, and the window is capped at 65 days — so a full sync must walk date windows.
    requires_date_window: bool = False
    # Sage HR resource identifiers are account-unique integers, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Sage HR API collection endpoints (https://sagehr.docs.apiary.io). All are full-refresh only:
# no endpoint exposes an updated-since style server-side timestamp filter, so there is no cursor
# to advance an incremental sync. The only date filter (`from`/`to` on time off requests) selects
# by leave date range, not modification time, and is capped at 65 days per request.
SAGE_HR_ENDPOINTS: dict[str, SageHREndpointConfig] = {
    "employees": SageHREndpointConfig(name="employees", path="/employees"),
    "terminated_employees": SageHREndpointConfig(name="terminated_employees", path="/terminated-employees"),
    "termination_reasons": SageHREndpointConfig(name="termination_reasons", path="/termination-reasons"),
    "teams": SageHREndpointConfig(name="teams", path="/teams"),
    "positions": SageHREndpointConfig(name="positions", path="/positions"),
    "documents": SageHREndpointConfig(name="documents", path="/documents"),
    "document_categories": SageHREndpointConfig(
        name="document_categories", path="/documents/categories", paginated=False
    ),
    "leave_requests": SageHREndpointConfig(
        name="leave_requests", path="/leave-management/requests", requires_date_window=True
    ),
    "leave_policies": SageHREndpointConfig(name="leave_policies", path="/leave-management/policies", paginated=False),
    "individual_allowances": SageHREndpointConfig(
        name="individual_allowances", path="/leave-management/reports/individual-allowances"
    ),
    "onboarding_categories": SageHREndpointConfig(name="onboarding_categories", path="/onboarding/categories"),
    "offboarding_categories": SageHREndpointConfig(name="offboarding_categories", path="/offboarding/categories"),
}

ENDPOINTS = tuple(SAGE_HR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
