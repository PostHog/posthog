"""Source inputs wiring for other products and core code.

Code outside warehouse_sources reads and writes a source's ``job_inputs`` only through this store,
never through the model field.
"""

from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore, UnreadableSourceInputsError

__all__ = ["SourceInputsStore", "UnreadableSourceInputsError"]
