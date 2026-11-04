from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IP2WhoisEndpointConfig:
    name: str
    # WHOIS records are keyed on the domain we looked up. It's injected on every row (see
    # `ip2whois.py`) so the key is stable regardless of how the API echoes the domain back.
    primary_keys: list[str] = field(default_factory=lambda: ["domain"])
    description: Optional[str] = None


# IP2WHOIS exposes a single lookup endpoint (`GET /v2?domain=...`) that returns the WHOIS record for
# one domain per request. There's no list/search endpoint, so the one table is driven by the
# user-supplied set of domains, one API call each. Full refresh only — the API has no server-side
# change cursor.
IP2WHOIS_ENDPOINTS: dict[str, IP2WhoisEndpointConfig] = {
    "whois": IP2WhoisEndpointConfig(
        name="whois",
        primary_keys=["domain"],
        description=(
            "WHOIS registration record (registrar, registrant/admin/tech/billing contacts, nameservers, "
            "and creation/update/expiration dates) for each configured domain. One API lookup per domain "
            "on every sync; full refresh only."
        ),
    ),
}

ENDPOINTS = tuple(IP2WHOIS_ENDPOINTS.keys())
