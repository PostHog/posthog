ARTICLES_SORTKEY = "UPDATED_AT"

ARTICLES_QUERY = f"""
query PaginatedArticles($pageSize: Int!, $cursor: String, $query: String) {{
    articles(
        first: $pageSize, after: $cursor, sortKey: {ARTICLES_SORTKEY},
        query: $query
    ) {{
        nodes {{
            author {{
                name
            }}
            blog {{
                handle
                id
                tags
                title
            }}
            body
            commentsCount(limit: null) {{
                count
            }}
            createdAt
            handle
            id
            isPublished
            publishedAt
            summary
            tags
            templateSuffix
            title
            updatedAt
        }}
        pageInfo {{
            hasNextPage
            endCursor
        }}
    }}
}}"""
