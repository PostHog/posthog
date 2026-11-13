"""Read-only projection of a source's active filter catalog for the filter editor."""

from posthog.dataclasses import frozen

from products.signals.backend.filter_catalog_schema import CatalogBundle, CatalogFieldType
from products.signals.backend.models import SignalFilterSourceDefinition


@frozen
class SignalFilterField:
    name: str
    type: CatalogFieldType
    description: str


@frozen
class SignalFilterCatalog:
    version: int
    filter_query_eligible: bool
    fields: tuple[SignalFilterField, ...]
    starter_expressions: tuple[str, ...]


def get_filter_catalog(*, source_product: str, source_type: str) -> SignalFilterCatalog | None:
    source = (
        SignalFilterSourceDefinition.objects.filter(source_product=source_product, source_type=source_type)
        .select_related("active_catalog_version")
        .first()
    )
    if source is None or source.active_catalog_version is None:
        return None
    bundle = CatalogBundle.model_validate(source.active_catalog_version.bundle)
    return SignalFilterCatalog(
        version=source.active_catalog_version.version,
        filter_query_eligible=source.filter_query_eligible,
        fields=tuple(
            SignalFilterField(name=field.name, type=field.type, description=field.description)
            for field in bundle.fields
        ),
        starter_expressions=tuple(bundle.starter_expressions),
    )
