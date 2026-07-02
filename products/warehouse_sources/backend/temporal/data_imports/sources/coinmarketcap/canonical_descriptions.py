from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the official CoinMarketCap API docs (https://coinmarketcap.com/api/documentation/v1/).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "cryptocurrency_map": {
        "description": "Mapping of all cryptocurrencies tracked by CoinMarketCap to their CoinMarketCap ID.",
        "docs_url": "https://coinmarketcap.com/api/documentation/v1/#operation/getV1CryptocurrencyMap",
        "columns": {
            "id": "The unique CoinMarketCap ID for this cryptocurrency.",
            "name": "The name of this cryptocurrency.",
            "symbol": "The ticker symbol for this cryptocurrency.",
            "slug": "The web URL friendly shorthand version of this cryptocurrency name.",
            "rank": "The rank of this cryptocurrency by market capitalization.",
            "is_active": "1 if this cryptocurrency has at least one active market currently being tracked, otherwise 0.",
            "first_historical_data": "Timestamp (ISO 8601) of the earliest market data record available for this cryptocurrency.",
            "last_historical_data": "Timestamp (ISO 8601) of the latest market data record available for this cryptocurrency.",
            "platform": "Metadata about the parent cryptocurrency platform this is a token on, if any.",
        },
    },
    "listings_latest": {
        "description": "Latest market data (price, market cap, volume, supply) for all active cryptocurrencies, ranked.",
        "docs_url": "https://coinmarketcap.com/api/documentation/v1/#operation/getV1CryptocurrencyListingsLatest",
        "columns": {
            "id": "The unique CoinMarketCap ID for this cryptocurrency.",
            "name": "The name of this cryptocurrency.",
            "symbol": "The ticker symbol for this cryptocurrency.",
            "slug": "The web URL friendly shorthand version of this cryptocurrency name.",
            "cmc_rank": "The cryptocurrency's CoinMarketCap rank by market cap.",
            "num_market_pairs": "The number of active trading pairs available for this cryptocurrency across exchanges.",
            "circulating_supply": "The approximate number of coins circulating in the market.",
            "total_supply": "The approximate total amount of coins in existence right now (minus any coins verifiably burned).",
            "max_supply": "The expected maximum limit of coins ever to be available for this cryptocurrency.",
            "date_added": "Timestamp (ISO 8601) of when this cryptocurrency was added to CoinMarketCap.",
            "tags": "Tags associated with this cryptocurrency.",
            "platform": "Metadata about the parent cryptocurrency platform this is a token on, if any.",
            "last_updated": "Timestamp (ISO 8601) of when the market data for this cryptocurrency was last updated.",
            "quote": "Market quote in each currency conversion requested (e.g. USD): price, volume, market cap, and percent changes.",
        },
    },
    "categories": {
        "description": "All cryptocurrency categories (e.g. DeFi, NFTs) with aggregate market data.",
        "docs_url": "https://coinmarketcap.com/api/documentation/v1/#operation/getV1CryptocurrencyCategories",
        "columns": {
            "id": "The unique ID of this cryptocurrency category.",
            "name": "The name of this cryptocurrency category.",
            "title": "The title of this cryptocurrency category.",
            "description": "The description of this cryptocurrency category.",
            "num_tokens": "The number of tokens in this cryptocurrency category.",
            "avg_price_change": "The average price change of all tokens in this category over 24 hours.",
            "market_cap": "The market cap of all tokens within this category.",
            "market_cap_change": "The market cap change of all tokens in this category over 24 hours.",
            "volume": "The 24 hour trading volume of all tokens within this category.",
            "volume_change": "The 24 hour trading volume change of all tokens in this category.",
            "last_updated": "Timestamp (ISO 8601) of when this category was last updated.",
        },
    },
    "fiat_map": {
        "description": "All fiat currencies supported by CoinMarketCap for quote conversions.",
        "docs_url": "https://coinmarketcap.com/api/documentation/v1/#operation/getV1FiatMap",
        "columns": {
            "id": "The unique CoinMarketCap ID for this fiat currency.",
            "name": "The name of this fiat currency.",
            "sign": "The currency sign for this fiat currency.",
            "symbol": "The ticker symbol for this fiat currency.",
        },
    },
    "exchange_map": {
        "description": "Mapping of all exchanges tracked by CoinMarketCap to their CoinMarketCap exchange ID.",
        "docs_url": "https://coinmarketcap.com/api/documentation/v1/#operation/getV1ExchangeMap",
        "columns": {
            "id": "The unique CoinMarketCap ID for this exchange.",
            "name": "The name of this exchange.",
            "slug": "The web URL friendly shorthand version of this exchange name.",
            "is_active": "1 if this exchange is still being actively tracked and updated, otherwise 0.",
            "is_listed": "1 if this exchange is listed (ranked) by CoinMarketCap, otherwise 0.",
            "is_redistributable": "1 if this exchange's data is available for redistribution per CoinMarketCap licensing, otherwise 0.",
            "first_historical_data": "Timestamp (ISO 8601) of the earliest market data record available for this exchange.",
            "last_historical_data": "Timestamp (ISO 8601) of the latest market data record available for this exchange.",
        },
    },
}
