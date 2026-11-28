"""The pool slot a metrics evaluation workflow takes before it evaluates a batch.

Its own module, with no Django import, because the workflow code builds these and Temporal's
workflow sandbox refuses a module that imports a Django model.
"""

from posthog.dataclasses import frozen


@frozen
class MetricsBatchSlot:
    """A slot one workflow took for one batch. The evaluation it hands the slot to releases it."""

    member: str
    held_until: float


@frozen
class MetricsBatchAdmission:
    """The result of one try at a slot. `due` is false when the batch has nothing left to evaluate."""

    due: bool
    slot: MetricsBatchSlot | None = None
