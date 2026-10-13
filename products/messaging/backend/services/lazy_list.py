from collections.abc import Callable, Iterator, Sequence
from typing import Any, TypeVar, overload

from django.db.models import QuerySet

_Contract = TypeVar("_Contract")


class LazyList(Sequence[_Contract]):
    """Contracts backed by a queryset, converted only for the rows a caller slices.

    A paginating view sizes the list and then slices one page, so the database returns one page
    and the size is a COUNT. Nothing but contracts leaves the facade.
    """

    def __init__(self, queryset: QuerySet, to_contract: Callable[[Any], _Contract]) -> None:
        self._queryset = queryset
        self._to_contract = to_contract

    def __len__(self) -> int:
        return self._queryset.count()

    def __iter__(self) -> Iterator[_Contract]:
        # Explicit: the Sequence mixin would iterate by index, one query per row.
        return (self._to_contract(row) for row in self._queryset)

    @overload
    def __getitem__(self, index: int) -> _Contract: ...

    @overload
    def __getitem__(self, index: slice) -> list[_Contract]: ...

    def __getitem__(self, index: int | slice) -> _Contract | list[_Contract]:
        rows = self._queryset[index]
        if isinstance(index, slice):
            return [self._to_contract(row) for row in rows]
        return self._to_contract(rows)
