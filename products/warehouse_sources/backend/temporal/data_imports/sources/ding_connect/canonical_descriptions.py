"""Canonical, documentation-sourced descriptions for DingConnect endpoints and columns.

Sourced from the official DingConnect API V1 reference (https://www.dingconnect.com/Api/Description).
Keyed by the resource names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced DingConnect table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://www.dingconnect.com/Api/Description"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Countries": {
        "description": "A country that DingConnect operates in.",
        "docs_url": _DOCS_URL,
        "columns": {
            "CountryIso": "Alphabetic 2 character ISO 3166-1 country code.",
            "CountryName": "English country name.",
            "InternationalDialingInformation": "Phone number dialing information for the country.",
            "RegionCodes": "Regions supported within the country.",
        },
    },
    "Currencies": {
        "description": "A currency that DingConnect supports.",
        "docs_url": _DOCS_URL,
        "columns": {
            "CurrencyIso": "Alphabetic 3 character ISO 4217 currency code.",
            "CurrencyName": "English currency name.",
        },
    },
    "Regions": {
        "description": "A region within a country. A provider may only service a subset of a country's regions, and a product may only be valid for a subset.",
        "docs_url": _DOCS_URL,
        "columns": {
            "RegionCode": "The region code.",
            "RegionName": "The region name.",
            "CountryIso": "The country ISO code of the region.",
        },
    },
    "Providers": {
        "description": "A mobile operator or biller whose products can be sold through DingConnect.",
        "docs_url": _DOCS_URL,
        "columns": {
            "ProviderCode": "Uniquely identifies a provider.",
            "CountryIso": "The country within which the provider operates.",
            "Name": "The English trading name of the provider.",
            "ShortName": "A shortened name for space-restricted UI elements.",
            "ValidationRegex": "Account numbers must match this regular expression.",
            "CustomerCareNumber": "Customer care number of the provider.",
            "RegionCodes": "Regions supported by the provider within the country.",
        },
    },
    "ProviderStatus": {
        "description": "Whether each provider can currently accept transfers. Providers can be suspended or in an error state.",
        "docs_url": _DOCS_URL,
        "columns": {
            "ProviderCode": "The unique provider code.",
            "IsProcessingTransfers": "Indicates if the provider is processing transfers.",
            "Message": "Details of operator status. Unformatted, non-localized text aimed at the distributor rather than the end customer.",
        },
    },
    "Products": {
        "description": "A sellable product (e.g. a top-up amount) offered by a provider.",
        "docs_url": _DOCS_URL,
        "columns": {
            "ProviderCode": "The provider of the product.",
            "SkuCode": "Unique product identifier, submitted with SendTransfer.",
            "LocalizationKey": "Key to be used in conjunction with GetProductDescriptions.",
            "SettingDefinitions": "Name/value pairs that should be submitted during SendTransfer.",
            "Maximum": "The maximum price that can be sold.",
            "Minimum": "The minimum price that can be sold.",
            "CommissionRate": "The commission rate applied when selling the product.",
            "ProcessingMode": "Transaction processing mode for this product.",
            "RedemptionMechanism": "Whether the customer must act further to redeem the transfer.",
            "Benefits": "The benefit type the transfer grants the target account.",
            "ValidityPeriodIso": "How long the product is valid for after purchase (ISO 8601 duration).",
            "RegionCode": "Region for this product.",
        },
    },
    "ProductDescriptions": {
        "description": "Localized long-form product text, keyed by the LocalizationKey carried on each product. Large blocks of text are CommonMark.",
        "docs_url": _DOCS_URL,
        "columns": {
            "DisplayText": "A short description of the product.",
            "DescriptionMarkdown": "A longer description of the product.",
            "ReadMoreMarkdown": "More detailed information about the product.",
            "LocalizationKey": "The key that links the description back to a product.",
            "LanguageCode": "The language this description is written in. English (en) is always present.",
        },
    },
    "Promotions": {
        "description": "A time-bound promotion applied to a provider's products.",
        "docs_url": _DOCS_URL,
        "columns": {
            "ProviderCode": "The code of the provider that the promotion applies to.",
            "StartUtc": "Start date and time in UTC of the promotion.",
            "EndUtc": "End date and time in UTC of the promotion.",
            "CurrencyIso": "Currency the promotion applies to, usually the same as the provider.",
            "ValidityPeriodIso": "Validity of the promotion (ISO 8601 duration).",
            "MinimumSendAmount": "Minimum amount to be sent to qualify, in the distributor's currency.",
            "LocalizationKey": "Key to be used in conjunction with GetPromotionDescriptions.",
        },
    },
    "Balance": {
        "description": "The distributor's current account balance.",
        "docs_url": _DOCS_URL,
        "columns": {
            "Balance": "The distributor's balance.",
            "CurrencyIso": "ISO 4217 currency code of the balance.",
        },
    },
    "ErrorCodeDescriptions": {
        "description": "Human readable descriptions for the error codes returned in the ErrorCodes array of an API response. Aimed at the distributor rather than the end customer.",
        "docs_url": _DOCS_URL,
        "columns": {
            "Code": "The identifying error code that was returned in the response.",
            "Message": "Error description.",
        },
    },
    "TransferRecords": {
        "description": "A record of a transfer (top-up) that was sent through DingConnect. Only retained upstream for ~2 months.",
        "docs_url": _DOCS_URL,
        "columns": {
            "TransferRef": "The unique identifier for the transfer within DingConnect's system.",
            "DistributorRef": "The distributor's own identifier for the transfer.",
            "SkuCode": "The unique product SkuCode that was transferred.",
            "Price": "The resulting price of the transfer.",
            "CommissionApplied": "The commission earned for selling this transfer.",
            "StartedUtc": "The UTC datetime when processing the transfer was started.",
            "CompletedUtc": "The UTC datetime that the transfer was recorded as completed.",
            "ProcessingState": "The current state of the transfer (e.g. Submitted, Processing, Complete, Failed, Cancelled).",
            "ReceiptText": "Provider-specific receipt text for the transfer.",
            "ReceiptParams": "Name/value pairs of data contained in the receipt text.",
            "AccountNumber": "The account number targeted in the transfer.",
        },
    },
}
