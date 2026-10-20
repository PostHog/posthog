from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, get_args

from posthog.dataclasses import frozen

RunStartCursorKind = Literal["number", "datetime", "naive_datetime", "date"]
_KINDS: frozenset[str] = frozenset(get_args(RunStartCursorKind))


@frozen
class RunStartCursor:
    """The incremental lower bound that one queue run extracts from.

    The producer writes it into the metadata of each batch of an incremental merge run. When a
    new run starts at or below the start of an older run, the new run extracts again every row
    that the older run queued.
    """

    field: str
    kind: RunStartCursorKind
    value: str

    @classmethod
    def from_value(cls, *, field: str, value: Any) -> RunStartCursor | None:
        """Encode a lower bound, or return None for a value that cannot be ordered safely."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float | Decimal):
            try:
                number = Decimal(str(value))
            except InvalidOperation:
                return None
            if not number.is_finite():
                return None
            return cls(field=field, kind="number", value=str(number))
        # A naive and an aware datetime cannot be ordered against each other, so each has its own kind.
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return cls(field=field, kind="naive_datetime", value=value.isoformat())
            return cls(field=field, kind="datetime", value=value.astimezone(UTC).isoformat())
        if isinstance(value, date):
            return cls(field=field, kind="date", value=value.isoformat())
        return None

    @classmethod
    def from_payload(cls, payload: Any) -> RunStartCursor | None:
        """Decode a cursor from batch metadata. Return None for a payload in an unknown shape."""
        if not isinstance(payload, dict):
            return None
        field, kind, value = payload.get("field"), payload.get("kind"), payload.get("value")
        if not isinstance(field, str) or not isinstance(value, str) or kind not in _KINDS:
            return None
        cursor = cls(field=field, kind=kind, value=value)
        try:
            cursor._sort_key()
        except (ValueError, InvalidOperation):
            return None
        return cursor

    def to_payload(self) -> dict[str, str]:
        return {"field": self.field, "kind": self.kind, "value": self.value}

    def rereads(self, payload: Any) -> bool:
        """Whether a run that starts here extracts every row of the run that recorded `payload`."""
        other = RunStartCursor.from_payload(payload)
        if other is None or other.field != self.field or other.kind != self.kind:
            return False
        mine, theirs = self._sort_key(), other._sort_key()
        if isinstance(mine, Decimal) and isinstance(theirs, Decimal):
            return mine <= theirs
        if isinstance(mine, date) and isinstance(theirs, date):
            return mine <= theirs
        return False

    def _sort_key(self) -> Decimal | datetime | date:
        if self.kind == "number":
            number = Decimal(self.value)
            if not number.is_finite():
                raise ValueError(f"Not a finite number: {self.value}")
            return number
        if self.kind == "datetime":
            moment = datetime.fromisoformat(self.value)
            if moment.tzinfo is None:
                raise ValueError(f"Not an aware datetime: {self.value}")
            return moment
        if self.kind == "naive_datetime":
            moment = datetime.fromisoformat(self.value)
            if moment.tzinfo is not None:
                raise ValueError(f"Not a naive datetime: {self.value}")
            return moment
        return date.fromisoformat(self.value)
