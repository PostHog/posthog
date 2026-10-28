from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class GustoEndpointConfig:
    name: str
    # Path under the API host. `{company_uuid}` / `{employee_uuid}` are filled in per parent row.
    path: str
    primary_keys: list[str]
    # Most company-scoped collections paginate with `page`/`per`; the derived `companies` table, a
    # few small company lists, and the per-employee child lists come back whole in a single response.
    paginated: bool = True
    # Money-movement endpoints take a `start_date`/`end_date` check-date window instead of being
    # walked in full. The value is the row field the window filters on, which is also the only
    # incremental cursor Gusto offers.
    date_window_field: str | None = None
    # Fan-out endpoints are fetched once per row of this parent endpoint (see FAN_OUT_PARENT_KEYS)
    # in each company.
    fan_out_parent: str | None = None
    # Static query parameters sent on every page of a paginated endpoint.
    extra_params: dict[str, str] | None = None
    # Rows nested under this key in the response body (None = the body is the array itself).
    data_key: str | None = None


# Fan-out parent endpoint -> the path placeholder its uuid fills. The child rows carry the parent
# uuid as the same name with a leading `_`.
FAN_OUT_PARENT_KEYS: dict[str, str] = {
    "employees": "employee_uuid",
    "company_benefits": "company_benefit_uuid",
}


# Gusto REST API (https://docs.gusto.com/embedded-payroll/reference). Every data endpoint is
# company-scoped, so each stream fans out over the companies the access token can reach
# (`GET /v1/me`). Only the money-movement endpoints accept a server-side date filter — the people
# and configuration tables have no updated-since parameter, so they are full refresh.
GUSTO_ENDPOINTS: dict[str, GustoEndpointConfig] = {
    "companies": GustoEndpointConfig(
        name="companies",
        path="/v1/companies/{company_uuid}",
        primary_keys=["uuid"],
        paginated=False,
    ),
    "locations": GustoEndpointConfig(
        name="locations",
        path="/v1/companies/{company_uuid}/locations",
        primary_keys=["uuid"],
    ),
    "employees": GustoEndpointConfig(
        name="employees",
        path="/v1/companies/{company_uuid}/employees",
        primary_keys=["uuid"],
    ),
    "jobs": GustoEndpointConfig(
        name="jobs",
        path="/v1/employees/{employee_uuid}/jobs",
        # Job uuids are not documented as globally unique, so the parent employee is part of the key.
        primary_keys=["_employee_uuid", "uuid"],
        paginated=False,
        fan_out_parent="employees",
    ),
    "contractors": GustoEndpointConfig(
        name="contractors",
        path="/v1/companies/{company_uuid}/contractors",
        primary_keys=["uuid"],
    ),
    "pay_schedules": GustoEndpointConfig(
        name="pay_schedules",
        path="/v1/companies/{company_uuid}/pay_schedules",
        primary_keys=["uuid"],
    ),
    "payrolls": GustoEndpointConfig(
        name="payrolls",
        path="/v1/companies/{company_uuid}/payrolls",
        primary_keys=["_company_uuid", "payroll_uuid"],
        date_window_field="check_date",
    ),
    "pay_periods": GustoEndpointConfig(
        name="pay_periods",
        path="/v1/companies/{company_uuid}/pay_periods",
        # Pay periods carry no identifier of their own — the schedule plus the period bounds are
        # what makes a row unique within a company.
        primary_keys=["_company_uuid", "pay_schedule_uuid", "start_date", "end_date"],
        paginated=False,
        date_window_field="end_date",
    ),
    "contractor_payments": GustoEndpointConfig(
        name="contractor_payments",
        path="/v1/companies/{company_uuid}/contractor_payments",
        primary_keys=["_company_uuid", "uuid"],
        paginated=False,
        date_window_field="date",
        # The body groups payments per contractor: {"total": {...}, "contractor_payments": [
        # {"contractor_uuid": ..., "payments": [...]}]}.
        data_key="contractor_payments",
    ),
    # The date filters here (due date, period, sent-on) don't track `amount_paid` and
    # `payment_sent_on` changing after a payment is scheduled, so a date watermark would leave
    # earlier unpaid payments stale. Full refresh keeps payment status current.
    "tax_payments": GustoEndpointConfig(
        name="tax_payments",
        path="/v1/companies/{company_uuid}/tax_payments",
        primary_keys=["uuid"],
    ),
    "departments": GustoEndpointConfig(
        name="departments",
        path="/v1/companies/{company_uuid}/departments",
        primary_keys=["uuid"],
        paginated=False,
    ),
    "company_benefits": GustoEndpointConfig(
        name="company_benefits",
        path="/v1/companies/{company_uuid}/company_benefits",
        primary_keys=["uuid"],
        paginated=False,
    ),
    # ACH transactions take no date filter, and `payment_status` / `error_code` change after a
    # transaction is created, so full refresh keeps failures and settlements current.
    "ach_transactions": GustoEndpointConfig(
        name="ach_transactions",
        path="/v1/companies/{company_uuid}/ach_transactions",
        primary_keys=["uuid"],
    ),
    "recurring_reimbursements": GustoEndpointConfig(
        name="recurring_reimbursements",
        path="/v1/employees/{employee_uuid}/recurring_reimbursements",
        primary_keys=["_employee_uuid", "uuid"],
        paginated=False,
        fan_out_parent="employees",
    ),
    "earning_types": GustoEndpointConfig(
        name="earning_types",
        path="/v1/companies/{company_uuid}/earning_types",
        # Default earning types are mostly the same for every company, and Gusto doesn't document
        # earning type uuids as unique across companies.
        primary_keys=["_company_uuid", "uuid"],
        paginated=False,
    ),
    "employee_benefits": GustoEndpointConfig(
        name="employee_benefits",
        path="/v1/company_benefits/{company_benefit_uuid}/employee_benefits",
        primary_keys=["_company_benefit_uuid", "uuid"],
        fan_out_parent="company_benefits",
        # By default Gusto returns only the benefits active today, not past or future effective-dated ones.
        extra_params={"include": "all_benefits"},
    ),
    "employment_history": GustoEndpointConfig(
        name="employment_history",
        path="/v1/employees/{employee_uuid}/employment_history",
        # Employments carry no identifier; a rehire starts a new employment with a new hire date.
        primary_keys=["_employee_uuid", "hire_date"],
        paginated=False,
        fan_out_parent="employees",
    ),
    # The date filters here match requests whose days overlap the window, not requests that changed,
    # and `status` moves from pending to approved or consumed later, so full refresh keeps it current.
    "time_off_requests": GustoEndpointConfig(
        name="time_off_requests",
        path="/v1/companies/{company_uuid}/time_off/requests",
        primary_keys=["_company_uuid", "uuid"],
        # The default is newest start date first; ascending puts new (mostly future) requests on
        # the last page instead of shifting every page mid-walk.
        extra_params={"sort_order": "asc"},
    ),
}

ENDPOINTS = tuple(GUSTO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "payrolls": [
        {
            "label": "check_date",
            "type": IncrementalFieldType.Date,
            "field": "check_date",
            "field_type": IncrementalFieldType.Date,
        },
    ],
    "pay_periods": [
        {
            "label": "end_date",
            "type": IncrementalFieldType.Date,
            "field": "end_date",
            "field_type": IncrementalFieldType.Date,
        },
    ],
    "contractor_payments": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        },
    ],
}
