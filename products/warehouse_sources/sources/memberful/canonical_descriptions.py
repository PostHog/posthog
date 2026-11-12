"""Canonical descriptions for Memberful tables and columns.

Taken from the field descriptions in Memberful's GraphQL schema and the Memberful API guide
(https://memberful.com/docs/api-reference/memberful-api). Keyed by the endpoint names in
`settings.py`. Flattened columns (`memberId`, `planIds`, ...) are described here as well.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

DOCS_URL = "https://memberful.com/docs/api-reference/memberful-api"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "members": {
        "description": "A person with a Memberful account, with or without an active subscription.",
        "docs_url": DOCS_URL,
        "columns": {
            "id": "Unique identifier for the member.",
            "email": "The member's email address.",
            "fullName": "The member's full name.",
            "username": "The member's username.",
            "phoneNumber": "The member's phone number, if collected.",
            "discordUserId": "The member's Discord user ID, if the Discord integration is connected.",
            "stripeCustomerId": "ID of the Stripe customer that pays for this member.",
            "unrestrictedAccess": "Whether the member has access to all downloads and plans without a purchase.",
            "totalOrders": "Total number of orders the member has placed.",
            "totalSpendCents": "Total amount the member has spent, in cents.",
            "metadata": "Custom string key and value pairs stored on the member through the API.",
            "trackingParams": "Tracking parameters, such as UTM values, recorded when the member signed up.",
            "address": "The member's mailing address, if collected at checkout.",
        },
    },
    "subscriptions": {
        "description": "A member's subscription to a plan price. Group subscriptions can cover additional members.",
        "docs_url": DOCS_URL,
        "columns": {
            "id": "Unique identifier for the subscription.",
            "active": "Whether the subscription is active.",
            "autorenew": "Whether the subscription renews automatically.",
            "pastDue": "Whether the subscription is past due.",
            "additionalMembers": "Number of additional members purchased for a group subscription.",
            "createdAt": "Time the subscription was created, in Unix seconds.",
            "activatedAt": "Last time the subscription was activated, in Unix seconds.",
            "expiresAt": "Time the subscription expires, in Unix seconds. Null for lifetime subscriptions.",
            "trialStartAt": "Start of the trial period, in Unix seconds.",
            "trialEndAt": "End of the trial period, in Unix seconds.",
            "memberId": "ID of the member who owns the subscription.",
            "planId": "ID of the plan price the subscription is for. Join to the plans table.",
            "couponId": "ID of the coupon applied to the subscription, if any.",
            "couponCode": "Code of the coupon applied to the subscription, if any.",
        },
    },
    "orders": {
        "description": "A purchase of a plan price or a download, including renewals, upgrades and manual charges.",
        "docs_url": DOCS_URL,
        "columns": {
            "uuid": "Unique identifier for the order.",
            "createdAt": "Time the order was created, in Unix seconds.",
            "status": "Order status: completed, refunded or suspended.",
            "type": "Order type: new_order, renewal, upgrade, manual_charge or additional_seats.",
            "currency": "Currency of the order, as a lowercase ISO 4217 code.",
            "totalCents": "Total order value, in cents.",
            "taxAmountCents": "Tax charged on the order, in cents.",
            "couponDiscountAmountCents": "Coupon discount applied to the order, in cents.",
            "purchasableType": "Type of the purchased item: Plan or Download.",
            "purchasableId": "ID of the purchased plan price or download.",
            "memberId": "ID of the member who placed the order.",
            "subscriptionId": "ID of the subscription the order belongs to. Set only when the purchased item is a plan.",
            "couponId": "ID of the coupon applied to the order, if any.",
            "couponCode": "Code of the coupon applied to the order, if any.",
        },
    },
    "activities": {
        "description": "An event in the account's activity feed, such as a new order, a renewal or a cancellation.",
        "docs_url": DOCS_URL,
        "columns": {
            "id": "Unique identifier for the activity.",
            "type": "Activity type, for example new_order, renewal, order_refunded or subscription_deactivated.",
            "createdAt": "Time the activity happened, in Unix seconds.",
            "memberId": "ID of the member the activity is about.",
            "subscriptionId": "ID of the subscription the activity is about, if any.",
        },
    },
    "coupons": {
        "description": "A discount code that members can apply at checkout.",
        "docs_url": DOCS_URL,
        "columns": {
            "id": "Unique identifier for the coupon.",
            "code": "The code members enter at checkout.",
            "state": "Coupon state: enabled or disabled.",
            "type": "How the coupon applies: one_time, recurring or limited.",
            "amountOffCents": "Discount amount in cents, or a percentage when isPercentage is true.",
            "isPercentage": "Whether amountOffCents is a percentage of the price instead of an amount.",
            "maximumNumberOfRedemptions": "Maximum number of times the coupon can be redeemed.",
            "recurringLimit": "How many times the coupon applies to a subscription, including the first purchase.",
            "planIds": "IDs of the plan prices the coupon applies to.",
            "downloadIds": "IDs of the downloads the coupon applies to.",
        },
    },
    "plans": {
        "description": (
            "A price that members can subscribe at. The API calls a dashboard price a plan, "
            "and a dashboard plan a pass. Each price belongs to one pass."
        ),
        "docs_url": DOCS_URL,
        "columns": {
            "id": "Unique identifier for the plan price.",
            "label": "Display label of the price, for example $10/month.",
            "slug": "URL slug of the price.",
            "type": "Plan type: standard_plan, fixed_plan, lifetime_plan or date_based_plan.",
            "priceCents": "Price, in cents.",
            "intervalUnit": "Renewal interval unit: week, month or year.",
            "intervalCount": "Number of interval units between renewals.",
            "renewalDay": "Renewal day for date based plans.",
            "renewalMonth": "Renewal month for date based plans.",
            "forSale": "Whether the price is for sale.",
            "trialType": "Trial type: card, free or paid.",
            "trialPriceCents": "Price of a paid trial, in cents.",
            "includedMembers": "Number of members included in a group plan.",
            "additionalMemberPriceCents": "Price of each additional group member, in cents.",
            "afterCheckoutRedirectUrl": "Page members go to after a successful checkout.",
            "passId": "ID of the pass (the dashboard plan) the price belongs to.",
            "passName": "Name of the pass (the dashboard plan) the price belongs to.",
        },
    },
    "downloads": {
        "description": "A digital file that members can buy on its own or get with a plan.",
        "docs_url": DOCS_URL,
        "columns": {
            "id": "Unique identifier for the download.",
            "name": "Name of the download.",
            "slug": "URL slug of the download.",
            "priceCents": "Price of the download, in cents.",
            "forSale": "Whether the download is for sale.",
        },
    },
}
