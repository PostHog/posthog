"""Snapshots a model's persisted field values across a save, for signal receivers that act
only when a save really changed something.

A ``pre_save`` receiver stores the values the save is about to overwrite; its ``post_save``
counterpart compares them against the instance. Each receiver passes its own attribute and
field set, so two features watching the same model never depend on which fields the other
happens to watch.
"""

from typing import Any

from django.db import models


def capture_fields_before_save(
    instance: models.Model,
    manager: models.Manager[Any],
    fields: frozenset[str],
    *,
    attr: str,
    update_fields: frozenset[str] | None,
    raw: bool,
) -> None:
    """Snapshot the persisted fields this save may overwrite.

    Always resets the snapshot first so a failed earlier save can never leak a stale
    capture into a later save's comparison.
    """
    setattr(instance, attr, None)
    if raw or instance.pk is None:
        return
    # Only fields this save will actually persist: a field changed in memory but excluded
    # from update_fields is not written, so it must not count.
    persisted_fields = fields if update_fields is None else fields.intersection(update_fields)
    if not persisted_fields:
        return
    # sorted(): set iteration order varies between processes, and it reaches the SELECT's
    # column list — an unstable query string defeats plan reuse and makes the query
    # snapshots that cover flag saves fail at random.
    setattr(instance, attr, manager.filter(pk=instance.pk).values(*sorted(persisted_fields)).first())


def snapshot_if_changed(instance: models.Model, *, attr: str) -> dict[str, Any] | None:
    """Pop the pre_save snapshot and return it only if a snapshotted value changed."""
    before = instance.__dict__.pop(attr, None)
    if before is None:
        return None
    if all(getattr(instance, field) == value for field, value in before.items()):
        return None
    return before
