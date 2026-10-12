from posthog.dataclasses import frozen
from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.facade.codebase_detection import Detection
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


@frozen
class Tool:
    kind: str
    label: str
    warehouse_source_type: ExternalDataSourceType | None
    detection: Detection

    @property
    def competes_with(self) -> tuple[ProductKey, ...]:
        return self.detection.competes_with
