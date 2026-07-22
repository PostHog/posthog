from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Statement tables share the company wrapper fields plus the standardized statement metadata columns;
# the per-metric columns (Revenue, Total Assets, ...) vary by statement template and fall back to the
# LLM with the docs_url below.
_COMPANY_COLUMNS = {
    "id": "SimFin's unique identifier for the company.",
    "name": "Company name.",
    "ticker": "Stock ticker symbol of the company.",
    "currency": "ISO currency code the figures are reported in.",
    "isin": "International Securities Identification Number of the company.",
}

_STATEMENT_COLUMNS = {
    **_COMPANY_COLUMNS,
    "fiscal_period": "Fiscal period of the statement (Q1-Q4, FY, H1, H2 or nine-month).",
    "fiscal_year": "Fiscal year of the statement (the company's fiscal year, not the calendar year).",
    "report_date": "End date of the reporting period.",
    "publish_date": "Date the statement was first published.",
    "restated": "Whether the figures have been restated since first publication.",
    "source": "Source filing the statement was derived from.",
    "ttm": "Whether the row represents a trailing-twelve-month aggregate.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "companies": {
        "description": "Catalog of every company in the SimFin database with its identifiers and sector classification.",
        "docs_url": "https://simfin.readme.io/reference/list-1",
        "columns": {
            "id": "SimFin's unique identifier for the company.",
            "name": "Company name.",
            "ticker": "Stock ticker symbol of the company.",
            "isin": "International Securities Identification Number of the company.",
            "sectorCode": "Numeric code of the company's sector.",
            "sectorName": "Name of the company's sector.",
            "industryName": "Name of the company's industry.",
        },
    },
    "company_details": {
        "description": "Detailed company profile for each configured ticker, including market, fiscal-year end and headcount.",
        "docs_url": "https://simfin.readme.io/reference/general-1",
        "columns": {
            "id": "SimFin's unique identifier for the company.",
            "name": "Company name.",
            "ticker": "Stock ticker symbol of the company.",
            "isin": "International Securities Identification Number of the company.",
            "sectorCode": "Numeric code of the company's sector.",
            "sectorName": "Name of the company's sector.",
            "industryName": "Name of the company's industry.",
            "market": "Market the company's primary listing trades in (e.g. US, DE).",
            "endFy": "Month the company's fiscal year ends in.",
            "numEmployees": "Number of employees.",
            "companyDescription": "Free-text description of the company's business.",
        },
    },
    "income_statements": {
        "description": "Standardized profit & loss statements, one row per company, fiscal year and period.",
        "docs_url": "https://simfin.readme.io/reference/statements-1",
        "columns": _STATEMENT_COLUMNS,
    },
    "balance_sheets": {
        "description": "Standardized balance sheets, one row per company, fiscal year and period.",
        "docs_url": "https://simfin.readme.io/reference/statements-1",
        "columns": _STATEMENT_COLUMNS,
    },
    "cash_flow_statements": {
        "description": "Standardized cash-flow statements, one row per company, fiscal year and period.",
        "docs_url": "https://simfin.readme.io/reference/statements-1",
        "columns": _STATEMENT_COLUMNS,
    },
    "derived_ratios": {
        "description": "Derived ratios and indicators (EBITDA, free cash flow, margins, per-share figures), one row per company, fiscal year and period.",
        "docs_url": "https://simfin.readme.io/reference/statements-1",
        "columns": _STATEMENT_COLUMNS,
    },
    "share_prices": {
        "description": "Daily split-adjusted share prices with trading volume and dividends, one row per company and trading day.",
        "docs_url": "https://simfin.readme.io/reference/prices-1",
        "columns": {
            **_COMPANY_COLUMNS,
            "date": "Trading day the price row refers to.",
            "opening_price": "Opening price on the trading day.",
            "highest_price": "Highest traded price on the trading day.",
            "lowest_price": "Lowest traded price on the trading day.",
            "last_closing_price": "Unadjusted closing price on the trading day.",
            "adjusted_closing_price": "Closing price adjusted for splits and dividends.",
            "trading_volume": "Number of shares traded on the trading day.",
            "dividend_paid": "Dividend per share paid on the trading day, if any.",
            "common_shares_outstanding": "Common shares outstanding on the trading day.",
        },
    },
    "common_shares_outstanding": {
        "description": "Point-in-time common shares outstanding, one row per company and change date.",
        "docs_url": "https://simfin.readme.io/reference/shares-1",
        "columns": {
            "id": "SimFin's unique identifier for the company.",
            "date": "Date the share count applies from.",
            "common_shares_outstanding": "Number of common shares outstanding at that date.",
        },
    },
    "weighted_shares_outstanding": {
        "description": "Basic and diluted weighted shares outstanding per fiscal period, one row per company, fiscal year and period.",
        "docs_url": "https://simfin.readme.io/reference/weighted-shares-1",
        "columns": {
            "id": "SimFin's unique identifier for the company.",
            "date": "End date of the fiscal period the share counts are weighted over.",
            "fiscal_year": "Fiscal year of the period.",
            "period": "Fiscal period (Q1-Q4, FY, H1, H2 or nine-month).",
            "basic_shares_outstanding": "Weighted average basic shares outstanding over the period.",
            "diluted_shares_outstanding": "Weighted average diluted shares outstanding over the period.",
        },
    },
}
