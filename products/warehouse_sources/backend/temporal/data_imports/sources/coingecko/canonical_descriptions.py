from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the public CoinGecko API v3 docs (https://docs.coingecko.com/reference).
# Partial coverage is fine — anything not described here falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "coins_list": {
        "description": "Every coin tracked by CoinGecko, as id/symbol/name reference rows.",
        "docs_url": "https://docs.coingecko.com/reference/coins-list",
        "columns": {
            "id": "CoinGecko coin id (used as the path parameter on per-coin endpoints).",
            "symbol": "Ticker symbol (not unique across coins).",
            "name": "Display name of the coin.",
        },
    },
    "coins_markets": {
        "description": "Current market snapshot per coin in USD: price, market cap, volume, supply, and all-time high/low.",
        "docs_url": "https://docs.coingecko.com/reference/coins-markets",
        "columns": {
            "id": "CoinGecko coin id.",
            "symbol": "Ticker symbol.",
            "name": "Display name of the coin.",
            "current_price": "Latest price in USD.",
            "market_cap": "Market capitalization in USD.",
            "market_cap_rank": "Rank of the coin by market capitalization.",
            "fully_diluted_valuation": "Market cap if the max supply were in circulation, in USD.",
            "total_volume": "Trading volume over the last 24 hours in USD.",
            "high_24h": "Highest price in the last 24 hours, in USD.",
            "low_24h": "Lowest price in the last 24 hours, in USD.",
            "price_change_24h": "Absolute price change over the last 24 hours, in USD.",
            "price_change_percentage_24h": "Percentage price change over the last 24 hours.",
            "circulating_supply": "Number of coins currently in circulation.",
            "total_supply": "Total number of coins that exist (excluding burned).",
            "max_supply": "Maximum number of coins that will ever exist (null if uncapped).",
            "ath": "All-time-high price in USD.",
            "ath_date": "Timestamp of the all-time-high price.",
            "atl": "All-time-low price in USD.",
            "atl_date": "Timestamp of the all-time-low price.",
            "last_updated": "Timestamp CoinGecko last refreshed this row.",
        },
    },
    "coins_categories": {
        "description": "Aggregated market data per coin category (market cap, 24h volume, top coins).",
        "docs_url": "https://docs.coingecko.com/reference/coins-categories",
        "columns": {
            "id": "Category id.",
            "name": "Category display name.",
            "market_cap": "Total market capitalization of the category in USD.",
            "market_cap_change_24h": "24-hour percentage change in the category's market cap.",
            "volume_24h": "Total 24-hour trading volume of the category in USD.",
            "top_3_coins_id": "CoinGecko ids of the category's top three coins by market cap.",
            "updated_at": "Timestamp CoinGecko last refreshed this category.",
        },
    },
    "coins_categories_list": {
        "description": "Reference list of category id/name pairs.",
        "docs_url": "https://docs.coingecko.com/reference/coins-categories-list",
        "columns": {
            "category_id": "Category id (used as the category filter on /coins/markets).",
            "name": "Category display name.",
        },
    },
    "exchanges": {
        "description": "Exchange metadata: name, country, trust score, and 24-hour BTC-denominated volume.",
        "docs_url": "https://docs.coingecko.com/reference/exchanges",
        "columns": {
            "id": "CoinGecko exchange id.",
            "name": "Exchange display name.",
            "year_established": "Year the exchange was established.",
            "country": "Country the exchange operates from.",
            "trust_score": "CoinGecko trust score (0-10).",
            "trust_score_rank": "Rank of the exchange by trust score.",
            "trade_volume_24h_btc": "24-hour trading volume denominated in BTC.",
        },
    },
    "exchanges_list": {
        "description": "Reference list of exchange id/name pairs.",
        "docs_url": "https://docs.coingecko.com/reference/exchanges-list",
        "columns": {
            "id": "CoinGecko exchange id.",
            "name": "Exchange display name.",
        },
    },
    "asset_platforms": {
        "description": "Blockchain platforms (Ethereum, Solana, ...) that coins can be issued on.",
        "docs_url": "https://docs.coingecko.com/reference/asset-platforms-list",
        "columns": {
            "id": "Asset platform id.",
            "chain_identifier": "EVM chain id where applicable (null for non-EVM chains).",
            "name": "Platform display name.",
            "shortname": "Short name of the platform.",
            "native_coin_id": "CoinGecko coin id of the platform's native token.",
        },
    },
}
