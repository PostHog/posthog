"""Canonical, documentation-sourced descriptions for Picqer endpoints and columns.

Sourced from the official Picqer API reference (https://picqer.com/en/api). Keyed by the endpoint
names in `settings.py` `PICQER_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
Picqer table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://picqer.com/en/api"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "orders": {
        "description": "A sales order in Picqer, containing the products a customer ordered and their fulfilment state.",
        "docs_url": f"{_DOCS}/orders",
        "columns": {
            "idorder": "Unique Picqer reference for the order.",
            "orderid": "Per-account order number.",
            "idcustomer": "Reference to the customer the order belongs to.",
            "reference": "External reference for the order.",
            "status": "Current status of the order (e.g. concept, expected, processing, completed, cancelled).",
            "created": "Datetime the order was created.",
            "updated": "Datetime the order was last changed.",
        },
    },
    "picklists": {
        "description": "A picklist — the set of products to pick from stock to fulfil one or more orders.",
        "docs_url": f"{_DOCS}/picklists",
        "columns": {
            "idpicklist": "Unique Picqer reference for the picklist.",
            "picklistid": "Per-account picklist number.",
            "idorder": "Reference to the order this picklist fulfils.",
            "idwarehouse": "Reference to the warehouse the picklist is picked from.",
            "status": "Current status of the picklist.",
            "created": "Datetime the picklist was created.",
        },
    },
    "purchaseorders": {
        "description": "A purchase order sent to a supplier to replenish stock.",
        "docs_url": f"{_DOCS}/purchaseorders",
        "columns": {
            "idpurchaseorder": "Unique Picqer reference for the purchase order.",
            "purchaseorderid": "Per-account purchase order number.",
            "idsupplier": "Reference to the supplier the purchase order is placed with.",
            "idwarehouse": "Reference to the warehouse the goods are received into.",
            "status": "Current status of the purchase order.",
            "created": "Datetime the purchase order was created.",
            "updated": "Datetime the purchase order was last changed.",
        },
    },
    "receipts": {
        "description": "A receipt recording the goods received against a purchase order.",
        "docs_url": f"{_DOCS}/receipts",
        "columns": {
            "idreceipt": "Unique Picqer reference for the receipt.",
            "receiptid": "Per-account receipt number.",
            "idpurchaseorder": "Reference to the purchase order the receipt belongs to.",
            "idwarehouse": "Reference to the warehouse the goods were received into.",
            "status": "Current status of the receipt.",
            "created": "Datetime the receipt was created.",
        },
    },
    "returns": {
        "description": "A return (RMA) of products a customer sent back.",
        "docs_url": f"{_DOCS}/returns",
        "columns": {
            "idreturn": "Unique Picqer reference for the return.",
            "returnid": "Per-account return number.",
            "idcustomer": "Reference to the customer the return belongs to.",
            "status": "Current status of the return.",
            "created_at": "Datetime the return was created.",
            "updated_at": "Datetime the return was last changed.",
        },
    },
    "products": {
        "description": "A product in the Picqer catalog, including its stock and supplier information.",
        "docs_url": f"{_DOCS}/products",
        "columns": {
            "idproduct": "Unique Picqer reference for the product.",
            "productcode": "The product's SKU / product code.",
            "name": "The product's name.",
            "price": "Sales price of the product.",
            "fixedstockprice": "Fixed stock price of the product.",
            "idsupplier": "Reference to the product's default supplier.",
            "created": "Datetime the product was created.",
            "updated": "Datetime the product was last changed.",
        },
    },
    "customers": {
        "description": "A customer record in Picqer.",
        "docs_url": f"{_DOCS}/customers",
        "columns": {
            "idcustomer": "Unique Picqer reference for the customer.",
            "customerid": "Per-account customer number.",
            "name": "The customer's name.",
            "contactname": "Name of the primary contact.",
            "emailaddress": "The customer's email address.",
        },
    },
    "suppliers": {
        "description": "A supplier products can be purchased from.",
        "docs_url": f"{_DOCS}/suppliers",
        "columns": {
            "idsupplier": "Unique Picqer reference for the supplier.",
            "name": "The supplier's name.",
        },
    },
    "warehouses": {
        "description": "A warehouse where stock is held and orders are fulfilled.",
        "docs_url": f"{_DOCS}/warehouses",
        "columns": {
            "idwarehouse": "Unique Picqer reference for the warehouse.",
            "name": "The warehouse's name.",
            "accept_orders": "Whether the warehouse accepts new orders.",
            "priority": "Priority used when allocating stock across warehouses.",
            "active": "Whether the warehouse is active.",
        },
    },
    "locations": {
        "description": "A physical stock location within a warehouse.",
        "docs_url": f"{_DOCS}/locations",
        "columns": {
            "idlocation": "Unique Picqer reference for the location.",
            "name": "The location's name / code.",
            "idwarehouse": "Reference to the warehouse the location belongs to.",
        },
    },
    "users": {
        "description": "A user account in the Picqer application.",
        "docs_url": f"{_DOCS}/users",
        "columns": {
            "iduser": "Unique Picqer reference for the user.",
            "firstname": "The user's first name.",
            "lastname": "The user's last name.",
            "emailaddress": "The user's email address.",
            "active": "Whether the user account is active.",
        },
    },
    "vatgroups": {
        "description": "A VAT (tax) group applied to products and orders.",
        "docs_url": f"{_DOCS}/vatgroups",
        "columns": {
            "idvatgroup": "Unique Picqer reference for the VAT group.",
            "name": "The VAT group's name.",
            "percentage": "The VAT percentage.",
        },
    },
    "tags": {
        "description": "A tag that can be attached to orders, customers, and other records.",
        "docs_url": f"{_DOCS}/tags",
        "columns": {
            "idtag": "Unique Picqer reference for the tag.",
            "title": "The tag's title.",
            "color": "The tag's display color.",
        },
    },
}
