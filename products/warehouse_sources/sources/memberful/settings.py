from dataclasses import field

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

PAGE_SIZE = 100
CREATED_AT = "createdAt"

CREATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": CREATED_AT,
        "type": IncrementalFieldType.DateTime,
        "field": CREATED_AT,
        "field_type": IncrementalFieldType.Integer,
    },
]

# Fields that would cost a nested lookup per row on the vendor side (a member's orders, a
# subscription's group members) are left out; they are their own tables here.
MEMBER_FIELDS = """
    id
    email
    fullName
    username
    phoneNumber
    discordUserId
    stripeCustomerId
    unrestrictedAccess
    totalOrders
    totalSpendCents
    metadata
    trackingParams
    address { street line2 city state postalCode country }
"""

SUBSCRIPTION_FIELDS = """
    id
    active
    autorenew
    pastDue
    additionalMembers
    createdAt
    activatedAt
    expiresAt
    trialStartAt
    trialEndAt
    member { id }
    plan { id }
    coupon { id code }
"""

ORDER_FIELDS = """
    uuid
    createdAt
    status
    type
    currency
    totalCents
    taxAmountCents
    couponDiscountAmountCents
    purchasableType
    purchasable { ... on Plan { id } ... on Download { id } }
    member { id }
    subscription { id }
    coupon { id code }
"""

ACTIVITY_FIELDS = """
    id
    type
    createdAt
    member { id }
    subscription { id }
"""

COUPON_FIELDS = """
    id
    code
    state
    type
    amountOffCents
    isPercentage
    maximumNumberOfRedemptions
    recurringLimit
    plans { id }
    downloads { id }
"""

# The API calls a dashboard price a `Plan` and a dashboard plan a `Pass`. `name`, `requireAddress`
# and `taxable` on `Plan` are deprecated in favor of the parent pass, so they are not selected.
PLAN_FIELDS = """
    id
    label
    slug
    type
    priceCents
    intervalUnit
    intervalCount
    renewalDay
    renewalMonth
    forSale
    trialType
    trialPriceCents
    includedMembers
    additionalMemberPriceCents
    afterCheckoutRedirectUrl
    pass { id name }
"""

DOWNLOAD_FIELDS = """
    id
    name
    slug
    priceCents
    forSale
"""


@frozen
class MemberfulEndpointConfig:
    root_field: str
    fields: str
    primary_key: str = "id"
    # False for root fields that return a plain list instead of a Relay connection.
    paginated: bool = True
    # True when the root field takes a `createdAt: CreatedAtFilter` argument.
    created_at_filter: bool = False
    supports_append: bool = False
    # New connections default to full refresh even when incremental sync is offered.
    prefers_full_refresh: bool = False
    partition_keys: list[str] | None = None
    # (nested object, key inside it, flat column). A null object gives a null column.
    nested_values: tuple[tuple[str, str, str], ...] = ()
    # (list of nested objects, flat column holding the ids of the list).
    nested_id_lists: tuple[tuple[str, str], ...] = ()
    incremental_fields: list[IncrementalField] = field(default_factory=list)


MEMBERFUL_ENDPOINTS: dict[str, MemberfulEndpointConfig] = {
    # Members have no timestamp field and the query has no filter, so this is full refresh only.
    "members": MemberfulEndpointConfig(root_field="members", fields=MEMBER_FIELDS),
    "subscriptions": MemberfulEndpointConfig(
        root_field="subscriptions",
        fields=SUBSCRIPTION_FIELDS,
        partition_keys=[CREATED_AT],
        nested_values=(
            ("member", "id", "memberId"),
            ("plan", "id", "planId"),
            ("coupon", "id", "couponId"),
            ("coupon", "code", "couponCode"),
        ),
    ),
    # A refund or a suspension changes an order's status but not its createdAt, so an incremental
    # sync never re-reads older orders. Full refresh is the default and append is not offered.
    "orders": MemberfulEndpointConfig(
        root_field="orders",
        fields=ORDER_FIELDS,
        primary_key="uuid",
        created_at_filter=True,
        prefers_full_refresh=True,
        partition_keys=[CREATED_AT],
        nested_values=(
            ("purchasable", "id", "purchasableId"),
            ("member", "id", "memberId"),
            ("subscription", "id", "subscriptionId"),
            ("coupon", "id", "couponId"),
            ("coupon", "code", "couponCode"),
        ),
        incremental_fields=CREATED_AT_INCREMENTAL_FIELDS,
    ),
    "activities": MemberfulEndpointConfig(
        root_field="activities",
        fields=ACTIVITY_FIELDS,
        created_at_filter=True,
        supports_append=True,
        partition_keys=[CREATED_AT],
        nested_values=(
            ("member", "id", "memberId"),
            ("subscription", "id", "subscriptionId"),
        ),
        incremental_fields=CREATED_AT_INCREMENTAL_FIELDS,
    ),
    "coupons": MemberfulEndpointConfig(
        root_field="coupons",
        fields=COUPON_FIELDS,
        nested_id_lists=(("plans", "planIds"), ("downloads", "downloadIds")),
    ),
    "plans": MemberfulEndpointConfig(
        root_field="plans",
        fields=PLAN_FIELDS,
        paginated=False,
        nested_values=(("pass", "id", "passId"), ("pass", "name", "passName")),
    ),
    "downloads": MemberfulEndpointConfig(root_field="downloads", fields=DOWNLOAD_FIELDS, paginated=False),
}

ENDPOINTS = tuple(MEMBERFUL_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MEMBERFUL_ENDPOINTS.items()
}
