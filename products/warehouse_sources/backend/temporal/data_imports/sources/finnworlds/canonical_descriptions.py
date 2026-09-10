"""Canonical, documentation-sourced descriptions for Finnworlds endpoints and columns.

Sourced from the official Finnworlds API documentation (https://finnworlds.com/documentation/).
Keyed by the endpoint names in `settings.py` `FINNWORLDS_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Finnworlds table. Columns absent here fall back to LLM
enrichment. The connector injects `ticker` (and `period` for fundamentals) onto every row, so those
appear as columns even though they originate from the request, not the record body.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

DOCS_URL = "https://finnworlds.com/documentation/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "company_information": {
        "description": "Company profile and reference data (sector, industry, identifiers, executives).",
        "docs_url": DOCS_URL,
        "columns": {
            "ticker": "Stock ticker symbol the data was requested for.",
            "name": "Company legal/display name.",
            "cik": "SEC Central Index Key for the company.",
            "isin": "International Securities Identification Number.",
            "cusip": "CUSIP identifier.",
            "lei": "Legal Entity Identifier.",
            "sector": "Industry sector the company belongs to.",
            "industry": "Industry classification of the company.",
            "sic_code": "Standard Industrial Classification code.",
            "sic_name": "Standard Industrial Classification label.",
            "website": "Company website URL.",
            "about": "Free-text description of the company.",
        },
    },
    "income_statements": {
        "description": "Income statement line items per reporting period for a company.",
        "docs_url": DOCS_URL,
        "columns": {
            "ticker": "Stock ticker symbol the statement belongs to.",
            "period": "Reporting period grain (annual or quarterly).",
            "date": "Fiscal period end date.",
            "total_revenue": "Total revenue for the period.",
            "cost_of_revenue": "Cost of revenue for the period.",
            "gross_profit": "Gross profit (revenue minus cost of revenue).",
            "operating_income": "Operating income for the period.",
            "pretax_income": "Income before income taxes.",
            "tax_provision": "Income tax expense for the period.",
            "net_income": "Net income for the period.",
            "basic_eps": "Basic earnings per share.",
            "diluted_eps": "Diluted earnings per share.",
            "ebit": "Earnings before interest and taxes.",
            "ebitda": "Earnings before interest, taxes, depreciation, and amortization.",
        },
    },
    "balance_sheets": {
        "description": "Balance sheet line items per reporting period for a company.",
        "docs_url": DOCS_URL,
        "columns": {
            "ticker": "Stock ticker symbol the statement belongs to.",
            "period": "Reporting period grain (annual or quarterly).",
            "date": "Fiscal period end date.",
            "total_assets": "Total assets at period end.",
            "total_liabilities_net_minority_interest": "Total liabilities net of minority interest.",
            "stockholders_equity": "Total stockholders' equity.",
            "net_debt": "Net debt (total debt minus cash and equivalents).",
            "working_capital": "Working capital at period end.",
            "ordinary_shares_number": "Number of ordinary shares outstanding.",
            "share_issued": "Number of shares issued.",
        },
    },
    "cash_flows": {
        "description": "Cash flow statement line items per reporting period for a company.",
        "docs_url": DOCS_URL,
        "columns": {
            "ticker": "Stock ticker symbol the statement belongs to.",
            "period": "Reporting period grain (annual or quarterly).",
            "date": "Fiscal period end date.",
            "operating_cash_flow": "Net cash from operating activities.",
            "investing_cash_flow": "Net cash from investing activities.",
            "financing_cash_flow": "Net cash from financing activities.",
            "free_cash_flow": "Free cash flow for the period.",
            "capital_expenditure": "Capital expenditure for the period.",
        },
    },
    "financial_ratios": {
        "description": "Current snapshot of valuation and health ratios for a company.",
        "docs_url": DOCS_URL,
        "columns": {
            "ticker": "Stock ticker symbol the ratios belong to.",
            "date": "Date the ratios were computed (as of).",
            "pe_ratio": "Price-to-earnings ratio.",
            "eps": "Earnings per share.",
            "market_capitalization": "Market capitalization.",
            "debt_equity_ratio": "Debt-to-equity ratio.",
            "altman_z_score": "Altman Z-score bankruptcy risk metric.",
        },
    },
    "dividends": {
        "description": "Historical dividend payments for a company.",
        "docs_url": DOCS_URL,
        "columns": {
            "ticker": "Stock ticker symbol the dividend belongs to.",
            "date": "Official record date of the dividend payment.",
            "dividend_rate": "Dividend amount paid per share.",
        },
    },
    "stock_splits": {
        "description": "Historical stock split events for a company.",
        "docs_url": DOCS_URL,
        "columns": {
            "ticker": "Stock ticker symbol the split belongs to.",
            "date": "Date the split took effect.",
            "stock_split": "Split ratio (e.g. 4:1).",
        },
    },
    "stock_prices": {
        "description": "Daily OHLC price candles and volume for a company.",
        "docs_url": DOCS_URL,
        "columns": {
            "ticker": "Stock ticker symbol the candle belongs to.",
            "date": "Trading date of the candle.",
            "open": "Opening price.",
            "high": "Intraday high price.",
            "low": "Intraday low price.",
            "close": "Closing price.",
            "adjusted_close": "Closing price adjusted for splits and dividends.",
            "trade_volume": "Number of shares traded.",
            "stock_split": "Split ratio applied on this date, if any.",
            "dividend_rate": "Dividend paid on this date, if any.",
        },
    },
    "company_ratings": {
        "description": "Analyst ratings and price targets for a company.",
        "docs_url": DOCS_URL,
        "columns": {
            "ticker": "Stock ticker symbol the rating belongs to.",
            "analyst_name": "Name of the analyst issuing the rating.",
            "analyst_firm": "Firm the analyst represents.",
            "analyst_role": "Role of the analyst at the firm.",
            "date_rating": "Date the rating was issued.",
            "target_date": "Date the price target applies to.",
            "price_target": "Analyst's price target.",
            "rated": "Rating direction (e.g. upgrade, downgrade, maintain).",
            "conclusion": "Analyst's conclusion or recommendation.",
        },
    },
    "sec_filings": {
        "description": "SEC filings (Form type, title, EDGAR link) for a company.",
        "docs_url": DOCS_URL,
        "columns": {
            "ticker": "Stock ticker symbol the filing belongs to.",
            "date": "Filing date.",
            "title": "Filing title.",
            "form_type": "SEC form type (e.g. 10-K, 10-Q, 8-K).",
            "file_number": "SEC file number associated with the filing.",
            "url": "EDGAR index URL for the filing.",
        },
    },
    "bond_yields": {
        "description": "Government bond yields by country and maturity. Global, not company-specific.",
        "docs_url": DOCS_URL,
        "columns": {
            "country": "Country the bond is issued by.",
            "region": "Region the country belongs to.",
            "type": "Bond maturity (e.g. 10Y).",
            "yield": "Current yield.",
            "datetime": "Timestamp the yield was recorded.",
            "price_change_day": "Yield change over the day.",
            "percentage_week": "Percentage change over the week.",
            "percentage_month": "Percentage change over the month.",
            "percentage_year": "Percentage change over the year.",
        },
    },
}
