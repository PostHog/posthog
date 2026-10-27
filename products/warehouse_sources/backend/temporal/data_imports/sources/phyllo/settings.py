from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


@frozen
class PhylloEndpointConfig:
    name: str
    path: str
    # Endpoints keyed off a linked creator account require an `account_id` query param, so we fan
    # out over the accounts listing and pull each account's rows in turn.
    fan_out_by_account: bool = False
    # Comments need both `account_id` and `content_id`, so we fan out accounts -> contents -> comments.
    fan_out_by_content: bool = False
    # The endpoint returns one object per account instead of a paginated `data` list.
    single_object: bool = False
    # Query params for a date window that the endpoint requires on every request (from, to).
    date_window_params: tuple[str, str] | None = None
    # Phyllo object identifiers are platform-generated UUIDs unique across the system (a content
    # item, transaction, or payout belongs to exactly one account), so `id` is a safe table-wide key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Phyllo v1 REST list endpoints (https://docs.getphyllo.com). All are full refresh only: the
# content and income endpoints document from_date/to_date filters, but we could not verify that
# they are honored server-side (and no endpoint documents an updated-after cursor), so we
# conservatively re-pull each stream every sync (see the implementing-warehouse-sources skill).
# commerce_income_transactions requires its date window, but one table-wide watermark would skip the
# history of an account connected after the first sync, and the status updates of older
# transactions, so it also re-pulls the full window every sync.
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
    "audience": PhylloEndpointConfig(name="audience", path="/v1/audience", fan_out_by_account=True, single_object=True),
    "social_comments": PhylloEndpointConfig(
        name="social_comments", path="/v1/social/comments", fan_out_by_account=True, fan_out_by_content=True
    ),
    "social_content_groups": PhylloEndpointConfig(
        name="social_content_groups", path="/v1/social/content-groups", fan_out_by_account=True
    ),
    "commerce_income_transactions": PhylloEndpointConfig(
        name="commerce_income_transactions",
        path="/v1/commerce/income/transactions",
        fan_out_by_account=True,
        date_window_params=("transaction_from_date", "transaction_to_date"),
    ),
}

ENDPOINTS = tuple(PHYLLO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
