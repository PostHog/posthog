from .fragments import COUNT_FRAGMENT

CATALOGS_SORTKEY = "ID"

CATALOGS_QUERY = f"""
query PaginatedCatalogs($pageSize: Int!, $cursor: String, $query: String) {{
    catalogs(
        first: $pageSize, after: $cursor, sortKey: {CATALOGS_SORTKEY},
        query: $query
    ) {{
        nodes {{
            id
            operations {{
                id
                processedRowCount
                status
            }}
            priceList {{
                id
                name
            }}
            publication {{
                id
            }}
            status
            title
            ... on AppCatalog {{
                apps(first: 250) {{
                    nodes {{
                        id
                        title
                    }}
                }}
            }}
            ... on CompanyLocationCatalog {{
                companyLocations(first: 250) {{
                    nodes {{
                        id
                        name
                    }}
                }}
                companyLocationsCount {COUNT_FRAGMENT}
            }}
            ... on MarketCatalog {{
                markets(first: 250) {{
                    nodes {{
                        id
                        name
                    }}
                }}
                marketsCount {COUNT_FRAGMENT}
            }}
        }}
        pageInfo {{
            hasNextPage
            endCursor
        }}
    }}
}}"""
