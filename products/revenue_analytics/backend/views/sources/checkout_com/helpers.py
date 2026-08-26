from django.db.models import QuerySet

from posthog.schema import CurrencyCode

from posthog.hogql import ast
from posthog.hogql.database.schema.exchange_rate import convert_currency_call

from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.models.team.team import Team

from products.revenue_analytics.backend.views.sources.helpers import currency_aware_amount
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema

# Schema (table) names the Checkout.com warehouse source syncs from the payments search API.
# These match `PAYMENTS_ENDPOINTS` in the source module
# (products/warehouse_sources/backend/temporal/data_imports/sources/checkout_com/payments.py),
# which owns the persisted schema names.
PAYMENT_RESOURCE_NAME = "payments"
PAYMENT_ACTION_RESOURCE_NAME = "payment_actions"
CUSTOMER_RESOURCE_NAME = "customers"

# Checkout.com represents most currencies in minor units (the amount divided by 100),
# but two groups are special:
# - full-value currencies, where the amount is already the final amount
# - three-decimal currencies, where the amount is divided by 1000
# Note this differs from Stripe's zero-decimal list (`ZERO_DECIMAL_CURRENCIES_IN_STRIPE`):
# Checkout.com treats ISK as full-value and CLP/MGA as two-decimal, and has a separate
# three-decimal group. https://www.checkout.com/docs/payments/accept-payments/format-the-amount-value
ZERO_DECIMAL_CURRENCIES_IN_CHECKOUT_COM: list[str] = [
    CurrencyCode.BIF.value,
    CurrencyCode.DJF.value,
    CurrencyCode.GNF.value,
    CurrencyCode.ISK.value,
    CurrencyCode.JPY.value,
    CurrencyCode.KMF.value,
    CurrencyCode.KRW.value,
    CurrencyCode.PYG.value,
    CurrencyCode.RWF.value,
    CurrencyCode.UGX.value,
    CurrencyCode.VND.value,
    CurrencyCode.VUV.value,
    CurrencyCode.XAF.value,
    CurrencyCode.XOF.value,
    CurrencyCode.XPF.value,
]

THREE_DECIMAL_CURRENCIES_IN_CHECKOUT_COM: list[str] = [
    CurrencyCode.BHD.value,
    CurrencyCode.IQD.value,
    CurrencyCode.JOD.value,
    CurrencyCode.KWD.value,
    CurrencyCode.LYD.value,
    CurrencyCode.OMR.value,
    CurrencyCode.TND.value,
]


def is_zero_decimal_in_checkout_com(field: ast.Field) -> ast.Call:
    return ast.Call(
        name="in",
        args=[field, ast.Constant(value=ZERO_DECIMAL_CURRENCIES_IN_CHECKOUT_COM)],
    )


def currency_aware_divider() -> ast.Alias:
    """Divider between the raw Checkout.com amount and the decimal amount: 1 for
    full-value currencies, 1000 for three-decimal currencies, 100 for everything else."""
    return ast.Alias(
        alias="currency_aware_divider",
        expr=ast.Call(
            name="multiIf",
            args=[
                ast.Field(chain=["enable_currency_aware_divider"]),
                ast.Call(
                    name="toDecimal",
                    args=[ast.Constant(value=1), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)],
                ),
                ast.Call(
                    name="in",
                    args=[
                        ast.Field(chain=["original_currency"]),
                        ast.Constant(value=THREE_DECIMAL_CURRENCIES_IN_CHECKOUT_COM),
                    ],
                ),
                ast.Call(
                    name="toDecimal",
                    args=[ast.Constant(value=1000), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)],
                ),
                ast.Call(
                    name="toDecimal",
                    args=[ast.Constant(value=100), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)],
                ),
            ],
        ),
    )


def parse_timestamp(field: ast.Expr) -> ast.Call:
    # Checkout.com timestamps sync as ISO-8601 strings (the pipeline stores the raw API
    # values), so they need parsing before they can be used as datetimes. `toString`
    # keeps this a no-op-ish coercion if the column ever becomes a real datetime.
    # HogQL's parseDateTimeBestEffort prints as ClickHouse's parseDateTime64BestEffortOrNull.
    return ast.Call(
        name="parseDateTimeBestEffort",
        args=[ast.Call(name="toString", args=[field])],
    )


def extract_json_string_from(field_chain: list[str | int], *path: str) -> ast.Call:
    """Like the shared helpers.extract_json_string, but for a qualified (aliased-table) field chain."""
    return ast.Call(
        name="JSONExtractString",
        args=[
            ast.Field(chain=field_chain),
            *[ast.Constant(value=p) for p in path],
        ],
    )


def customer_id_expr() -> ast.Call:
    # The payment's customer is a JSON object; its `id` matches the customers table.
    # Empty (customer-less payments) becomes NULL so joins and filters behave.
    return ast.Call(
        name="nullIf",
        args=[
            extract_json_string_from(["payment", "customer"], "id"),
            ast.Constant(value=""),
        ],
    )


def get_table(schemas: QuerySet[ExternalDataSchema], schema_name: str) -> DataWarehouseTable | None:
    schema = next((schema for schema in schemas if schema.name == schema_name), None)
    if schema is None:
        return None

    return schema.table


def approved_captures_join_expr(actions_table: DataWarehouseTable, payments_table: DataWarehouseTable) -> ast.JoinExpr:
    """FROM <payment_actions> AS action JOIN <payments> AS payment ON action.payment_id = payment.id.

    Approved `Capture` actions are Checkout.com's charges: the payment object only carries
    the latest status and the requested amount, while each capture action carries the exact
    captured amount and time. The parent payment supplies the currency (actions have none),
    the customer and the payment type.
    """
    return ast.JoinExpr(
        alias="action",
        table=ast.Field(chain=[actions_table.name]),
        next_join=ast.JoinExpr(
            alias="payment",
            table=ast.Field(chain=[payments_table.name]),
            join_type="INNER JOIN",
            constraint=ast.JoinConstraint(
                constraint_type="ON",
                expr=ast.CompareOperation(
                    left=ast.Field(chain=["action", "payment_id"]),
                    right=ast.Field(chain=["payment", "id"]),
                    op=ast.CompareOperationOp.Eq,
                ),
            ),
        ),
    )


def approved_captures_where_expr() -> ast.Expr:
    # Refund and Void actions also live in payment_actions; only approved captures
    # represent money coming in. Matching case-insensitively guards against casing
    # drift in the API's action type values.
    return ast.And(
        exprs=[
            ast.CompareOperation(
                left=ast.Call(name="lower", args=[ast.Field(chain=["action", "type"])]),
                right=ast.Constant(value="capture"),
                op=ast.CompareOperationOp.Eq,
            ),
            ast.Field(chain=["action", "approved"]),
        ]
    )


def currency_conversion_fields(team: Team) -> list[ast.Expr]:
    """The `original_currency` .. `amount` tail shared by the charge and revenue item views.

    Amounts come from the capture action (in Checkout.com's minor units) and the currency
    from the parent payment, converted into the team's base currency at the `timestamp`
    aliased earlier in the same select.
    """
    return [
        # Uppercase to match the currency codes in the `exchange_rate` table
        ast.Alias(
            alias="original_currency",
            expr=ast.Call(name="upper", args=[ast.Field(chain=["payment", "currency"])]),
        ),
        # The captured amount, in Checkout.com's minor units for the currency
        ast.Alias(
            alias="original_amount",
            expr=ast.Call(
                name="toDecimal",
                args=[
                    ast.Field(chain=["action", "amount"]),
                    ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
                ],
            ),
        ),
        # Whether the original currency is a full-value currency in Checkout.com's API
        ast.Alias(
            alias="enable_currency_aware_divider",
            expr=is_zero_decimal_in_checkout_com(ast.Field(chain=["original_currency"])),
        ),
        # 1, 1000 or 100 depending on the currency's minor-unit rules
        currency_aware_divider(),
        # The original amount adjusted into whole currency units
        currency_aware_amount(),
        # The team's base currency, which `amount` is converted into
        ast.Alias(alias="currency", expr=ast.Constant(value=team.base_currency)),
        ast.Alias(
            alias="amount",
            expr=convert_currency_call(
                amount=ast.Field(chain=["currency_aware_amount"]),
                currency_from=ast.Field(chain=["original_currency"]),
                currency_to=ast.Field(chain=["currency"]),
                timestamp=ast.Call(
                    name="_toDate",
                    args=[
                        ast.Call(
                            name="ifNull",
                            args=[
                                ast.Field(chain=["timestamp"]),
                                ast.Call(name="toDateTime", args=[ast.Constant(value=0)]),
                            ],
                        ),
                    ],
                ),
            ),
        ),
    ]
