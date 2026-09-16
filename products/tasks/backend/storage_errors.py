"""Errors raised by the tasks object-storage helpers.

Kept apart from ``facade/contracts.py`` so ``storage.py`` — which ``models.py`` imports, and
therefore every process pays at ``django.setup()`` — does not pull the contracts module's
pydantic dataclasses onto the startup path. ``facade/contracts.py`` re-exports the name, so
consumers keep importing it from the facade.
"""


class TaskRunLogAppendUnserialized(Exception):
    """The per-log append lock could not be taken; the caller should retry the append."""
