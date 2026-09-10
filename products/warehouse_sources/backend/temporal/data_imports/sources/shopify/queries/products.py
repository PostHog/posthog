from .fragments import COUNT_FRAGMENT, METAFIELD_CONNECTIONS_FRAGMENT, MONEY_V2_FRAGMENT

PRODUCTS_SORTKEY = "UPDATED_AT"

# NOTE: 250 is the max allowable query size for nested connections
PRODUCTS_QUERY = f"""
query PaginatedProducts($pageSize: Int!, $cursor: String, $query: String) {{
    products(
        first: $pageSize, after: $cursor, sortKey: {PRODUCTS_SORTKEY},
        query: $query
    ) {{
        nodes {{
            id
            compareAtPriceRange {{
                minVariantCompareAtPrice {MONEY_V2_FRAGMENT}
                maxVariantCompareAtPrice {MONEY_V2_FRAGMENT}
            }}
            createdAt
            description
            descriptionHtml
            giftCardTemplateSuffix
            handle
            hasOnlyDefaultVariant
            hasOutOfStockVariants
            isGiftCard
            metafields(first: 250) {METAFIELD_CONNECTIONS_FRAGMENT}
            onlineStoreUrl
            options(first: 250) {{
                id
                name
                position
                values
            }}
            priceRangeV2 {{
                minVariantPrice {MONEY_V2_FRAGMENT}
                maxVariantPrice {MONEY_V2_FRAGMENT}
            }}
            productType
            publishedAt
            requiresSellingPlan
            seo {{
                title
                description
            }}
            status
            tags
            templateSuffix
            title
            totalInventory
            tracksInventory
            updatedAt
            variantsCount {COUNT_FRAGMENT}
            variants(first: 250) {{
                nodes {{
                    id
                    availableForSale
                    barcode
                    compareAtPrice
                    createdAt
                    displayName
                    inventoryPolicy
                    inventoryQuantity
                    position
                    price
                    selectedOptions {{
                        name
                        value
                    }}
                    sellableOnlineQuantity
                    showUnitPrice
                    sku
                    taxable
                    title
                    unitPrice {MONEY_V2_FRAGMENT}
                    updatedAt
                }}
            }}
            vendor
        }}
        pageInfo {{
            hasNextPage
            endCursor
        }}
    }}
}}"""
