from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Printify API docs (https://developers.printify.com).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "shops": {
        "description": "A sales channel (shop) connected to your Printify account, e.g. a Shopify or Etsy store.",
        "docs_url": "https://developers.printify.com/#shops",
        "columns": {
            "id": "The unique ID of the shop.",
            "title": "The shop's display name.",
            "sales_channel": "The sales channel platform the shop is connected to (e.g. shopify, etsy).",
        },
    },
    "products": {
        "description": "A product created in a Printify shop, including its variants, print areas, and publishing state.",
        "docs_url": "https://developers.printify.com/#products",
        "columns": {
            "id": "The unique ID of the product.",
            "shop_id": "The ID of the shop the product belongs to.",
            "title": "The product's name.",
            "description": "The product's description.",
            "tags": "Tags attached to the product.",
            "options": "Purchase options (e.g. color, size) and their values.",
            "variants": "All variant combinations of the product with pricing and availability.",
            "images": "Mock-up images of the product.",
            "created_at": "When the product was created.",
            "updated_at": "When the product was last updated.",
            "visible": "Whether the product is visible in the connected sales channel.",
            "blueprint_id": "The ID of the catalog blueprint the product is based on.",
            "print_provider_id": "The ID of the print provider fulfilling the product.",
            "print_areas": "The design placeholders and artwork placed on the product.",
            "is_locked": "Whether the product is locked because it has pending orders.",
        },
    },
    "orders": {
        "description": "An order submitted to Printify for fulfillment, including line items, shipping, and status.",
        "docs_url": "https://developers.printify.com/#orders",
        "columns": {
            "id": "The unique ID of the order.",
            "shop_id": "The ID of the shop the order belongs to.",
            "address_to": "The delivery address of the order.",
            "line_items": "The products and variants included in the order.",
            "metadata": "Order metadata, including the sales-channel order id and shop order number.",
            "total_price": "The total price of the order, in cents.",
            "total_shipping": "The total shipping cost of the order, in cents.",
            "total_tax": "The total tax on the order, in cents.",
            "status": "The production status of the order (e.g. pending, in-production, fulfilled).",
            "shipping_method": "The ID of the shipping method selected for the order.",
            "shipments": "Carrier and tracking information for the order's shipments.",
            "created_at": "When the order was created.",
            "sent_to_production_at": "When the order was sent to production.",
            "fulfilled_at": "When the order was fulfilled.",
        },
    },
    "uploads": {
        "description": "An artwork image uploaded to your Printify media library.",
        "docs_url": "https://developers.printify.com/#uploads",
        "columns": {
            "id": "The unique ID of the uploaded image.",
            "file_name": "The file name of the uploaded image.",
            "height": "The image height in pixels.",
            "width": "The image width in pixels.",
            "size": "The file size in bytes.",
            "mime_type": "The MIME type of the image file.",
            "preview_url": "A URL to preview the image.",
            "upload_time": "When the image was uploaded.",
        },
    },
    "webhooks": {
        "description": "A webhook subscription registered on a Printify shop.",
        "docs_url": "https://developers.printify.com/#webhooks",
        "columns": {
            "id": "The unique ID of the webhook.",
            "shop_id": "The ID of the shop the webhook is registered on.",
            "topic": "The event topic the webhook is subscribed to (e.g. order:created).",
            "url": "The URL webhook events are delivered to.",
        },
    },
    "blueprints": {
        "description": "A catalog blueprint — a base product (e.g. a t-shirt model) that shop products are built from.",
        "docs_url": "https://developers.printify.com/#catalog",
        "columns": {
            "id": "The unique ID of the blueprint.",
            "title": "The blueprint's name.",
            "description": "The blueprint's description.",
            "brand": "The brand of the underlying garment or product.",
            "model": "The manufacturer model of the underlying garment or product.",
            "images": "Preview images of the blueprint.",
        },
    },
    "print_providers": {
        "description": "A print provider available in the Printify catalog to fulfill products.",
        "docs_url": "https://developers.printify.com/#catalog",
        "columns": {
            "id": "The unique ID of the print provider.",
            "title": "The print provider's name.",
            "location": "The print provider's location address.",
        },
    },
    "blueprint_print_providers": {
        "description": "Which print providers fulfill each catalog blueprint, with their decoration methods and production time.",
        "docs_url": "https://developers.printify.com/#catalog",
        "columns": {
            "id": "The ID of the print provider.",
            "blueprint_id": "The ID of the catalog blueprint the print provider fulfills.",
            "title": "The print provider's name.",
            "decoration_methods": "Decoration methods the print provider offers for the blueprint (e.g. dtg, embroidery).",
            "production_time": "The print provider's average production time in business days.",
        },
    },
    "catalog_variants": {
        "description": "Catalog variants (e.g. color and size combinations) for each blueprint and print provider used by a product in a connected shop. Includes out-of-stock variants.",
        "docs_url": "https://developers.printify.com/#catalog",
        "columns": {
            "id": "The variant ID, referenced as variant_id on product variants and order line items.",
            "blueprint_id": "The ID of the catalog blueprint.",
            "print_provider_id": "The ID of the print provider.",
            "title": "The variant's name (e.g. Heather Grey / XS).",
            "options": "The option values of the variant, such as color and size.",
            "placeholders": "Print areas available on the variant, with their dimensions and decoration method.",
            "decoration_methods": "Decoration methods available for the variant.",
        },
    },
    "catalog_shipping_rates": {
        "description": "Shipping cost and handling time for each variant and destination country, for each blueprint and print provider used by a product in a connected shop.",
        "docs_url": "https://developers.printify.com/#catalog",
        "columns": {
            "blueprint_id": "The ID of the catalog blueprint.",
            "print_provider_id": "The ID of the print provider.",
            "variant_id": "The ID of the catalog variant.",
            "country": "The destination country code, or REST_OF_THE_WORLD.",
            "handling_time": "The print provider's handling time for the blueprint.",
            "first_item": "The shipping cost of the first item, in the smallest currency unit, and its currency.",
            "additional_items": "The shipping cost of each additional item, in the smallest currency unit, and its currency.",
        },
    },
    "product_gpsr": {
        "description": "General Product Safety Regulation (GPSR) information for each product in a connected shop.",
        "docs_url": "https://developers.printify.com/#products",
        "columns": {
            "shop_id": "The ID of the shop the product belongs to.",
            "product_id": "The ID of the product.",
            "sections": "GPSR sections, each with a title (e.g. EU representative, Care instructions) and text.",
        },
    },
}
