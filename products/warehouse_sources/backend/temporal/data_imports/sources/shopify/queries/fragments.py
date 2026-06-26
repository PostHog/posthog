ID_NAME_FRAGMENT = """{
    id
    name
}"""

ID_NAME_CREATED_FRAGMENT = """{
    id
    name
    createdAt
}"""

ID_NAME_CREATED_UPDATED_FRAGMENT = """{
    id
    name
    createdAt
    updatedAt
}"""

ID_TITLE_CREATED_UPDATED_FRAGMENT = """{
    id
    title
    createdAt
    updatedAt
}"""

NODE_CONNECTION_ID_FRAGMENT = """{
    nodes {
        id
    }
}"""

COUNT_FRAGMENT = """{
    count
    precision
}"""

EMAIL_ADDRESS_FRAGMENT = """{
    emailAddress
    marketingOptInLevel
    marketingState
    marketingUpdatedAt
    openTrackingLevel
    validFormat
}"""

FULFILLMENT_FRAGMENT = """{
    id
    name
    createdAt
    updatedAt
}"""

KV_FRAGMENT = """{
    key
    value
}"""


MAILING_ADDRESS_FRAGMENT = """{
    address1
    address2
    city
    company
    coordinatesValidated
    country
    countryCodeV2
    firstName
    formatted
    formattedArea
    id
    lastName
    latitude
    longitude
    name
    phone
    province
    provinceCode
    timeZone
    validationResultSummary
    zip
}"""

METAFIELD_CONNECTIONS_FRAGMENT = """{
    nodes {
        compareDigest
        createdAt
        id
        jsonValue
        key
        namespace
        type
        updatedAt
        value
    }
}"""


MONEY_V2_FRAGMENT = """{
    amount
    currencyCode
}"""

MONEY_BAG_FRAGMENT = f"""{{
    presentmentMoney {MONEY_V2_FRAGMENT}
    shopMoney {MONEY_V2_FRAGMENT}
}}"""

PHONE_NUMBER_FRAGMENT = """{
    marketingCollectedFrom
    marketingOptInLevel
    marketingState
    marketingUpdatedAt
    phoneNumber
}"""

TAX_LINES_FRAGMENT = f"""{{
    priceSet {MONEY_BAG_FRAGMENT}
    rate
    ratePercentage
    source
    title
}}"""

LINE_ITEM_FRAGMENT = f"""{{
    id
    currentQuantity
    customAttributes {KV_FRAGMENT}
    discountedTotalSet {MONEY_BAG_FRAGMENT}
    discountedUnitPriceSet {MONEY_BAG_FRAGMENT}
    isGiftCard
    name
    nonFulfillableQuantity
    originalTotalSet {MONEY_BAG_FRAGMENT}
    originalUnitPriceSet {MONEY_BAG_FRAGMENT}
    product {{
        id
    }}
    quantity
    refundableQuantity
    requiresShipping
    restockable
    sku
    taxable
    taxLines(first: 250) {TAX_LINES_FRAGMENT}
    title
    totalDiscountSet {MONEY_BAG_FRAGMENT}
    unfulfilledDiscountedTotalSet {MONEY_BAG_FRAGMENT}
    unfulfilledOriginalTotalSet {MONEY_BAG_FRAGMENT}
    unfulfilledQuantity
    variant {{
        id
    }}
    vendor
}}"""

CUSTOMER_FRAGMENT = f"""{{
    addresses {MAILING_ADDRESS_FRAGMENT}
    amountSpent {MONEY_V2_FRAGMENT}
    createdAt
    defaultAddress {MAILING_ADDRESS_FRAGMENT}
    defaultEmailAddress {EMAIL_ADDRESS_FRAGMENT}
    defaultPhoneNumber {PHONE_NUMBER_FRAGMENT}
    displayName
    firstName
    id
    lastName
    lastOrder {ID_NAME_FRAGMENT}
    lifetimeDuration
    locale
    multipassIdentifier
    note
    numberOfOrders
    productSubscriberStatus
    state
    statistics {{
        predictedSpendTier
        rfmGroup
    }}
    tags
    taxExempt
    taxExemptions
    updatedAt
    verifiedEmail
}}"""
