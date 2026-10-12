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
    "consignments": {
        "description": "An inventory movement in Lightspeed Retail: a supplier order, outlet transfer, stocktake or supplier return.",
        "docs_url": "https://x-series-api.lightspeedhq.com/reference/getconsignments",
        "columns": _columns(
            type="Consignment type: SUPPLIER, OUTLET, STOCKTAKE or RETURN.",
            status="Workflow status of the consignment (e.g. OPEN, SENT, DISPATCHED, RECEIVED, CANCELLED, STOCKTAKE_COMPLETE).",
            name="Consignment name. For orders, this is the note shown in the UI.",
            reference="Order number.",
            outlet_id="ID of the outlet where the stock is received.",
            source_outlet_id="ID of the outlet the stock comes from. Set for stock transfers only.",
            supplier_id="ID of the supplier the stock is ordered from.",
            supplier_invoice="Supplier invoice number.",
            consignment_date="Date the consignment was created.",
            due_at="Date the consignment is due.",
            received_at="Date the consignment was received.",
            total_count_gain="Number of items over the expected level.",
            total_count_loss="Number of items below the expected level.",
            total_cost_gain="Cost of items over the expected level.",
            total_cost_loss="Cost of items below the expected level.",
            created_at="Time at which the consignment was created.",
            updated_at="Time at which the consignment was last updated.",
        ),
    },
    "consignment_products": {
        "description": "A product line item on a Lightspeed Retail consignment, with the expected and received counts.",
        "docs_url": "https://x-series-api.lightspeedhq.com/reference/listproductsbyconsignmentid",
        "columns": {
            "consignment_id": "ID of the consignment the line item belongs to.",
            "product_id": "ID of the product.",
            "product_sku": "SKU of the product.",
            "count": "Expected item count.",
            "received": "Observed (received) item count.",
            "cost": "Cost of the item.",
            "status": "Status of the item: PENDING or SUCCESS.",
            "is_included": "Whether the item was included via a filter. Always true for a full count with no filters.",
            "version": _COMMON_COLUMNS["version"],
            "created_at": "Time at which the line item was created.",
            "updated_at": "Time at which the line item was last updated.",
            "deleted_at": _COMMON_COLUMNS["deleted_at"],
        },
    },
    "suppliers": {
        "description": "A supplier that products are ordered from in Lightspeed Retail.",
        "docs_url": "https://x-series-api.lightspeedhq.com/reference/listsuppliers",
        "columns": _columns(
            name="The supplier's name.",
            description="The supplier's description.",
            source="Origin of the supplier record (e.g. USER, SHOPIFY).",
            default_markup="Default markup for the supplier. Used for record keeping only; it does not affect products.",
            contact="Contact information for the supplier.",
        ),
    },
    "payment_types": {
        "description": "A payment type (e.g. cash, card, gift card) configured in Lightspeed Retail.",
        "docs_url": "https://x-series-api.lightspeedhq.com/reference/listpaymenttypes",
        "columns": _columns(
            name="The payment type's name.",
            type_id="ID of the global payment type. Several payment types can share the same type_id.",
            payment_type="The global payment type this payment type is based on.",
            config="Payment type configuration. The shape varies by payment type.",
            outlet_ids="IDs of the outlets this payment type is associated with.",
            disabled="Whether the payment type is disabled.",
            gateway="Whether the payment type is a payment gateway type.",
            internal="Whether the payment type is for internal use only.",
            is_editable="Whether the payment type can be edited.",
            name_changed_by_user="Whether the retailer customized the name.",
            created_at="Time at which the payment type was created.",
        ),
    },
}
