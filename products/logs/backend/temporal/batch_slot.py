"""The pool slot a logs evaluation workflow takes before it evaluates a batch.

Its own module, with no Django import, because the workflow code builds these and Temporal's
workflow sandbox refuses a module that imports a Django model.
"""

from posthog.dataclasses import frozen


@frozen
class LogsBatchSlot:
    """A slot one workflow took for one batch. The evaluation it hands the slot to releases it."""

    member: str
    held_until: float


@frozen
class LogsBatchAdmission:
    """The result of one try at a slot. `due` is false when the batch has nothing left to evaluate."""

    due: bool
    slot: LogsBatchSlot | None = None
