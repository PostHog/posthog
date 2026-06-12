"""Shared django-filter primitives for the Replay Vision viewsets."""

from typing import Any

from django.db.models import F, Q, QuerySet

import django_filters
from rest_framework.exceptions import ValidationError


def split_csv(value: str) -> list[str]:
    """Split a CSV string on commas, strip each entry, drop empties."""
    return [v for v in (v.strip() for v in value.split(",")) if v]


def validate_csv_choices(
    value: str,
    valid_choices: frozenset[str],
    error_key: str,
) -> list[str]:
    """Parse a CSV string and reject any value outside `valid_choices` with a 400."""
    values = split_csv(value)
    if not values:
        return values
    invalid = sorted({v for v in values if v not in valid_choices})
    if invalid:
        raise ValidationError({error_key: f"Invalid value(s) {invalid}; allowed: {sorted(valid_choices)}."})
    return values


def ordering_enum(fields: tuple[str, ...]) -> list[str]:
    """Ascending + descending (`-`-prefixed) variants of each ordering key."""
    return [value for field in fields for value in (field, f"-{field}")]


class MultiChoiceFilter(django_filters.CharFilter):
    """CSV multi-value filter; 400s on values outside `valid_choices` (unlike `BaseInFilter`, which silently matches nothing)."""

    def __init__(
        self,
        *args: Any,
        valid_choices: frozenset[str] | None = None,
        error_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._valid_choices = valid_choices
        # `error_key` overrides the default response key so ORM traversal paths don't leak to the client.
        self._error_key = error_key

    def filter(self, qs: QuerySet, value: str | None) -> QuerySet:
        if not value:
            return qs
        if self._valid_choices is not None:
            values = validate_csv_choices(value, self._valid_choices, self._error_key or self.field_name)
        else:
            values = split_csv(value)
        if not values:
            return qs
        return qs.filter(Q((f"{self.field_name}__in", values)))


class OrderByFilter(django_filters.CharFilter):
    """Base for `?order_by=` filters. Subclasses set `_allowed_keys` and implement `_handle`."""

    _allowed_keys: frozenset[str] = frozenset()
    _tiebreaker: str = "id"

    def filter(self, qs: QuerySet, value: str | None) -> QuerySet:
        if not value:
            return qs
        descending = value.startswith("-")
        key = value[1:] if descending else value
        if key not in self._allowed_keys:
            raise ValidationError(
                {"order_by": f"Invalid order_by '{value}'. Allowed keys: {sorted(self._allowed_keys)}."}
            )
        return self._handle(qs, key, descending)

    def _handle(self, qs: QuerySet, key: str, descending: bool) -> QuerySet:
        raise NotImplementedError

    def _order_plain(self, qs: QuerySet, key: str, descending: bool) -> QuerySet:
        return qs.order_by(("-" if descending else "") + key, self._tiebreaker)

    def _order_nulls_last(self, qs: QuerySet, annotation: str, descending: bool) -> QuerySet:
        f = F(annotation)
        expr = f.desc(nulls_last=True) if descending else f.asc(nulls_last=True)
        return qs.order_by(expr, self._tiebreaker)


__all__ = [
    "MultiChoiceFilter",
    "OrderByFilter",
    "ordering_enum",
    "split_csv",
    "validate_csv_choices",
]
