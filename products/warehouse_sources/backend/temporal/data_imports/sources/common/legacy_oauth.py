from collections.abc import Mapping
from dataclasses import field
from typing import Any

from posthog.dataclasses import frozen


@frozen
class LegacyOAuthGrant:
    kind: str
    external_id: str
    config: Mapping[str, Any]
    sensitive_config: Mapping[str, Any] = field(repr=False)
    pointer_key: str
    legacy_keys: tuple[str, ...]
    refresh_token: str = field(repr=False)


class LegacyOAuthGrantUnusable(Exception):
    """The legacy tokens cannot be used. Messages must not contain tokens."""
