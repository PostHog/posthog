"""Find the warehouse sources that point at a core ``Integration``.

An OAuth source stores the pointer as a ``*_integration_id`` field in its inputs. The inputs are
encrypted, so SQL cannot search them. The search loads the inputs of the non-deleted sources of one
team, which keeps the cost bounded by the size of that team.
"""

from collections.abc import Mapping
from typing import Any

from products.warehouse_sources.backend.facade.contracts import SourceReferencingIntegration
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

POINTER_SUFFIX = "_integration_id"


def list_sources_using_integration(team_id: int, integration_pk: int) -> list[SourceReferencingIntegration]:
    sources = list(
        ExternalDataSource.objects.select_related(None)
        .filter(team_id=team_id)
        .exclude(deleted=True)
        .only("id", "source_type", "prefix", "job_inputs")
    )
    inputs_by_source = SourceInputsStore.load_many(sources)
    wanted = str(integration_pk)
    return [
        SourceReferencingIntegration(id=source.id, source_type=str(source.source_type), prefix=source.prefix)
        for source in sources
        if _has_pointer(inputs_by_source.get(source.id, {}), wanted)
    ]


def _has_pointer(inputs: Mapping[str, Any], wanted: str) -> bool:
    for key, value in inputs.items():
        if key.endswith(POINTER_SUFFIX) and value is not None and str(value) == wanted:
            return True
        # Switch groups and select options nest their fields one level down.
        if isinstance(value, Mapping) and _has_pointer(value, wanted):
            return True
    return False
