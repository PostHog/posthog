"""Transport-neutral sample-capture primitives.

Both the HTTP (`common/http/sampling.py`) and gRPC (`common/grpc/sampling.py`)
sample-capture pipelines share:

- the `CaptureRule` / `CaptureConfig` data model and its JSON (de)serialization,
- the status-class / status-code matching used to decide whether a rule fires,
- the scrubadub-based value scrubbing that anonymizes captured payloads.

Each transport keeps its own Redis key, S3 prefix, in-process config cache and
payload builder local — only the pieces above are shared here.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

WILDCARD = "*"
REDACTED_SCRUB_FAILURE = "<scrub_failed>"

# Auth-bearing field/key names redacted wholesale (by key) in captured samples,
# across transports. Deliberately curated to unambiguous secret-bearing names —
# generic, overloaded tokens like `code`, `key`, `auth`, or `token` are excluded
# because they collide with non-secret protobuf fields (e.g. `error.code`,
# `page_token`) and would make samples useless without protecting anything.
REDACT_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "developer_token",
        "access_token",
        "refresh_token",
        "id_token",
        "subject_token",
        "actor_token",
        "client_secret",
        "client_assertion",
        "private_key",
        "private_key_id",
        "api_key",
        "apikey",
        "password",
        "authorization",
    }
)


@dataclass(frozen=True)
class CaptureRule:
    source_type: str = WILDCARD
    response_code: str = WILDCARD
    team_id: str = WILDCARD
    schema_id: str = WILDCARD
    limit: int = 0

    def matches_dimensions(self, *, source_type: str, team_id: int, schema_id: str) -> bool:
        """Match the non-status dimensions (source/team/schema) against this rule."""
        if self.source_type != WILDCARD and self.source_type != source_type:
            return False
        if self.team_id != WILDCARD and self.team_id != str(team_id):
            return False
        if self.schema_id != WILDCARD and self.schema_id != str(schema_id):
            return False
        return True

    def matches(self, *, source_type: str, status_code: int | None, team_id: int, schema_id: str) -> bool:
        """HTTP-style match: dimensions + numeric HTTP status (incl. `2xx` classes)."""
        if not self.matches_dimensions(source_type=source_type, team_id=team_id, schema_id=schema_id):
            return False
        return matches_http_status(self.response_code, status_code)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CaptureRule:
        return cls(
            source_type=str(raw.get("source_type") or WILDCARD),
            response_code=str(raw.get("response_code") or WILDCARD),
            team_id=str(raw.get("team_id") or WILDCARD),
            schema_id=str(raw.get("schema_id") or WILDCARD),
            limit=int(raw.get("limit") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "response_code": self.response_code,
            "team_id": self.team_id,
            "schema_id": self.schema_id,
            "limit": self.limit,
        }


@dataclass(frozen=True)
class CaptureConfig:
    capture_id: str
    rules: tuple[CaptureRule, ...] = field(default_factory=tuple)

    @classmethod
    def from_json(cls, raw: bytes | str) -> CaptureConfig | None:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Failed to decode capture config JSON")
            return None

        capture_id = data.get("capture_id")
        if not capture_id:
            return None
        rules_raw = data.get("rules") or []
        rules = tuple(CaptureRule.from_dict(r) for r in rules_raw if isinstance(r, dict))
        return cls(capture_id=str(capture_id), rules=rules)

    def to_json(self) -> str:
        return json.dumps({"capture_id": self.capture_id, "rules": [r.to_dict() for r in self.rules]})


def matches_http_status(rule_value: str, status_code: int | None) -> bool:
    """Match a numeric HTTP status against a rule value (`*`, `200`, or `2xx`)."""
    if rule_value == WILDCARD:
        return True
    if status_code is None:
        return False
    if rule_value.endswith("xx") and len(rule_value) == 3 and rule_value[0].isdigit():
        return str(status_code).startswith(rule_value[0])
    return rule_value == str(status_code)


# scrubadub's default Scrubber is constructed lazily; the import is heavy.
_scrubber_lock = threading.Lock()
_scrubber: Any | None = None


def get_scrubber() -> Any:
    global _scrubber
    if _scrubber is not None:
        return _scrubber
    with _scrubber_lock:
        if _scrubber is None:
            import scrubadub

            _scrubber = scrubadub.Scrubber()
        return _scrubber


def scrub_string(value: str) -> str:
    if not value:
        return value
    try:
        return get_scrubber().clean(value)
    except Exception:
        # Fail closed: a scrubadub failure on a value we couldn't otherwise
        # categorise must not leak the raw, potentially sensitive content
        # into the captured sample. Replace with a placeholder so the
        # surrounding structure (header dict, body shape) is preserved
        # for fixture use, but the unredacted value never lands in S3.
        logger.debug("scrubadub failed; replacing value with placeholder", exc_info=True)
        return REDACTED_SCRUB_FAILURE


def scrub_value(value: Any) -> Any:
    """Walk a JSON-shaped value, scrubbing string leaves but preserving keys."""
    if isinstance(value, dict):
        return {k: scrub_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_value(item) for item in value]
    if isinstance(value, str):
        return scrub_string(value)
    return value
