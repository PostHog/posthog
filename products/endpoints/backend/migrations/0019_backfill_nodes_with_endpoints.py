from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 1000
LOG_INTERVAL = 25


def backfill_endpoints_to_dags(apps, _):
    from products.data_modeling.backend.models import Node, NodeType
    from products.data_modeling.backend.services.saved_query_dag_sync import get_dag_id, sync_saved_query_to_dag
    from products.data_warehouse.backend.models import DataWarehouseSavedQuery

    existing_saved_query_ids = set(Node.objects.values_list("saved_query_id", flat=True))
    endpoint_saved_queries = DataWarehouseSavedQuery.objects.filter(
        deleted=False, origin=DataWarehouseSavedQuery.Origin.ENDPOINT
    ).exclude(id__in=existing_saved_query_ids)
    total_to_backfill = endpoint_saved_queries.count()
    logger.info("Starting endpoint saved_query -> node and edge model backfill...")

    for i, saved_query in enumerate(endpoint_saved_queries.iterator(chunk_size=BATCH_SIZE)):
        Node.objects.create(
            team_id=saved_query.team_id,
            saved_query=saved_query,
            dag_id_text=get_dag_id(saved_query.team_id),
            name=saved_query.name,
            type=NodeType.ENDPOINT,
            properties={"endpoint_backfilled": True},
        )
        if (i + 1) % LOG_INTERVAL == 0:
            logger.info("Backfilling nodes...", progress=i + 1, total=total_to_backfill)

    logger.info("All nodes backfilled. Backfilling edges...")

    # second pass: sync to create edges (all nodes now exist)
    for i, saved_query in enumerate(endpoint_saved_queries.iterator(chunk_size=BATCH_SIZE)):
        sync_saved_query_to_dag(saved_query, extra_properties={"endpoint_backfilled": True})
        if (i + 1) % LOG_INTERVAL == 0:
            logger.info("Backfilling edges...", progress=i + 1, total=total_to_backfill)
    logger.info("All edges backfilled.")
    logger.info("Done.")


def reverse_backfill(apps, schema_editor):
    """
    Reverse the backfill by deleting only Nodes and Edges that were
    created by this migration (identified by endpoint_backfilled=True property).
    """
    Node = apps.get_model("data_modeling", "Node")
    Edge = apps.get_model("data_modeling", "Edge")

    Edge.objects.filter(properties__endpoint_backfilled=True).delete()
    Node.objects.filter(properties__endpoint_backfilled=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0018_endpointversion_bucket_overrides"),
        ("data_modeling", "0010_add_endpoint_node_type"),
    ]

    operations = [
        migrations.RunPython(backfill_endpoints_to_dags, reverse_backfill, elidable=True),
    ]
