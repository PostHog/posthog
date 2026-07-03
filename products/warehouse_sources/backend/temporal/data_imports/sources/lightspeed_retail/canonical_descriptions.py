"""Canonical, documentation-sourced descriptions for Lightspeed Retail (X-Series) endpoints and columns.

Sourced from the official Lightspeed X-Series (formerly Vend) API 2.0 reference
(https://x-series-api.lightspeedhq.com/reference). Keyed by the endpoint names in `settings.py`
`LIGHTSPEED_RETAIL_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced table. Every
record carries a monotonically increasing integer `version` used as the incremental cursor. Columns
absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most X-Series objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "version": "Monotonically increasing version number, incremented whenever the record changes.",
    "deleted_at": "Time at which the object was deleted, if it has been deleted.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sales": {
        "description": "A point-of-sale transaction (a register sale) in Lightspeed Retail.",
        "docs_url": "https://x-series-api.lightspeedhq.com/reference/listsales",
        "columns": _columns(
            outlet_id="ID of the outlet where the sale took place.",
            register_id="ID of the register the sale was made on.",
            user_id="ID of the user (cashier) who made the sale.",
            customer_id="ID of the customer the sale is associated with, if any.",
            status="Status of the sale (e.g. CLOSED, OPEN, ONACCOUNT, LAYBY, VOIDED).",
            total_price="Total price of the sale excluding tax.",
            total_tax="Total tax charged on the sale.",
            note="Free-form note attached to the sale.",
            line_items="The products sold in this transaction.",
            payments="Payments applied to the sale.",
            sale_date="Date and time the sale occurred.",
            created_at="Time at which the sale record was created.",
            updated_at="Time at which the sale was last updated.",
        ),
    },
    "customers": {
        "description": "A customer record in Lightspeed Retail.",
        "docs_url": "https://x-series-api.lightspeedhq.com/reference/listcustomers",
        "columns": _columns(
            customer_code="Your own code identifying the customer.",
            first_name="The customer's first name.",
            last_name="The customer's last name.",
            company_name="The customer's company name, if any.",
            email="The customer's email address.",
            phone="The customer's phone number.",
            mobile="The customer's mobile number.",
            customer_group_id="ID of the customer group the customer belongs to.",
            balance="The customer's outstanding account balance.",
            year_to_date="Total the customer has spent year to date.",
            created_at="Time at which the customer was created.",
            updated_at="Time at which the customer was last updated.",
        ),
    },
    "products": {
        "description": "A product in the Lightspeed Retail catalog.",
        "docs_url": "https://x-series-api.lightspeedhq.com/reference/listproducts",
        "columns": _columns(
            name="The product's name.",
            handle="The product's URL-friendly handle.",
            sku="The product's stock-keeping unit (SKU).",
            description="Description of the product.",
            supply_price="Cost price paid to acquire the product.",
            brand_id="ID of the product's brand.",
            supplier_id="ID of the product's supplier.",
            product_type_id="ID of the product's type.",
            active="Whether the product is active.",
            is_composite="Whether the product is a composite (bundle) of other products.",
            has_variants="Whether the product has variants.",
            variant_parent_id="ID of the parent product if this is a variant.",
            created_at="Time at which the product was created.",
            updated_at="Time at which the product was last updated.",
        ),
    },
    "inventory": {
        "description": "Per-outlet stock levels for a product in Lightspeed Retail.",
        "docs_url": "https://x-series-api.lightspeedhq.com/reference/listinventory",
        "columns": _columns(
            product_id="ID of the product this inventory record is for.",
            outlet_id="ID of the outlet the stock is held at.",
            current_amount="Current quantity on hand at the outlet.",
            reorder_point="Stock level at which the product should be reordered.",
            reorder_amount="Quantity to reorder when the reorder point is reached.",
        ),
    },
    "outlets": {
        "description": "A physical store location (outlet) in Lightspeed Retail.",
        "docs_url": "https://x-series-api.lightspeedhq.com/reference/listoutlets",
        "columns": _columns(
            name="The outlet's name.",
            time_zone="The outlet's time zone.",
            currency="The currency the outlet trades in.",
            physical_address_1="First line of the outlet's physical address.",
            physical_city="City of the outlet's physical address.",
            physical_country_id="Country of the outlet's physical address.",
        ),
    },
    "registers": {
        "description": "A point-of-sale register (till) at an outlet in Lightspeed Retail.",
        "docs_url": "https://x-series-api.lightspeedhq.com/reference/listregisters",
        "columns": _columns(
            name="The register's name.",
            outlet_id="ID of the outlet the register belongs to.",
            is_open="Whether the register currently has an open session.",
        ),
    },
    "users": {
        "description": "A staff user account in Lightspeed Retail.",
        "docs_url": "https://x-series-api.lightspeedhq.com/reference/listusers",
        "columns": _columns(
            username="The user's login username.",
            display_name="The user's display name.",
            email="The user's email address.",
            account_type="The user's account type / permission level.",
            target_daily="The user's daily sales target, if set.",
            created_at="Time at which the user was created.",
            updated_at="Time at which the user was last updated.",
        ),
    },
    "taxes": {
        "description": "A sales tax rate configured in Lightspeed Retail.",
        "docs_url": "https://x-series-api.lightspeedhq.com/reference/listtaxes",
        "columns": _columns(
            name="The tax's name.",
            rate="The tax rate, as a decimal fraction.",
            is_default="Whether this is the default tax applied to sales.",
        ),
    },
}
