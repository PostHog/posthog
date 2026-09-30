"""One rule as the hub's snapshot delivers it. Values are already normalized by the hub."""

import ipaddress
from datetime import datetime
from typing import Any

from posthog.dataclasses import frozen

_TEXT_FIELDS = ("id", "targetType", "targetValue", "effect", "scope")


@frozen
class SnapshotRule:
    id: str
    target_type: str
    target_value: str
    effect: str
    scope: str
    expires_at: datetime | None = None
    # Parsed once when the snapshot loads, so a decision never re-parses a range.
    network: ipaddress.IPv4Network | ipaddress.IPv6Network | None = None

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

        return cls(
            id=values["id"],
            target_type=values["targetType"],
            target_value=values["targetValue"],
            effect=values["effect"],
            scope=values["scope"],
            expires_at=expires_at,
            network=network,
        )
