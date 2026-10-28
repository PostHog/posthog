"""Source inputs wiring for other products and for this product's presentation layer.

Code outside the logic layer reads and writes a source's ``job_inputs`` only through this class, never
through the model field. Each method delegates to the store in ``logic/source_inputs.py``.
"""

from products.warehouse_sources.backend.facade.contracts import (
    SourceCredentialsMissingError,
    UnreadableSourceInputsError,
)
from products.warehouse_sources.backend.logic import (
    source_credentials_rollout as _rollout,
    source_inputs as _store,
)


class SourceInputsStore:
    load = staticmethod(_store.SourceInputsStore.load)
    load_many = staticmethod(_store.SourceInputsStore.load_many)
    preload = staticmethod(_store.SourceInputsStore.preload)
    load_settings = staticmethod(_store.SourceInputsStore.load_settings)
    stored_as_string = staticmethod(_store.SourceInputsStore.stored_as_string)
    assign = staticmethod(_store.SourceInputsStore.assign)
    save = staticmethod(_store.SourceInputsStore.save)
    create = staticmethod(_store.SourceInputsStore.create)
    update_runtime = staticmethod(_store.SourceInputsStore.update_runtime)
    aload = staticmethod(_store.SourceInputsStore.aload)
    asave = staticmethod(_store.SourceInputsStore.asave)
    requested_credentials_reference = staticmethod(_rollout.requested_credentials_reference)


__all__ = ["SourceCredentialsMissingError", "SourceInputsStore", "UnreadableSourceInputsError"]
