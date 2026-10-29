import datetime
from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Month-scoped endpoints take a required `date=YYYYMM` and return one pay period per request, so a
# first sync walks back this far and later full refreshes keep the same start.
MONTHLY_HISTORY_LOOKBACK = datetime.timedelta(days=3 * 365)

# A pay period's payroll can stay open after later months have rows, so an incremental run reads
# this many months before the watermark again.
INCREMENTAL_REREAD_MONTHS = 3

MONTH_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "month",
        "type": IncrementalFieldType.Date,
        "field": "month",
        "field_type": IncrementalFieldType.Date,
    }
]


@dataclass(frozen=True)
class PayFitEndpointConfig:
    name: str
    # Appended to /companies/{companyId} on the Partner API host.
    path: str
    # Key wrapping the rows in the JSON response, e.g. {"collaborators": [...], "meta": {...}}.
    # None means the body itself is the row (an object) or the rows (an array).
    data_key: str | None
    # OAuth scope the API key must carry to read this endpoint, or None when it needs none.
    scope: str | None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Payslips have no list-all endpoint; they are fetched per collaborator.
    fan_out_over_collaborators: bool = False
    extra_params: dict[str, str] = field(default_factory=dict)
    paginated: bool = True
    # Fetched once per pay period, with each row stamped with a `month` date column.
    monthly: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stamp each row with its position in the response, for rows that carry no ID.
    number_rows: bool = False


# PayFit Partner API endpoints. List endpoints expose no server-side `updated_after`/`since`
# filter, so they are full refresh only. Month-scoped endpoints can sync incrementally by month,
# because the requested pay period is the server-side filter. Accounting entries and worked time
# are French-only endpoints. Meal vouchers, health insurance and provident funds, and the
# accounting CSV export are not synced.
PAYFIT_ENDPOINTS: dict[str, PayFitEndpointConfig] = {
    "collaborators": PayFitEndpointConfig(
        name="collaborators",
        path="/collaborators",
        data_key="collaborators",
        scope="collaborators:read",
    ),
    "contracts": PayFitEndpointConfig(
        name="contracts",
        path="/contracts",
        data_key="contracts",
        scope="contracts:read",
        primary_keys=["contractId"],
    ),
    "absences": PayFitEndpointConfig(
        name="absences",
        path="/absences",
        data_key="absences",
        scope="time:read",
        # The API defaults to approved absences only; sync every status so the warehouse keeps
        # pending/declined/cancelled rows with their `status` column.
        extra_params={"status": "all"},
    ),
    "payslips": PayFitEndpointConfig(
        name="payslips",
        path="/collaborators/{collaboratorId}/payslips",
        data_key="payslips",
        scope="contracts:payslips:read",
        # Rows are aggregated across every collaborator, so the parent id is part of the key.
        primary_keys=["collaboratorId", "payslipId"],
        fan_out_over_collaborators=True,
    ),
    "company": PayFitEndpointConfig(
        name="company",
        path="",
        data_key=None,
        scope=None,
        paginated=False,
    ),
    "payroll_status": PayFitEndpointConfig(
        name="payroll_status",
        path="/payroll-status",
        data_key=None,
        scope=None,
        primary_keys=["month"],
        paginated=False,
        monthly=True,
        incremental_fields=MONTH_INCREMENTAL_FIELDS,
    ),
    "contracts_worked_time": PayFitEndpointConfig(
        name="contracts_worked_time",
        path="/contracts/time",
        data_key="contracts",
        scope="time:read",
        primary_keys=["month", "contractId"],
        monthly=True,
        incremental_fields=MONTH_INCREMENTAL_FIELDS,
    ),
    "accounting_entries": PayFitEndpointConfig(
        name="accounting_entries",
        path="/accounting-v2",
        data_key=None,
        scope="accounting:read",
        # Entries carry no ID, and one contract and account can repeat across analytic codes, so
        # rows are keyed by their position in the month's export. That key is only stable within
        # one read, which is why this table is full refresh only.
        primary_keys=["month", "lineNumber"],
        paginated=False,
        monthly=True,
        number_rows=True,
    ),
}

ENDPOINTS = tuple(PAYFIT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PAYFIT_ENDPOINTS.items() if config.incremental_fields
}
