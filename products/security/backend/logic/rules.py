"""One rule as the hub's snapshot delivers it. Values are already normalized by the hub."""

import re
import ipaddress
from datetime import datetime
from typing import Any

from posthog.dataclasses import frozen

_TEXT_FIELDS = ("id", "targetType", "targetValue", "effect", "scope")
_EMAIL_TYPES = ("email", "email_root", "email_domain", "email_pattern")

_WILDCARD = "*"
_MAX_PATTERN_WILDCARDS = 3
_MIN_PATTERN_LOCAL_LITERALS = 3
_MAX_PATTERN_DOMAIN_LENGTH = 253
_PATTERN_DOMAIN_LABEL = re.compile(r"[a-z0-9*-]+")


@frozen
class EmailPattern:
    """A whole-address glob. `*` matches any run of characters, and every other character is literal."""

    segments: tuple[str, ...]

    @classmethod
    def parse(cls, value: str) -> "EmailPattern | None":
        """The pattern, or None when it breaks the hub's limits.

        The hub refuses these values when a rule is written. Refusing them again here means a
        bad row can never match everyone, as `*@*` would. The hub also refuses a pattern whose
        literal domain is posthog.com. That check is not repeated here, because a decision never
        blocks a posthog.com account.
        """
        local, at, domain = value.partition("@")
        if not at or "@" in domain or re.search(r"\s", value):
            return None
        if value.count(_WILDCARD) > _MAX_PATTERN_WILDCARDS:
            return None
        if len(local.replace(_WILDCARD, "")) < _MIN_PATTERN_LOCAL_LITERALS:
            return None
        if domain != _WILDCARD:
            labels = domain.split(".")
            if len(domain) > _MAX_PATTERN_DOMAIN_LENGTH:
                return None
            if not all(_PATTERN_DOMAIN_LABEL.fullmatch(label) for label in labels):
                return None
            if all(_WILDCARD in label for label in labels):
                return None
        return cls(segments=tuple(value.split(_WILDCARD)))

    def matches(self, address: str) -> bool:
        # Not a regex: with three wildcards a backtracking regex does cubic work on a crafted
        # address, and signup and login run this for every pattern rule.
        if len(self.segments) == 1:
            return address == self.segments[0]
        head, *middle, tail = self.segments
        end = len(address) - len(tail)
        if end < len(head) or not address.startswith(head) or not address.endswith(tail):
            return False
        position = len(head)
        for segment in middle:
            found = address.find(segment, position, end)
            if found < 0:
                return False
            position = found + len(segment)
        return True


@frozen
class SnapshotRule:
    id: str
    target_type: str
    target_value: str
    effect: str
    scope: str
    expires_at: datetime | None = None
    # Parsed once when the snapshot loads, so a decision never re-parses a range or a pattern.
    network: ipaddress.IPv4Network | ipaddress.IPv6Network | None = None
    email_pattern: EmailPattern | None = None

    @classmethod
    def from_wire(cls, raw: object) -> "SnapshotRule | None":
        """The rule, or None when the hub sent something this release can't read."""
        if not isinstance(raw, dict):
            return None
        values: dict[str, Any] = {key: raw.get(key) for key in _TEXT_FIELDS}
        if not all(isinstance(value, str) for value in values.values()):
            return None

        expires_at: datetime | None = None
        expires_raw = raw.get("expiresAt")
        if expires_raw is not None:
            if not isinstance(expires_raw, str):
                return None
            try:
                expires_at = datetime.fromisoformat(expires_raw)
            except ValueError:
                return None
            # A naive value can't compare against the aware `now` a decision uses, which
            # raises TypeError inside decide and fails the whole check closed.
            if expires_at.utcoffset() is None:
                return None

        network = None
        if values["targetType"] == "ip":
            try:
                network = ipaddress.ip_network(values["targetValue"])
            except ValueError:
                return None

        # The hub normalizes a target value when the rule is written, and a subject's address
        # is normalized at decision time, so the two already meet in the middle. Folding the
        # case again here costs nothing and closes a silent failure: a rule that reached the
        # snapshot un-normalized would match nobody, and nothing would report it. The Redis
        # list this replaced lowercased on read, so it could not be defeated that way.
        target_value = values["targetValue"]
        if values["targetType"] in _EMAIL_TYPES:
            target_value = target_value.strip().lower()

        email_pattern = None
        if values["targetType"] == "email_pattern":
            # The hub writes pattern rules as blocks only. An exemption on a pattern would
            # drop the login email code for every address it covers.
            if values["effect"] != "block":
                return None
            email_pattern = EmailPattern.parse(target_value)
            if email_pattern is None:
                return None

        return cls(
            id=values["id"],
            target_type=values["targetType"],
            target_value=target_value,
            effect=values["effect"],
            scope=values["scope"],
            expires_at=expires_at,
            network=network,
            email_pattern=email_pattern,
        )
