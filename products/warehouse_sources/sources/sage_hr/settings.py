from dataclasses import dataclass, field


@dataclass(frozen=True)
class SageHRFanOut:
    # Paginated parent collection whose rows' `id` fills the `{id}` placeholder of the child path.
    parent_path: str
    # Column added to every child row so rows from different parents stay distinct.
    parent_key: str


@dataclass(frozen=True)
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
    fan_out: SageHRFanOut | None = None
    # Compensation rows carry no identifier, so the source derives `id` from the row content.
    derive_row_id: bool = False


_PER_EMPLOYEE = SageHRFanOut(parent_path="/employees", parent_key="employee_id")
_PER_RECRUITMENT_POSITION = SageHRFanOut(parent_path="/recruitment/positions", parent_key="position_id")


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
    "compensations": SageHREndpointConfig(
        name="compensations",
        path="/employees/{id}/compensations",
        primary_keys=["employee_id", "id"],
        fan_out=_PER_EMPLOYEE,
        derive_row_id=True,
    ),
    "leave_balances": SageHREndpointConfig(
        name="leave_balances",
        path="/employees/{id}/leave-management/balances",
        paginated=False,
        primary_keys=["employee_id", "policy_id"],
        fan_out=_PER_EMPLOYEE,
    ),
    # The docs don't say whether applicant ids are unique across positions, so key on both.
    "recruitment_applicants": SageHREndpointConfig(
        name="recruitment_applicants",
        path="/recruitment/positions/{id}/applicants",
        primary_keys=["position_id", "id"],
        fan_out=_PER_RECRUITMENT_POSITION,
    ),
}

ENDPOINTS = tuple(SAGE_HR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
