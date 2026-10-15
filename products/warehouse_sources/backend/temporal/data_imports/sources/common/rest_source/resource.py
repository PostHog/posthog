from collections.abc import Callable, Iterator
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.safe_point import (
    framework_checkpoints_are_covered,
    hold_safe_points,
)

ResumeHook = Callable[[Optional[dict[str, Any]]], None]


class PageCheckpoints:
    """Holds the resume states that pagination produces until the `Resource` hands the page on.

    Pagination knows a page's resume state before the page is converted and transformed. A state
    staged at that point would cover rows that a failing transform never hands on, and the pipeline
    commits staged state when a source raises. The `Resource` therefore applies the state itself,
    next to its own `yield`.
    """

    def __init__(self, resume_hook: ResumeHook) -> None:
        self._resume_hook = resume_hook
        self._pending: list[Optional[dict[str, Any]]] = []

    def defer(self, state: Optional[dict[str, Any]]) -> None:
        self._pending.append(state)

    def defer_page_state(self, state: Optional[dict[str, Any]], _has_next_page: bool) -> None:
        self.defer(state)

    def apply(self, *, page_is_handed_on: bool) -> None:
        pending, self._pending = self._pending, []
        if not pending:
            return
        if page_is_handed_on:
            for state in pending:
                self._resume_hook(state)
            return
        # The framework reaches its own safe point after the page is handed on, so nothing is lost.
        with hold_safe_points():
            for state in pending:
                self._resume_hook(state)


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
        page_checkpoints: Optional[PageCheckpoints] = None,
    ) -> None:
        self.name = name
        self._hints = hints
        self._maps: list[Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]] = []
        self._filters: list[Callable[[dict[str, Any]], bool]] = []
        self._generator_fn = generator_fn
        self._args = args
        self._kwargs = kwargs or {}
        self._data_from = data_from
        self._page_checkpoints = page_checkpoints

    @property
    def column_hints(self) -> Optional[dict[str, Any]]:
        """Return a mapping of column name to ``data_type`` extracted from the
        resource's ``columns`` hint, suitable for ``SourceResponse.column_hints``.
        """
        columns = self._hints.get("columns")
        if columns is None:
            return None
        return {key: value.get("data_type") for key, value in columns.items()}

    def add_map(self, fn: Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]) -> "Resource":
        """Add a per-item transform. Returning a dict maps 1:1; returning a list explodes the item
        1-to-many (e.g. flattening a report bucket's ``results[]`` into one row per result, with
        parent-bucket fields merged in). Later maps apply to each exploded row."""
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
            # A map may return a dict (1:1) or a list of dicts (1-to-many explode); subsequent
            # maps apply to every row produced so far.
            current: list[dict[str, Any]] = [item]
            for m in self._maps:
                next_rows: list[dict[str, Any]] = []
                for row in current:
                    mapped = m(row)
                    if isinstance(mapped, list):
                        next_rows.extend(mapped)
                    else:
                        next_rows.append(mapped)
                current = next_rows
            result.extend(current)
        return result

    def _iter_generator(self, call_kwargs: dict[str, Any]) -> Iterator[list[dict[str, Any]]]:
        checkpoints = self._page_checkpoints
        for page in self._generator_fn(*self._args, **call_kwargs):
            transformed = self._apply_transforms(page)
            if checkpoints is None:
                if transformed:
                    yield transformed
                continue

            # When the pipeline iterates this resource directly, it must receive a page with its
            # resume state already staged. The pipeline commits staged state right after it writes a
            # batch, and it can end the attempt before control returns here. State staged after the
            # `yield` is then lost for the last page, and the next attempt reads that page again.
            # A source that wraps this resource can hold the page before it hands rows on, so its
            # state waits until the wrapper asks for the next page.
            if framework_checkpoints_are_covered():
                checkpoints.apply(page_is_handed_on=False)
            if transformed:
                yield transformed
            checkpoints.apply(page_is_handed_on=True)

        if checkpoints is not None:
            checkpoints.apply(page_is_handed_on=True)

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
