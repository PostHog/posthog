from collections.abc import Callable, Iterator
from typing import Any, Optional


class Resource:
    """Lightweight resource wrapper that replaces DltResource.

    Supports the interface consumed by the pipeline:
    - ``name``: resource name
    - ``_hints``: dict with ``columns``, ``write_disposition``, etc.
    - ``add_map(fn)``: add per-item transformation
    - ``add_filter(fn)``: add per-item filter
    - iteration: yields pages of data (``list[dict]``)
    - ``data_from``: when set, the generator is re-invoked for each page of
      the parent resource, with the parent page passed in as the ``items``
      kwarg. This is how dependent (fan-out) resources are driven.

    Generators passed in are plain sync generators — the rest_source does no
    awaiting, so there's no reason to pay the cost of an async event loop to
    walk them.
    """

    def __init__(
        self,
        generator_fn: Callable[..., Iterator[Any]],
        *,
        name: str,
        hints: dict[str, Any],
        args: tuple[Any, ...] = (),
        kwargs: Optional[dict[str, Any]] = None,
        data_from: Optional["Resource"] = None,
    ) -> None:
        self.name = name
        self._hints = hints
        self._maps: list[Callable[[dict[str, Any]], dict[str, Any]]] = []
        self._filters: list[Callable[[dict[str, Any]], bool]] = []
        self._generator_fn = generator_fn
        self._args = args
        self._kwargs = kwargs or {}
        self._data_from = data_from

    @property
    def column_hints(self) -> Optional[dict[str, Any]]:
        """Return a mapping of column name to ``data_type`` extracted from the
        resource's ``columns`` hint, suitable for ``SourceResponse.column_hints``.
        """
        columns = self._hints.get("columns")
        if columns is None:
            return None
        return {key: value.get("data_type") for key, value in columns.items()}

    def add_map(self, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> "Resource":
        self._maps.append(fn)
        return self

    def add_filter(self, fn: Callable[[dict[str, Any]], bool]) -> "Resource":
        self._filters.append(fn)
        return self

    def _apply_transforms(self, page: Any) -> list[dict[str, Any]]:
        if not isinstance(page, list):
            items = list(page) if hasattr(page, "__iter__") else [page]
        else:
            items = page

        result = []
        for item in items:
            if not isinstance(item, dict):
                result.append(item)
                continue
            skip = False
            for f in self._filters:
                if not f(item):
                    skip = True
                    break
            if skip:
                continue
            for m in self._maps:
                item = m(item)
            result.append(item)
        return result

    def _iter_generator(self, call_kwargs: dict[str, Any]) -> Iterator[list[dict[str, Any]]]:
        for page in self._generator_fn(*self._args, **call_kwargs):
            transformed = self._apply_transforms(page)
            if transformed:
                yield transformed

    def __iter__(self) -> Iterator[list[dict[str, Any]]]:
        if self._data_from is None:
            yield from self._iter_generator(self._kwargs)
            return

        # Dependent resource: drive the child generator with each parent page
        # as the ``items`` kwarg. The parent's own transforms are applied
        # before the pages reach us (via the parent's ``__iter__``).
        for parent_page in self._data_from:
            if not parent_page:
                continue
            call_kwargs = {**self._kwargs, "items": parent_page}
            yield from self._iter_generator(call_kwargs)
