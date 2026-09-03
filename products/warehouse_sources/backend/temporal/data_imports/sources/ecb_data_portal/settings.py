from datetime import date
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://data-api.ecb.europa.eu"


@frozen
class ECBEndpointConfig:
    name: str
    flow: str
    key: str
    description: str
    # Earliest observation date for this flow/key, confirmed against the live API. Only set for
    # flows large enough to be worth splitting into chunk_years windows below — leave unset for
    # small flows, which always fetch (and re-fetch, on incremental syncs) their full remaining
    # history in a single unbounded request.
    history_start: Optional[date] = None
    # Calendar-year window size for a full backfill. None fetches the whole series in one request
    # (verified fine for FM and ICP: well under 100 KB each). EXR's full history is ~260k rows /
    # ~57 MB in a single response, so it's split into 5-year windows and resumed via
    # ECBResumeConfig if a sync is interrupted mid-backfill.
    chunk_years: Optional[int] = None


ENDPOINT_CONFIGS: dict[str, ECBEndpointConfig] = {
    "eur_exchange_rates": ECBEndpointConfig(
        name="eur_exchange_rates",
        flow="EXR",
        key="D..EUR.SP00.A",
        description="Daily ECB reference exchange rates for the euro against published currencies.",
        history_start=date(1999, 1, 4),
        chunk_years=5,
    ),
    "key_interest_rates": ECBEndpointConfig(
        name="key_interest_rates",
        flow="FM",
        key="B.U2.EUR.4F.KR..LEV",
        description="ECB key interest rates (main refinancing, deposit facility, marginal lending), by date of change.",
    ),
    "hicp_inflation": ECBEndpointConfig(
        name="hicp_inflation",
        flow="ICP",
        key="M.U2.N.000000.4.ANR",
        description="Euro area HICP (inflation) overall index, annual rate of change.",
    ),
}

ENDPOINTS = tuple(ENDPOINT_CONFIGS)

# TIME_PERIOD is the only server-side filterable field (via startPeriod/endPeriod) on every
# flow — there's no separate "created"/"modified" column in the SDMX response.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": "Time period",
            "type": IncrementalFieldType.Date,
            "field": "TIME_PERIOD",
            "field_type": IncrementalFieldType.Date,
        }
    ]
    for name in ENDPOINTS
}
