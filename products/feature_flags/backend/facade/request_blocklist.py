"""Validation and normalization for the per-team request blocklists on TeamFeatureFlagPolicyConfig.

The flags service trims hosts, strips a trailing dot, lowercases them, and skips invalid IP
entries. It applies no other rule, so every writer goes through these functions. Deliberately free of Django/DRF imports: the model module imports
the length limits at module level, and the serializer translates BlocklistEntryError.
"""

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit

import idna

# Caps each list so the flags service scans a short list on every /flags request.
MAX_BLOCKED_HOSTS = 100
MAX_BLOCKED_IPS = 100

# The broadest ranges a blocked IP entry may cover. A wider range blocks a large share of the
# internet, which is almost always a typo for a narrower one.
MIN_BLOCKED_IPV4_PREFIX = 8
MIN_BLOCKED_IPV6_PREFIX = 16

# Bounds the raw list a client sends, before the normalizers drop blanks and duplicates. It only
# guards against abuse, so that MAX_BLOCKED_HOSTS and MAX_BLOCKED_IPS apply to the unique entries.
MAX_BLOCKLIST_INPUT_ENTRIES = 1000

# Column widths. 253 is the DNS limit for a full domain name, which idna.encode enforces. 43 fits
# the longest canonical entry, an IPv6 address with no zero group to compress plus a two-digit
# prefix, such as "ffff:ffff:ffff:ffff:ffff:ffff:ffff:fffe/127".
MAX_BLOCKED_HOST_LENGTH = 253
MAX_BLOCKED_IP_LENGTH = 43

_ALLOWED_SINGLE_LABEL_HOSTS = frozenset({"localhost"})


class BlocklistEntryError(ValueError):
    """An entry for blocked_hosts or blocked_ips that cannot be stored. The message is user-facing."""


def normalize_blocked_hosts(entries: Iterable[str]) -> list[str]:
    """Lowercase, deduplicate, and validate hostnames, keeping the order they were given in.

    A full URL is reduced to its hostname, because people often paste one from the browser.
    """
    hosts: dict[str, None] = {}
    for raw_entry in entries:
        entry = raw_entry.strip().lower()
        if not entry:
            continue
        invalid_error = BlocklistEntryError(
            f"'{raw_entry.strip()}' is not a valid domain. Enter a domain like example.com."
        )
        if "://" in entry:
            # Browsers read a backslash in a URL as a slash, so "https://example.com\@evil.com"
            # opens example.com. urlsplit reads it as part of the userinfo and returns evil.com.
            try:
                entry = urlsplit(entry.replace("\\", "/")).hostname or ""
            except ValueError:
                raise invalid_error
        entry = entry.rstrip(".")
        if entry.startswith("*."):
            raise BlocklistEntryError(
                f"Enter '{entry[2:]}' instead of '{entry}'. A domain already blocks all of its subdomains."
            )
        # Browsers send an internationalized domain in the Origin header as punycode. UTS 46 maps
        # ideographic full stops to ".", so strip the trailing dots again after the encoding.
        try:
            entry = idna.encode(entry, uts46=True, std3_rules=True).decode("ascii").rstrip(".")
        except idna.IDNAError:
            raise invalid_error
        if "." not in entry and entry not in _ALLOWED_SINGLE_LABEL_HOSTS:
            raise BlocklistEntryError(
                f"'{entry}' would block every domain that ends in .{entry}. Enter a full domain like example.com."
            )
        hosts[entry] = None
        if len(hosts) > MAX_BLOCKED_HOSTS:
            raise BlocklistEntryError(f"You can block up to {MAX_BLOCKED_HOSTS} domains.")
    return list(hosts)


def normalize_blocked_ips(entries: Iterable[str]) -> list[str]:
    """Validate IP addresses and CIDR ranges and store them in canonical form, deduplicated.

    Host bits are dropped (`203.0.113.7/24` becomes `203.0.113.0/24`), and a single address is
    stored without its `/32` or `/128` suffix.
    """
    ips: dict[str, None] = {}
    for raw_entry in entries:
        entry = raw_entry.strip()
        if not entry:
            continue
        network: ipaddress.IPv4Network | ipaddress.IPv6Network | None
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            network = None
        # A client IP never carries an IPv6 zone ID (fe80::1%eth0), so a scoped entry can never match.
        if network is None or "%" in entry:
            raise BlocklistEntryError(
                f"'{entry}' is not a valid IP address or range. Enter an address like 203.0.113.7 or a range like 203.0.113.0/24."
            )
        # The flags service matches IPv4 clients against IPv4 entries only, so store a mapped
        # address (::ffff:203.0.113.7) as the IPv4 address it stands for.
        if (
            isinstance(network, ipaddress.IPv6Network)
            and network.prefixlen >= 96
            and network.network_address.ipv4_mapped is not None
        ):
            network = ipaddress.ip_network(f"{network.network_address.ipv4_mapped}/{network.prefixlen - 96}")
        min_prefix = MIN_BLOCKED_IPV4_PREFIX if network.version == 4 else MIN_BLOCKED_IPV6_PREFIX
        if network.prefixlen < min_prefix:
            raise BlocklistEntryError(
                f"'{entry}' covers too many addresses. IPv{network.version} ranges can be /{min_prefix} or narrower."
            )
        normalized = (
            str(network.network_address) if network.prefixlen == network.max_prefixlen else network.with_prefixlen
        )
        ips[normalized] = None
        if len(ips) > MAX_BLOCKED_IPS:
            raise BlocklistEntryError(f"You can block up to {MAX_BLOCKED_IPS} IP addresses or ranges.")
    return list(ips)
