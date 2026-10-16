"""Canonical, documentation-sourced descriptions for Schematic endpoints and columns.

Sourced from the Schematic API reference (https://docs.schematichq.com/api-reference).
Keyed by the endpoint names in `settings.py`, which match the `ExternalDataSchema.name` of a synced
table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://docs.schematichq.com/api-reference"

_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_at": "Time at which the object was created.",
    "updated_at": "Time at which the object was last updated.",
}


_ENVIRONMENT_ID = "Identifier of the Schematic environment the object belongs to."


def _columns(*, with_id: bool = True, **overrides: str) -> dict[str, str]:
    common = _COMMON_COLUMNS if with_id else {k: v for k, v in _COMMON_COLUMNS.items() if k != "id"}
    return {**common, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "companies": {
        "description": "A customer account in Schematic, with its lookup keys, traits, assigned plans and billing subscription.",
        "docs_url": f"{_DOCS}/companies/list-companies",
        "columns": _columns(
            environment_id=_ENVIRONMENT_ID,
            name="Display name of the company.",
            last_seen_at="Time Schematic last received an event or check for this company.",
            logo_url="URL of the company logo.",
            keys="Lookup keys that identify the company, such as an external id or a billing customer id.",
            traits="Trait values set on the company.",
            entity_traits="Trait definitions and values set on the company.",
            plans="Plans currently assigned to the company.",
            add_ons="Add-on plans currently assigned to the company.",
            billing_subscription="The company's billing subscription, when one is linked.",
            user_count="Number of users that belong to the company.",
            metrics="Usage metrics recorded for the company.",
        ),
    },
    "users": {
        "description": "An end user tracked by Schematic, with its lookup keys, traits and company memberships.",
        "docs_url": f"{_DOCS}/companies/list-users",
        "columns": _columns(
            environment_id=_ENVIRONMENT_ID,
            name="Display name of the user.",
            last_seen_at="Time Schematic last received an event or check for this user.",
            keys="Lookup keys that identify the user.",
            traits="Trait values set on the user.",
            entity_traits="Trait definitions and values set on the user.",
            company_memberships="Companies the user belongs to.",
        ),
    },
    "company_memberships": {
        "description": "A link between a user and a company.",
        "docs_url": f"{_DOCS}/companies/list-company-memberships",
        "columns": _columns(
            company_id="Identifier of the company.",
            user_id="Identifier of the user.",
            company="The company the membership belongs to.",
        ),
    },
    "features": {
        "description": "A feature defined in Schematic that plans and companies can be entitled to.",
        "docs_url": f"{_DOCS}/features/list-features",
        "columns": _columns(
            name="Display name of the feature.",
            description="Description of the feature.",
            feature_type="How the feature is metered: boolean, event or trait.",
            lifecycle_phase="Lifecycle phase of the feature, such as alpha, beta or GA.",
            event_subtype="Event subtype that counts toward an event-metered feature.",
            trait_id="Identifier of the trait that measures a trait-metered feature.",
            icon="Icon shown for the feature in Schematic.",
            flags="Flags attached to the feature.",
            plans="Plans that entitle companies to the feature.",
            maintainer="Account member who maintains the feature.",
        ),
    },
    "flags": {
        "description": "A feature flag evaluated by the Schematic SDKs.",
        "docs_url": f"{_DOCS}/features/list-flags",
        "columns": _columns(
            key="Key used to check the flag from an SDK.",
            name="Display name of the flag.",
            description="Description of the flag.",
            flag_type="Type of the flag.",
            default_value="Value returned when no rule matches.",
            feature_id="Identifier of the feature the flag belongs to.",
            feature="The feature the flag belongs to.",
            rules="Targeting rules evaluated for the flag.",
            last_checked_at="Time the flag was last checked by an SDK.",
        ),
    },
    "plans": {
        "description": "A plan or add-on that bundles feature entitlements and billing products.",
        "docs_url": f"{_DOCS}/plans/list-plans",
        "columns": _columns(
            name="Display name of the plan.",
            description="Description of the plan.",
            plan_type="Whether the row is a plan or an add-on.",
            audience_type="Audience the plan targets.",
            is_default="Whether the plan is the default plan for new companies.",
            is_free="Whether the plan is free.",
            is_trialable="Whether the plan offers a trial.",
            trial_days="Length of the trial in days.",
            company_count="Number of companies on the plan.",
            billing_product="Billing product linked to the plan.",
            monthly_price="Monthly price of the plan.",
            yearly_price="Yearly price of the plan.",
            entitlements="Feature entitlements the plan grants.",
            features="Features included in the plan.",
        ),
    },
    "plan_entitlements": {
        "description": "A feature entitlement granted by a plan, with its limit and metering period.",
        "docs_url": f"{_DOCS}/entitlements/list-plan-entitlements",
        "columns": _columns(
            environment_id=_ENVIRONMENT_ID,
            plan_id="Identifier of the plan that grants the entitlement.",
            feature_id="Identifier of the entitled feature.",
            plan="The plan that grants the entitlement.",
            feature="The entitled feature.",
            value_type="How the entitlement value is expressed: boolean, numeric, trait or unlimited.",
            value_bool="Boolean entitlement value.",
            value_numeric="Numeric limit of the entitlement.",
            value_trait_id="Identifier of the trait that sets the limit.",
            metric_period="Period over which usage is measured.",
            soft_limit="Whether usage may exceed the limit.",
            price_behavior="How overage is priced.",
        ),
    },
    "company_overrides": {
        "description": "A per-company entitlement override that replaces the plan entitlement for one feature.",
        "docs_url": f"{_DOCS}/entitlements/list-company-overrides",
        "columns": _columns(
            environment_id=_ENVIRONMENT_ID,
            company_id="Identifier of the company the override applies to.",
            feature_id="Identifier of the overridden feature.",
            company="The company the override applies to.",
            feature="The overridden feature.",
            value_type="How the override value is expressed: boolean, numeric, trait or unlimited.",
            value_bool="Boolean override value.",
            value_numeric="Numeric limit set by the override.",
            metric_period="Period over which usage is measured.",
            expiration_date="Time the override stops applying.",
            notes="Free-text notes on the override.",
        ),
    },
    "billing_customers": {
        "description": "A customer synced from the billing provider, with its subscriptions.",
        "docs_url": f"{_DOCS}/billing/list-customers-with-subscriptions",
        "columns": {
            "id": "Unique identifier for the billing customer.",
            "company_id": "Identifier of the Schematic company linked to the customer.",
            "external_id": "Identifier of the customer in the billing provider.",
            "provider_type": "Billing provider the customer comes from, such as Stripe.",
            "name": "Name of the customer.",
            "email": "Email address of the customer.",
            "subscriptions": "Subscriptions held by the customer.",
            "deleted_at": "Time the customer was deleted in the billing provider.",
            "updated_at": "Time at which the customer was last updated.",
        },
    },
    "billing_products": {
        "description": "A product synced from the billing provider.",
        "docs_url": f"{_DOCS}/billing/list-billing-products",
        "columns": _columns(
            with_id=False,
            environment_id=_ENVIRONMENT_ID,
            product_id="Unique identifier for the billing product.",
            external_id="Identifier of the product in the billing provider.",
            provider_type="Billing provider the product comes from, such as Stripe.",
            name="Name of the product.",
            currency="Currency of the product's default price.",
            price="Default price in the smallest currency unit.",
            price_decimal="Default price as a decimal string.",
            is_active="Whether the product is active in the billing provider.",
            prices="Prices defined for the product.",
            subscription_count="Number of subscriptions that include the product.",
        ),
    },
    "billing_prices": {
        "description": "A price synced from the billing provider.",
        "docs_url": f"{_DOCS}/billing/list-billing-prices",
        "columns": _columns(
            price_id="Identifier of the price.",
            price_external_id="Identifier of the price in the billing provider.",
            product_id="Identifier of the billing product the price belongs to.",
            product_external_id="Identifier of the product in the billing provider.",
            product_name="Name of the billing product.",
            provider_type="Billing provider the price comes from, such as Stripe.",
            currency="Currency of the price.",
            price="Amount in the smallest currency unit.",
            price_decimal="Amount as a decimal string.",
            interval="Billing interval, such as month or year.",
            interval_count="Number of intervals between charges.",
            usage_type="Whether the price is licensed or metered.",
            billing_scheme="Whether the price is per unit or tiered.",
            tiers_mode="How tiers apply when the price is tiered.",
            is_active="Whether the price is active in the billing provider.",
            meter_id="Identifier of the meter for a metered price.",
        ),
    },
    "billing_coupons": {
        "description": "A coupon synced from the billing provider.",
        "docs_url": f"{_DOCS}/billing/list-coupons",
        "columns": {
            "id": "Unique identifier for the coupon.",
            "external_id": "Identifier of the coupon in the billing provider.",
            "provider_type": "Billing provider the coupon comes from, such as Stripe.",
            "name": "Name of the coupon.",
            "amount_off": "Fixed discount in the smallest currency unit.",
            "percent_off": "Percentage discount.",
            "currency": "Currency of a fixed discount.",
            "duration": "How long the coupon applies: once, repeating or forever.",
            "duration_in_months": "Number of months a repeating coupon applies.",
            "max_redemptions": "Maximum number of times the coupon can be redeemed.",
            "times_redeemed": "Number of times the coupon has been redeemed.",
            "is_active": "Whether the coupon is active.",
            "valid_from": "Time the coupon becomes valid.",
            "valid_until": "Time the coupon expires.",
        },
    },
    "billing_meters": {
        "description": "A usage meter synced from the billing provider.",
        "docs_url": f"{_DOCS}/billing/list-meters",
        "columns": {
            "id": "Unique identifier for the meter.",
            "provider_type": "Billing provider the meter comes from, such as Stripe.",
            "event_name": "Name of the billing event the meter counts.",
            "event_payload_key": "Payload key the meter aggregates.",
            "external_price_id": "Identifier of the billing price attached to the meter.",
        },
    },
}
