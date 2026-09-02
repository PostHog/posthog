"""Account-scoped batch audiences: one invocation per customer analytics account.

The trigger's stored ``filters`` dict is the single source of truth. ``audience_type:
'accounts'`` switches the batch resolver from persons to accounts; the remaining keys
(``properties`` of account custom property filters, ``tag_names``, ``assigned_to_user_ids``,
``all_roles_unassigned``) narrow which accounts a firing fans out to.

customer_analytics owns the account data but already depends on workflows, so the query
implementation arrives through a provider registered during ``django.setup()``
(``CustomerAnalyticsConfig.ready``) — the same hook inversion warehouse_sources uses.
"""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from rest_framework import exceptions

from posthog.models.team.team import Team

ACCOUNT_BATCH_SIZE = 500

# Mirrors ACCOUNT_CUSTOM_PROPERTY_OPERATOR_ALLOWLIST in
# products/customer_analytics/frontend/components/Accounts/accountsCustomPropertyFilters.ts.
SUPPORTED_CUSTOM_PROPERTY_OPERATORS = frozenset(
    {
        "exact",
        "is_not",
        "icontains",
        "not_icontains",
        "regex",
        "not_regex",
        "gt",
        "gte",
        "lt",
        "lte",
        "is_set",
        "is_not_set",
        "is_date_exact",
        "is_date_before",
        "is_date_after",
    }
)

_VALUELESS_OPERATORS = frozenset({"is_set", "is_not_set"})


@dataclass(frozen=True, kw_only=True)
class AccountAudienceCustomPropertyFilter:
    """One custom-property predicate of a batch audience (key = definition id)."""

    definition_id: UUID
    operator: str
    value: Any = None


@dataclass(frozen=True, kw_only=True)
class AccountAudienceFilters:
    """Account selection for a batch run; empty filters mean every account with an external_id."""

    tag_names: tuple[str, ...] = ()
    assigned_to_user_ids: tuple[int, ...] = ()
    all_roles_unassigned: bool = False
    custom_properties: tuple[AccountAudienceCustomPropertyFilter, ...] = ()


class AccountAudienceProvider(Protocol):
    def count_accounts(self, team: Team, filters: AccountAudienceFilters) -> int: ...

    def list_account_external_ids(
        self, team: Team, filters: AccountAudienceFilters, *, cursor: str | None, limit: int
    ) -> list[str]: ...

    def get_account_group_type_name(self, team: Team) -> str | None: ...


_provider: AccountAudienceProvider | None = None


def register_account_audience_provider(provider: AccountAudienceProvider) -> None:
    global _provider
    _provider = provider


def _require_provider() -> AccountAudienceProvider:
    if _provider is None:
        raise exceptions.ValidationError({"filters": "Account audiences are not available on this instance."})
    return _provider


def is_account_audience(filters: dict | None) -> bool:
    return bool(filters) and filters.get("audience_type") == "accounts"  # type: ignore[union-attr]


def get_account_group_type_name(team: Team) -> str | None:
    return _provider.get_account_group_type_name(team) if _provider is not None else None


def parse_account_audience_filters(filters: dict) -> AccountAudienceFilters:
    properties = filters.get("properties") or []
    if not isinstance(properties, list):
        raise exceptions.ValidationError({"filters": {"properties": "Properties must be an array."}})

    custom_properties: list[AccountAudienceCustomPropertyFilter] = []
    for entry in properties:
        if not isinstance(entry, dict) or entry.get("type") != "account_custom_property":
            raise exceptions.ValidationError(
                {"filters": {"properties": "Account audiences only support account custom property filters."}}
            )
        try:
            definition_id = UUID(str(entry.get("key")))
        except (ValueError, TypeError):
            raise exceptions.ValidationError(
                {"filters": {"properties": "Account custom property filter keys must be property definition ids."}}
            )
        operator = str(entry.get("operator") or "exact")
        # A dropped predicate would silently broaden a mass send to every account, so anything
        # the compiler can't express is rejected at write time instead.
        if operator not in SUPPORTED_CUSTOM_PROPERTY_OPERATORS:
            raise exceptions.ValidationError(
                {"filters": {"properties": f"Unsupported operator for account audiences: {operator}"}}
            )
        value = entry.get("value")
        if operator not in _VALUELESS_OPERATORS and value in (None, "", []):
            raise exceptions.ValidationError(
                {"filters": {"properties": f"A value is required for the {operator} operator."}}
            )
        custom_properties.append(
            AccountAudienceCustomPropertyFilter(
                definition_id=definition_id,
                operator=operator,
                value=value,
            )
        )

    tag_names = filters.get("tag_names") or []
    if not isinstance(tag_names, list) or not all(isinstance(tag, str) for tag in tag_names):
        raise exceptions.ValidationError({"filters": {"tag_names": "Must be a list of tag names."}})

    assigned_to_user_ids = filters.get("assigned_to_user_ids") or []
    if not isinstance(assigned_to_user_ids, list) or not all(
        isinstance(user_id, int) and not isinstance(user_id, bool) for user_id in assigned_to_user_ids
    ):
        raise exceptions.ValidationError({"filters": {"assigned_to_user_ids": "Must be a list of user ids."}})

    return AccountAudienceFilters(
        tag_names=tuple(tag_names),
        assigned_to_user_ids=tuple(assigned_to_user_ids),
        all_roles_unassigned=bool(filters.get("all_roles_unassigned")),
        custom_properties=tuple(custom_properties),
    )


def get_account_audience_page(team: Team, filters: dict, cursor: str | None) -> list[str]:
    parsed = parse_account_audience_filters(filters)
    try:
        return _require_provider().list_account_external_ids(team, parsed, cursor=cursor, limit=ACCOUNT_BATCH_SIZE)
    except ValueError as e:
        raise exceptions.ValidationError({"filters": str(e)})


def get_account_audience_count(team: Team, filters: dict) -> int:
    try:
        return _require_provider().count_accounts(team, parse_account_audience_filters(filters))
    except ValueError as e:
        raise exceptions.ValidationError({"filters": str(e)})
