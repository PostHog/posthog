from itertools import count
from typing import Any

from products.security.backend.logic.snapshot import reset_memo, write_snapshot

_ids = count(1)


def _rule(overrides: dict[str, Any], **defaults: Any) -> dict[str, Any]:
    return {"id": f"01920000-0000-7000-8000-{next(_ids):012d}", "expiresAt": None, **defaults, **overrides}


def block_rule(**overrides: Any) -> dict[str, Any]:
    return _rule(overrides, targetType="email", targetValue="blocked@example.com", effect="block", scope="all_access")


def exempt_rule(**overrides: Any) -> dict[str, Any]:
    return _rule(overrides, targetType="email", targetValue="exempt@example.com", effect="exempt", scope="email_code")


def seed_rules(*rules: dict[str, Any]) -> None:
    write_snapshot(f"test-{next(_ids)}", list(rules))
    reset_memo()
