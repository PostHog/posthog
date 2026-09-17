from products.posthog_ai.backend.hogai.artifacts.handlers.base import (
    HANDLER_REGISTRY,
    ArtifactHandler,
    EnrichmentContext,
    get_handler_for_content_class,
    get_handler_for_content_type,
    get_handler_for_db_type,
)
from products.posthog_ai.backend.hogai.artifacts.handlers.notebook import NotebookArtifactManagerMixin, NotebookHandler

# Import handlers to trigger registration (order matters: viz before notebook)
from products.posthog_ai.backend.hogai.artifacts.handlers.visualization import (  # noqa: I001
    VisualizationArtifactManagerMixin,
    VisualizationHandler,
)

__all__ = [
    "ArtifactHandler",
    "EnrichmentContext",
    "HANDLER_REGISTRY",
    "get_handler_for_content_class",
    "get_handler_for_content_type",
    "get_handler_for_db_type",
    "NotebookArtifactManagerMixin",
    "NotebookHandler",
    "VisualizationArtifactManagerMixin",
    "VisualizationHandler",
]
