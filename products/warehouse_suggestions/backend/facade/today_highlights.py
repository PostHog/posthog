from products.today.backend.facade.contracts import HighlightSource

from ..today_highlights import find_catalog_approvals, find_model_suggestions

HIGHLIGHT_SOURCES = (
    HighlightSource(
        name="data_catalog_approvals",
        find=find_catalog_approvals,
        scopes=("data_catalog:read", "data_catalog_approval:write"),
    ),
    HighlightSource(name="warehouse_model_suggestions", find=find_model_suggestions),
)
