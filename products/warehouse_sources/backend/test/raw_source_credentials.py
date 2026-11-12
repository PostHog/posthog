"""Credentials rows for warehouse sources that a test saves with raw ``job_inputs``.

`SourceInputsStore` reads connection fields only from the credentials row and OAuth pointers only from the
``credentials_integration_id`` column. A test that builds a source with
``ExternalDataSource.objects.create(job_inputs=...)`` skips the store, so the source has neither. While
`link_raw_source_credentials` is active, such a save gets the row and the column that a store write gives, and the
source reads back the inputs that the test stored. A stripped source is a store write, so it is left as it is.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from unittest.mock import patch

from django.db.models.signals import post_save

from posthog.integrations import IntegrationReference

from products.warehouse_sources.backend.logic.credential_auth_types import has_typed_in_credentials
from products.warehouse_sources.backend.logic.source_credentials import (
    CredentialsNotFoundError,
    WarehouseSourceCredentialsStore,
)
from products.warehouse_sources.backend.logic.source_credentials_rollout import (
    in_use_oauth_pointer,
    in_use_oauth_slot,
    is_stripped,
    split_connection_fields,
)
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

_DISPATCH_UID = "link_raw_warehouse_source_credentials"


@contextmanager
def link_raw_source_credentials() -> Iterator[None]:
    post_save.connect(_link, sender=ExternalDataSource, dispatch_uid=_DISPATCH_UID)
    try:
        yield
    finally:
        post_save.disconnect(sender=ExternalDataSource, dispatch_uid=_DISPATCH_UID)


@contextmanager
def read_unsaved_source_inputs_as_stored() -> Iterator[None]:
    """Make reads return ``job_inputs`` as stored, for tests that build sources in memory without a database.

    Such a source can have no credentials row, so a read of its credentials would raise.
    """
    with patch(
        "products.warehouse_sources.backend.logic.source_inputs.read_connection_fields",
        side_effect=lambda source, inputs: inputs,
    ):
        yield


def _link(
    sender: type[ExternalDataSource],
    instance: ExternalDataSource,
    raw: bool = False,
    update_fields: Any = None,
    **kwargs: Any,
) -> None:
    if raw or (update_fields is not None and "job_inputs" not in update_fields):
        return
    saved_reference = instance.credentials_integration_id
    try:
        inputs = SourceInputsStore.load_stored(instance)
        if is_stripped(inputs):
            return
        source_type = str(instance.source_type)
        if in_use_oauth_slot(source_type, inputs) is not None:
            pointer = in_use_oauth_pointer(source_type, inputs)
            reference = None if pointer is None else str(IntegrationReference.from_legacy_id(pointer.integration_id))
        else:
            reference = _write_typed_in_row(instance, inputs)
    except ValueError:
        # Inputs that do not decode, or a shape that the OAuth walk does not read: the store reads neither.
        return
    # As in a store write, inputs without credentials leave the source without a reference.
    if reference == saved_reference:
        return
    instance.credentials_integration_id = reference
    ExternalDataSource.objects.filter(pk=instance.pk).update(credentials_integration_id=reference)


def _write_typed_in_row(instance: ExternalDataSource, inputs: dict[str, Any]) -> str | None:
    source_type = str(instance.source_type)
    if not has_typed_in_credentials(source_type):
        return None
    connection = split_connection_fields(source_type, inputs)
    if not connection:
        return None
    if instance.credentials_integration_id is not None:
        try:
            return str(WarehouseSourceCredentialsStore.update(instance, connection, allow_shared=True))
        except CredentialsNotFoundError:
            pass
    return str(WarehouseSourceCredentialsStore.create(instance, connection))
