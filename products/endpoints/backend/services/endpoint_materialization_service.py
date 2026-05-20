from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.endpoints.backend.materialization import build_endpoint_hogql


class OrphanedEndpointSavedQueryError(Exception):
    pass


def prepare_executable_query(saved_query: DataWarehouseSavedQuery) -> None:
    version = saved_query.endpoint_versions.first()
    if version is None:
        raise OrphanedEndpointSavedQueryError(
            f"Saved query {saved_query.id} ({saved_query.name}) has no linked EndpointVersion"
        )

    saved_query.query = build_endpoint_hogql(version.query, saved_query.team, bucket_overrides=version.bucket_overrides)
    saved_query.save(update_fields=["query", "updated_at"])
