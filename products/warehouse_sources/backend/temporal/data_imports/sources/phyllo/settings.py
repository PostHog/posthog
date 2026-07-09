from dataclasses import dataclass, field


@dataclass
class PhylloEndpointConfig:
    name: str
    path: str
    # Endpoints keyed off a linked creator account require an `account_id` query param, so we fan
    # out over the accounts listing and pull each account's rows in turn.
    fan_out_by_account: bool = False
    # Phyllo object identifiers are platform-generated UUIDs unique across the system (a content
    # item, transaction, or payout belongs to exactly one account), so `id` is a safe table-wide key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Phyllo v1 REST list endpoints (https://docs.getphyllo.com). All are full refresh only: the
# content and income endpoints document from_date/to_date filters, but we could not verify that
# they are honored server-side (and no endpoint documents an updated-after cursor), so we
# conservatively re-pull each stream every sync (see the implementing-warehouse-sources skill).
PHYLLO_ENDPOINTS: dict[str, PhylloEndpointConfig] = {
    "work_platforms": PhylloEndpointConfig(name="work_platforms", path="/v1/work-platforms"),
    "users": PhylloEndpointConfig(name="users", path="/v1/users"),
    "accounts": PhylloEndpointConfig(name="accounts", path="/v1/accounts"),
    "profiles": PhylloEndpointConfig(name="profiles", path="/v1/profiles"),
    "social_contents": PhylloEndpointConfig(
        name="social_contents", path="/v1/social/contents", fan_out_by_account=True
    ),
    "income_transactions": PhylloEndpointConfig(
        name="income_transactions", path="/v1/income/transactions", fan_out_by_account=True
    ),
    "income_payouts": PhylloEndpointConfig(name="income_payouts", path="/v1/income/payouts", fan_out_by_account=True),
}

ENDPOINTS = tuple(PHYLLO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
