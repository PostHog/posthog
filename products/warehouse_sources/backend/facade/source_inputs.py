"""Source inputs wiring for other products and for this product's presentation layer.

Code outside the logic layer reads and writes a source's ``job_inputs`` only through this class, never
through the model field. Each method delegates to the store in ``logic/source_inputs.py``.
"""

from products.warehouse_sources.backend.facade.contracts import UnreadableSourceInputsError
from products.warehouse_sources.backend.logic import (
    source_credentials as _credentials,
    source_credentials_rollout as _rollout,
    source_inputs as _store,
)


class SourceInputsStore:
    # The model fields that `assign` stages. A caller that saves with `update_fields` after `assign` lists them all.
    update_fields = _store.INPUTS_UPDATE_FIELDS
    load = staticmethod(_store.SourceInputsStore.load)
    load_many = staticmethod(_store.SourceInputsStore.load_many)
    load_settings = staticmethod(_store.SourceInputsStore.load_settings)
    stored_as_string = staticmethod(_store.SourceInputsStore.stored_as_string)
    assign = staticmethod(_store.SourceInputsStore.assign)
    save = staticmethod(_store.SourceInputsStore.save)
    create = staticmethod(_store.SourceInputsStore.create)
    update_runtime = staticmethod(_store.SourceInputsStore.update_runtime)
    update_oauth_inputs = staticmethod(_store.SourceInputsStore.update_oauth_inputs)
    aload = staticmethod(_store.SourceInputsStore.aload)
    asave = staticmethod(_store.SourceInputsStore.asave)
    requested_credentials_reference = staticmethod(_rollout.requested_credentials_reference)
    with_credentials_of = staticmethod(_rollout.with_credentials_of)
    credentials_usages = staticmethod(_credentials.WarehouseSourceCredentialsStore.other_usages)


__all__ = ["SourceInputsStore", "UnreadableSourceInputsError"]
