"""Search-index hooks other products call from their own model save paths."""

from products.tasks.backend.search_index import (
    canvas_deleted as canvas_deleted,
    canvas_saved as canvas_saved,
)
