from products.data_catalog.backend.facade.contracts import DigestSource

from ..data_catalog_digest import suggestion_rows, teams_with_open_suggestions

DIGEST_SOURCES = (
    DigestSource(name="warehouse_suggestions", rows=suggestion_rows, teams_with_rows=teams_with_open_suggestions),
)
