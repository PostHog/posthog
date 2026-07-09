from dataclasses import dataclass, field


@dataclass
class PayFitEndpointConfig:
    name: str
    # Appended to /companies/{companyId} on the Partner API host.
    path: str
    # Key wrapping the rows in the JSON response, e.g. {"collaborators": [...], "meta": {...}}.
    data_key: str
    # OAuth scope the API key must carry to read this endpoint.
    scope: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Payslips have no list-all endpoint; they are fetched per collaborator.
    fan_out_over_collaborators: bool = False
    extra_params: dict[str, str] = field(default_factory=dict)


# PayFit Partner API list endpoints. All are full-refresh only: PayFit exposes no server-side
# `updated_after`/`since` filter on any of them, so there is no incremental cursor to advance.
# Country-specific endpoints (meal vouchers, health insurance and provident funds, accounting CSV
# exports) are intentionally not synced.
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
}

ENDPOINTS = tuple(PAYFIT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
