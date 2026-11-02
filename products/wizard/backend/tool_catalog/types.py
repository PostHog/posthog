from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.codebase_detection import Detection
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


@frozen
class Tool:
    kind: str
    label: str
    warehouse_source_type: ExternalDataSourceType | None
    detection: Detection
    # Whether the wizard sends the user to the app to create the source. None for a tool with no source.
    setup_requires_ui: bool | None


@frozen
class ToolClassification:
    warehouse_source_type: str | None
    alternative_to: tuple[str, ...]
