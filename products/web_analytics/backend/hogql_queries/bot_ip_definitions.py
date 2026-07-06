from dataclasses import dataclass
from functools import cache
from ipaddress import IPv6Address, collapse_addresses, ip_network

from products.web_analytics.backend.hogql_queries.bot_ip_networks import (
    GOOGLE_COMMON_CRAWLER_NETWORKS,
    GOOGLE_SPECIAL_CRAWLER_NETWORKS,
    GOOGLE_USER_TRIGGERED_FETCHER_NETWORKS,
)


@dataclass(frozen=True)
class BotIPDefinition:
    name: str  # Display name: "Googlebot"
    category: str  # Category, same vocabulary as BotDefinition: "search_crawler", ...
    traffic_type: str  # Type, same vocabulary as BotDefinition: "Bot", ...
    operator: str  # Operator/company: "Google"
    networks: tuple[str, ...]  # Collapsed CIDR ranges (IPv4 and IPv6) published by the operator
    documentation_url: str | None = None


# Some crawlers (e.g. Google's mobile rendering service) send real browser user agents
# with no bot token, so the operator-published source IP ranges are the only reliable
# classification signal. Refresh the network lists with
# products/web_analytics/scripts/refresh_bot_ip_ranges.py.
BOT_IP_DEFINITIONS: dict[str, BotIPDefinition] = {
    "google-common-crawlers": BotIPDefinition(
        "Googlebot",
        "search_crawler",
        "Bot",
        "Google",
        networks=GOOGLE_COMMON_CRAWLER_NETWORKS,
        documentation_url="https://developers.google.com/crawling/docs/verifying-google-crawlers",
    ),
    "google-special-crawlers": BotIPDefinition(
        "Google special crawler",
        "search_crawler",
        "Bot",
        "Google",
        networks=GOOGLE_SPECIAL_CRAWLER_NETWORKS,
        documentation_url="https://developers.google.com/crawling/docs/verifying-google-crawlers",
    ),
    "google-user-triggered-fetchers": BotIPDefinition(
        "Google fetcher",
        "search_crawler",
        "Bot",
        "Google",
        networks=GOOGLE_USER_TRIGGERED_FETCHER_NETWORKS,
        documentation_url="https://developers.google.com/crawling/docs/verifying-google-crawlers",
    ),
}

# The query-time matcher normalizes every address to IPv6 (IPv4 maps to ::ffff:a.b.c.d),
# so IPv4 CIDRs become IPv6 CIDRs with the prefix length shifted by 96 bits.
_IPV4_MAPPED_OFFSET = 96


def _ipv6_prefix_groups(cidrs: tuple[str, ...]) -> tuple[tuple[int, tuple[str, ...]], ...]:
    groups: dict[int, list[str]] = {}
    for cidr in cidrs:
        network = ip_network(cidr)
        if network.version == 4:
            prefixlen = network.prefixlen + _IPV4_MAPPED_OFFSET
            address = str(IPv6Address(f"::ffff:{network.network_address}"))
        else:
            prefixlen = network.prefixlen
            address = str(network.network_address)
        groups.setdefault(prefixlen, []).append(address)
    return tuple((prefixlen, tuple(sorted(addresses))) for prefixlen, addresses in sorted(groups.items()))


@cache
def bot_ip_prefix_groups_by_definition() -> tuple[tuple[str, tuple[tuple[int, tuple[str, ...]], ...]], ...]:
    """Per-definition (prefixlen, network addresses) groups, for labeled lookups (bot name etc.)."""
    return tuple((key, _ipv6_prefix_groups(definition.networks)) for key, definition in BOT_IP_DEFINITIONS.items())


@cache
def merged_bot_ip_prefix_groups() -> tuple[tuple[int, tuple[str, ...]], ...]:
    """(prefixlen, network addresses) groups across all definitions, for the boolean is-bot check."""
    all_networks = [ip_network(cidr) for definition in BOT_IP_DEFINITIONS.values() for cidr in definition.networks]
    v4 = collapse_addresses(n for n in all_networks if n.version == 4)
    v6 = collapse_addresses(n for n in all_networks if n.version == 6)
    return _ipv6_prefix_groups(tuple(str(n) for n in [*v4, *v6]))
