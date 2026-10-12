from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class GustoEndpointConfig:
    name: str
    # Path under the API host. `{company_uuid}` / `{employee_uuid}` are filled in per parent row.
    path: str
    primary_keys: list[str]
    # Company-scoped collections paginate with `page`/`per`; the derived `companies` table and the
    # per-employee child lists come back whole in a single response.
    paginated: bool = True
    # Money-movement endpoints take a `start_date`/`end_date` check-date window instead of being
    # walked in full. The value is the row field the window filters on, which is also the only
    # incremental cursor Gusto offers.
    date_window_field: str | None = None
    # Fan-out endpoints are fetched once per employee of each company.
    fans_out_over_employees: bool = False
    # Rows nested under this key in the response body (None = the body is the array itself).
    data_key: str | None = None


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
        fans_out_over_employees=True,
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
