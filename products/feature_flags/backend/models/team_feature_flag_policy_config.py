import re
import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit

from django.contrib.postgres.fields import ArrayField
from django.db import models

# Caps each list so the flags service scans a short list on every /flags request.
MAX_BLOCKED_HOSTS = 100
MAX_BLOCKED_IPS = 100

# The broadest ranges a blocked IP entry may cover. A wider range blocks a large share of the
# internet, which is almost always a typo for a narrower one.
MIN_BLOCKED_IPV4_PREFIX = 8
MIN_BLOCKED_IPV6_PREFIX = 16

_HOSTNAME_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


class BlocklistEntryError(ValueError):
    """An entry for blocked_hosts or blocked_ips that cannot be stored. The message is user-facing."""


def normalize_blocked_hosts(entries: Iterable[str]) -> list[str]:
    """Lowercase, deduplicate, and validate hostnames, keeping the order they were given in.

    A full URL is reduced to its hostname, because people often paste one from the browser.
    """
    hosts: list[str] = []
    for raw_entry in entries:
        entry = raw_entry.strip().lower()
        if not entry:
            continue
        if "://" in entry:
            entry = urlsplit(entry).hostname or ""
        entry = entry.rstrip(".")
        if entry.startswith("*."):
            raise BlocklistEntryError(
                f"Enter '{entry[2:]}' instead of '{entry}'. A domain already blocks all of its subdomains."
            )
        if len(entry) > 253 or not all(_HOSTNAME_LABEL.match(label) for label in entry.split(".")):
            raise BlocklistEntryError(f"'{raw_entry.strip()}' is not a valid domain. Enter a domain like example.com.")
        if entry not in hosts:
            hosts.append(entry)
    if len(hosts) > MAX_BLOCKED_HOSTS:
        raise BlocklistEntryError(f"You can block up to {MAX_BLOCKED_HOSTS} domains.")
    return hosts


def normalize_blocked_ips(entries: Iterable[str]) -> list[str]:
    """Validate IP addresses and CIDR ranges and store them in canonical form, deduplicated.

    Host bits are dropped (`203.0.113.7/24` becomes `203.0.113.0/24`), and a single address is
    stored without its `/32` or `/128` suffix.
    """
    ips: list[str] = []
    for raw_entry in entries:
        entry = raw_entry.strip()
        if not entry:
            continue
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            raise BlocklistEntryError(
                f"'{entry}' is not a valid IP address or range. Enter an address like 203.0.113.7 or a range like 203.0.113.0/24."
            )
        min_prefix = MIN_BLOCKED_IPV4_PREFIX if network.version == 4 else MIN_BLOCKED_IPV6_PREFIX
        if network.prefixlen < min_prefix:
            raise BlocklistEntryError(
                f"'{entry}' covers too many addresses. IPv{network.version} ranges can be /{min_prefix} or narrower."
            )
        normalized = (
            str(network.network_address) if network.prefixlen == network.max_prefixlen else network.with_prefixlen
        )
        if normalized not in ips:
            ips.append(normalized)
    if len(ips) > MAX_BLOCKED_IPS:
        raise BlocklistEntryError(f"You can block up to {MAX_BLOCKED_IPS} IP addresses or ranges.")
    return ips


class TeamFeatureFlagPolicyConfig(models.Model):
    """Customer-editable feature flag rules for a team.

    Distinct from TeamFeatureFlagsConfig, which holds staff-only rollout switches and is never
    exposed to customers. This one is reachable by project admins as `feature_flag_policy_config`
    on the team/project API.

    These rules are bookkeeping, and they do not hold on every write path. The exemptions are
    declared by the caller, and a path that builds a serializer context without `get_team` skips
    the rules entirely: the organization-level flag copy and the approvals apply path both do.
    """

    # db_constraint=False: a real FK constraint would take a SHARE ROW EXCLUSIVE
    # lock on posthog_team (a hot table) while migrating.
    # related_name="+": the relation crosses a product boundary, so it must not add a reverse
    # accessor to Team. Readers come in through `Team.feature_flag_policy_config` instead.
    team = models.OneToOneField(
        "posthog.Team", on_delete=models.CASCADE, primary_key=True, db_constraint=False, related_name="+"
    )

    # Blocks creating a flag with no tags, and blocks removing the last tag from a flag that has
    # one. Only applies to flags a person creates directly. Flags generated to back a survey,
    # experiment, early access feature, product tour, or web experiment are exempt, because those
    # forms have no tag input and would otherwise dead-end.
    require_tags = models.BooleanField(default=False)

    # The flags service answers /flags and /decide requests from these hosts or IPs with an
    # empty response, before billing and evaluation. It reads both lists from the team metadata
    # cache, so a write takes effect once that cache refreshes. Writers normalize the entries
    # with normalize_blocked_hosts and normalize_blocked_ips; a host also blocks its subdomains.
    # db_default lets pods on the previous release insert rows without naming these columns.
    blocked_hosts = ArrayField(models.CharField(max_length=253), default=list, blank=True, db_default=[])
    blocked_ips = ArrayField(models.CharField(max_length=43), default=list, blank=True, db_default=[])


def team_requires_flag_tags(team_id: int) -> bool:
    """Whether this team requires tags on flags.

    Queries the row rather than going through ``get_or_create_team_extension`` so a read on the
    flag-write path does not create the row for every team that never touched the setting.
    """
    return (
        TeamFeatureFlagPolicyConfig.objects.filter(team_id=team_id).values_list("require_tags", flat=True).first()
        is True
    )
