from .fragments import (
    EMAIL_ADDRESS_FRAGMENT,
    MAILING_ADDRESS_FRAGMENT,
    METAFIELD_CONNECTIONS_FRAGMENT,
    MONEY_V2_FRAGMENT,
    PHONE_NUMBER_FRAGMENT,
)

CUSTOMERS_SORTKEY = "UPDATED_AT"

# NOTE: 250 is the max allowable query size for nested connections
CUSTOMERS_QUERY = f"""
query PaginatedCustomers($pageSize: Int!, $cursor: String, $query: String) {{
    customers(
        first: $pageSize, after: $cursor, sortKey: {CUSTOMERS_SORTKEY},
        query: $query
    ) {{
        nodes {{
            id
            displayName
            firstName
            lastName
            createdAt
            updatedAt
            locale
            note
            state
            verifiedEmail
            taxExempt
            taxExemptions
            multipassIdentifier
            dataSaleOptOut
            lifetimeDuration
            productSubscriberStatus
            numberOfOrders
            canDelete
            tags
            amountSpent {MONEY_V2_FRAGMENT}
            defaultEmailAddress {EMAIL_ADDRESS_FRAGMENT}
            defaultPhoneNumber {PHONE_NUMBER_FRAGMENT}
            addresses {MAILING_ADDRESS_FRAGMENT}
            defaultAddress {MAILING_ADDRESS_FRAGMENT}
            lastOrder {{
                id
                name
                createdAt
            }}
            statistics {{
                predictedSpendTier
                rfmGroup
            }}
            metafields(first: 250) {METAFIELD_CONNECTIONS_FRAGMENT}
        }}
        pageInfo {{
            hasNextPage
            endCursor
        }}
    }}
}}"""
