from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

SKIO_GRAPHQL_URL = "https://graphql.skio.com/v1/graphql"

# Skio caps queries at 100 returned nodes per request (see the rate limits section at
# https://code.skio.com), so one flat page of rows sits exactly at that cap.
SKIO_PAGE_SIZE = 100


# Collections Skio exposes only as array relationships are read through their parent, a page of
# parents at a time. A parent page is kept small because every parent carries up to a full child
# page, and a parent with more children than that is read on in follow-up queries.
SKIO_PARENT_PAGE_SIZE = 25


@frozen
class SkioParentConfig:
    """The root collection a nested endpoint is read through."""

    query_name: str
    graphql_type: str


@frozen
class SkioEndpointConfig:
    """One Skio GraphQL collection synced as a table.

    `query_name` is the field that returns the rows: a root query, or for an endpoint with a
    `parent` the array relationship on that parent. `graphql_type` is the Hasura object type of the
    rows, which names the generated `<type>_bool_exp` / `<type>_order_by` input types the query
    document declares. `fields` is the flat scalar selection set, taken verbatim from the published
    schema at https://code.skio.com; Skio limits query depth to 4 nested levels, so every stream
    selects scalars only and relationships are joined in the warehouse via the *Id columns.
    """

    name: str
    query_name: str
    graphql_type: str
    fields: tuple[str, ...]
    description: str
    parent: SkioParentConfig | None = None
    created_field: str = "createdAt"
    updated_field: str = "updatedAt"

    @property
    def query_document(self) -> str:
        """The stream's GraphQL document. Filtering, ordering, and page size ride in as variables
        so one document serves full refresh, incremental, and resumed pages alike."""
        if self.parent is not None:
            return self._nested_query_document(self.parent)
        field_lines = "\n".join(f"      {field}" for field in self.fields)
        return f"""query {self.query_name}Page($limit: Int!, $where: {self.graphql_type}_bool_exp, $orderBy: [{self.graphql_type}_order_by!]) {{
    {self.query_name}(limit: $limit, where: $where, order_by: $orderBy) {{
{field_lines}
    }}
}}"""

    def _nested_query_document(self, parent: SkioParentConfig) -> str:
        field_lines = "\n".join(f"        {field}" for field in self.fields)
        return f"""query {parent.query_name}{self.query_name}Page($parentLimit: Int!, $parentWhere: {parent.graphql_type}_bool_exp, $limit: Int!, $where: {self.graphql_type}_bool_exp, $orderBy: [{self.graphql_type}_order_by!]) {{
    {parent.query_name}(limit: $parentLimit, where: $parentWhere, order_by: [{{id: asc}}]) {{
      id
      {self.query_name}(limit: $limit, where: $where, order_by: $orderBy) {{
{field_lines}
      }}
    }}
}}"""


ENDPOINTS: dict[str, SkioEndpointConfig] = {
    "subscriptions": SkioEndpointConfig(
        name="subscriptions",
        query_name="Subscriptions",
        graphql_type="Subscription",
        fields=(
            "id",
            "platformId",
            "status",
            "statusContext",
            "createdAt",
            "updatedAt",
            "cancelledAt",
            "nextBillingDate",
            "nextRenewalDate",
            "lastBillingAttemptAt",
            "currencyCode",
            "deliveryPrice",
            "deliveryPriceOverride",
            "cyclesCompleted",
            "remainingCyclesUntilRenewal",
            "prepaidProductPricesPerDelivery",
            "isPickup",
            "note",
            "customAttributes",
            "metadata",
            "churnScore",
            "churnPredictedAt",
            "churnRiskReasons",
            "streakCount",
            "maxStreakCount",
            "streakExpiresAt",
            "migrationIndex",
            "billingPolicyId",
            "deliveryPolicyId",
            "prepaidDeliveryPolicyId",
            "originOrderId",
            "shippingAddressId",
            "storefrontUserId",
            "siteId",
        ),
        description="Subscription contracts, mirroring Shopify SubscriptionContract objects.",
    ),
    "subscription_lines": SkioEndpointConfig(
        name="subscription_lines",
        query_name="SubscriptionLines",
        graphql_type="SubscriptionLine",
        fields=(
            "id",
            "platformId",
            "subscriptionId",
            "productVariantId",
            "sellingPlanId",
            "quantity",
            "priceWithoutDiscount",
            "taxable",
            "titleOverride",
            "isPrepaid",
            "ordersRemaining",
            "prepaidSubscriptionId",
            "groupId",
            "reChargeId",
            "customAttributes",
            "createdAt",
            "updatedAt",
            "removedAt",
        ),
        description="Line items on a subscription, mirroring Shopify SubscriptionLine objects.",
    ),
    "orders": SkioEndpointConfig(
        name="orders",
        query_name="Orders",
        graphql_type="Order",
        # `subscriptionId` is deliberately not selected: Skio's schema documents it as never
        # written (always null). The real link from an order to its subscription runs through
        # order_line_items.subscriptionLineId -> subscription_lines.subscriptionId.
        fields=(
            "id",
            "platformId",
            "platformNumber",
            "name",
            "storefrontUserId",
            "shippingAddressId",
            "siteId",
            "currencyCode",
            "totalPrice",
            "totalPricePresentmentAmount",
            "taxExempt",
            "taxesIncluded",
            "note",
            "appId",
            "clientIp",
            "firstOrderInPrepaidSequence",
            "prepaidSubscriptionId",
            "fulfillAt",
            "fulfillmentOrderCredit",
            "processedAt",
            "deliveredAt",
            "cancelledAt",
            "deletedAt",
            "createdAt",
            "updatedAt",
        ),
        description="Orders generated by subscriptions, mirroring Shopify Order objects.",
    ),
    "order_line_items": SkioEndpointConfig(
        name="order_line_items",
        query_name="OrderLineItems",
        graphql_type="OrderLineItem",
        fields=(
            "id",
            "platformId",
            "orderId",
            "subscriptionLineId",
            "productVariantId",
            "quantity",
            "priceWithoutDiscount",
            "pricePresentmentAmount",
            "pricePresentmentCurrencyCode",
            "currencyCode",
            "attributionGroupId",
            "groupId",
            "customAttributes",
            "createdAt",
            "updatedAt",
        ),
        description="Line items on an order, mirroring Shopify LineItem objects.",
    ),
    "customers": SkioEndpointConfig(
        name="customers",
        query_name="StorefrontUsers",
        graphql_type="StorefrontUser",
        # `qaToken` is deliberately not selected: it is a login token, not customer data.
        fields=(
            "id",
            "platformId",
            "email",
            "emailLower",
            "firstName",
            "lastName",
            "phoneNumber",
            "shopifyTags",
            "smsTransactionalOptIn",
            "tempSmsTransactionalOptIn",
            "siteId",
            "redactedAt",
            "removedAt",
            "createdAt",
            "updatedAt",
        ),
        description="Storefront customers with subscriptions, mirroring Shopify Customer objects.",
    ),
    "addresses": SkioEndpointConfig(
        name="addresses",
        query_name="Addresses",
        graphql_type="Address",
        # `doorCode` is deliberately not selected: it is a physical-access code for delivery,
        # not shipping data, and warehouse access is granted at table/source scope with no
        # column-specific redaction for it.
        fields=(
            "id",
            "platformId",
            "storefrontUserId",
            "firstName",
            "lastName",
            "company",
            "address1",
            "address2",
            "city",
            "province",
            "zip",
            "country",
            "phoneNumber",
            "createdAt",
            "updatedAt",
        ),
        description="Shipping addresses attached to customers and subscriptions.",
    ),
    "products": SkioEndpointConfig(
        name="products",
        query_name="Products",
        graphql_type="Product",
        fields=(
            "id",
            "platformId",
            "title",
            "slug",
            "status",
            "description",
            "imageSrc",
            "images",
            "shopifyTags",
            "metafields",
            "canUpsell",
            "hideOn1TimeUpsells",
            "limitOneTimeUpsellQuantity",
            "oneTimeUpsellPercentageOff",
            "smsOrder",
            "siteId",
            "deletedAt",
            "createdAt",
            "updatedAt",
        ),
        description="Products available on subscription, mirroring Shopify Product objects.",
    ),
    "product_variants": SkioEndpointConfig(
        name="product_variants",
        query_name="ProductVariants",
        graphql_type="ProductVariant",
        fields=(
            "id",
            "platformId",
            "productId",
            "title",
            "sku",
            "price",
            "compareAtPrice",
            "position",
            "image",
            "marketPrices",
            "outOfStockAt",
            "deletedAt",
            "createdAt",
            "updatedAt",
        ),
        description="Product variants available on subscription, mirroring Shopify ProductVariant objects.",
    ),
    "policies": SkioEndpointConfig(
        name="policies",
        query_name="Policies",
        graphql_type="Policy",
        fields=(
            "id",
            "interval",
            "intervalCount",
            "minCycles",
            "maxCycles",
            "isMaxCycleV2",
            "createdAt",
            "updatedAt",
        ),
        description="Billing and delivery policies: the cadence a subscription bills or ships on.",
    ),
    "selling_plans": SkioEndpointConfig(
        name="selling_plans",
        # Skio has no root query for selling plans. Every plan has exactly one (non-null) billing
        # policy, so reading them through it returns each plan once, where reading them through
        # subscription lines would repeat a plan for every line on it.
        query_name="SellingPlansByBillingPolicy",
        graphql_type="SellingPlan",
        parent=SkioParentConfig(query_name="Policies", graphql_type="Policy"),
        fields=(
            "id",
            "platformId",
            "name",
            "option",
            "position",
            "description",
            "sellingPlanGroupId",
            "billingPolicyId",
            "deliveryPolicyId",
            "prepaidDeliveryPolicyId",
            "productVariantIdToSwapToAfterFirstOrder",
            "availableInCustomerPortal",
            "availableInDashboard",
            "availableOnStorefront",
            "availableViaApi",
            "siteId",
            "createdAt",
            "updatedAt",
        ),
        description="Selling plans that subscription lines are sold on, mirroring Shopify SellingPlan objects.",
    ),
    "audit_logs": SkioEndpointConfig(
        name="audit_logs",
        query_name="AuditLogs",
        graphql_type="AuditLog",
        parent=SkioParentConfig(query_name="Subscriptions", graphql_type="Subscription"),
        fields=(
            "id",
            "subscriptionId",
            "storefrontUserId",
            "eventType",
            "eventData",
            "createdAt",
            "updatedAt",
        ),
        description="Lifecycle events recorded on subscriptions, such as pauses, skips, and cancellations.",
    ),
    "cancel_flow_v2_sessions": SkioEndpointConfig(
        name="cancel_flow_v2_sessions",
        query_name="CancelFlowV2Sessions",
        graphql_type="CancelFlowV2Session",
        parent=SkioParentConfig(query_name="Subscriptions", graphql_type="Subscription"),
        fields=(
            "id",
            "subscriptionId",
            "cancelFlowId",
            "siteId",
            "status",
            "reason",
            "reasonPath",
            "isOtherReason",
            "rebuttal",
            "rebuttalOptions",
            "action",
            "actions",
            "actionsV2",
            "actionsV2MultiStep",
            "isMultipleActions",
            "isSplashScreen",
            "conditions",
            "conditionsV2",
            "shownReasons",
            "shownRebuttals",
            "shownActions",
            "created_at",
            "updated_at",
        ),
        description="Sessions of customers going through a version 2 cancel flow, with the reasons, offers, and outcome.",
        # Unlike every other Skio type, CancelFlowV2Session names its timestamps in snake_case.
        created_field="created_at",
        updated_field="updated_at",
    ),
    "cancel_flow_v3_sessions": SkioEndpointConfig(
        name="cancel_flow_v3_sessions",
        query_name="CancelFlowV3Sessions",
        graphql_type="CancelFlowV3Session",
        parent=SkioParentConfig(query_name="Subscriptions", graphql_type="Subscription"),
        fields=(
            "id",
            "subscriptionId",
            "cancelFlowId",
            "versionNumber",
            "siteId",
            "type",
            "status",
            "pathTaken",
            "createdAt",
            "updatedAt",
        ),
        description="Sessions of customers going through a version 3 cancel flow, with the path they took and the outcome.",
    ),
}

# Every collection carries non-null created/updated timestamptz columns with server-side
# comparison filters in its Hasura bool_exp, so both are genuine incremental cursors.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": config.updated_field,
            "type": IncrementalFieldType.DateTime,
            "field": config.updated_field,
            "field_type": IncrementalFieldType.DateTime,
        },
        {
            "label": config.created_field,
            "type": IncrementalFieldType.DateTime,
            "field": config.created_field,
            "field_type": IncrementalFieldType.DateTime,
        },
    ]
    for name, config in ENDPOINTS.items()
}
