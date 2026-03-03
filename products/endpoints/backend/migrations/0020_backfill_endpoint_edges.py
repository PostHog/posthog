from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 1000
LOG_INTERVAL = 25


def backfill_endpoint_edges(apps, _):
    from products.data_modeling.backend.models import Node, NodeType
    from products.data_modeling.backend.services.saved_query_dag_sync import sync_saved_query_to_dag

    # Find endpoint nodes that have no incoming edges (missing edges from 0019)
    endpoint_nodes_without_edges = (
        Node.objects.filter(type=NodeType.ENDPOINT, saved_query__isnull=False)
        .exclude(incoming_edges__isnull=False)
        .select_related("saved_query")
    )
    total = endpoint_nodes_without_edges.count()
    logger.info("Starting endpoint edge backfill...", total=total)

    if total == 0:
        logger.info("No endpoint nodes missing edges. Nothing to do.")
        return

    failed = 0
    for i, node in enumerate(endpoint_nodes_without_edges.iterator(chunk_size=BATCH_SIZE)):
        try:
            if node.saved_query:
                sync_saved_query_to_dag(node.saved_query, extra_properties={"endpoint_edges_backfilled": True})
        except Exception as e:
            failed += 1
            logger.warning(
                "Failed to backfill edges for endpoint node",
                node_id=str(node.id),
                saved_query_id=str(node.saved_query_id),
                saved_query_name=node.name,
                error=str(e),
            )
        if (i + 1) % LOG_INTERVAL == 0:
            logger.info("Backfilling endpoint edges...", progress=i + 1, total=total)

    logger.info("Endpoint edge backfill complete.", total=total, failed=failed)


def reverse_backfill(apps, schema_editor):
    Edge = apps.get_model("data_modeling", "Edge")
    Edge.objects.filter(properties__endpoint_edges_backfilled=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("endpoints", "0019_backfill_nodes_with_endpoints"),
        ("data_modeling", "0010_add_endpoint_node_type"),
    ]

    operations = [
        migrations.RunPython(backfill_endpoint_edges, reverse_backfill, elidable=True),
    ]
