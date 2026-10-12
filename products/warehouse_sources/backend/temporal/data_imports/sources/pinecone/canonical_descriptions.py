from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "indexes": {
        "description": "Configuration and status of indexes in the connected Pinecone project.",
        "docs_url": "https://docs.pinecone.io/reference/api/2026-07/control-plane/list_indexes",
        "columns": {
            "name": "Index name, unique within the project.",
            "host": "Address of the index's data plane endpoint.",
            "deployment": "Deployment type, cloud provider, and region of the index.",
            "schema": "Field definitions, including vector dimensions and similarity metrics.",
            "status": "Index readiness and current state.",
            "deletion_protection": "Whether the index is protected from deletion.",
            "tags": "User-defined key-value labels on the index.",
        },
    },
    "collections": {
        "description": "Collections containing snapshots of pod-based indexes in the connected Pinecone project.",
        "docs_url": "https://docs.pinecone.io/reference/api/2026-07/control-plane/list_collections",
        "columns": {
            "name": "Collection name, unique within the project.",
            "size": "Collection size in bytes.",
            "status": "Collection lifecycle state.",
            "dimension": "Dimensions of each vector in the collection.",
            "vector_count": "Number of records stored in the collection.",
            "environment": "Environment hosting the collection.",
        },
    },
    "backups": {
        "description": "Backup inventory for the connected Pinecone project.",
        "docs_url": "https://docs.pinecone.io/reference/api/2026-07/control-plane/list_project_backups",
        "columns": {
            "backup_id": "Unique backup identifier.",
            "source_index_name": "Name of the index the backup was taken from.",
            "source_index_id": "Identifier of the index the backup was taken from.",
            "status": "Backup creation state.",
            "created_at": "Time the backup was created.",
            "record_count": "Number of records in the backup.",
            "namespace_count": "Number of namespaces in the backup.",
            "size_bytes": "Backup size in bytes.",
        },
    },
    "restore_jobs": {
        "description": "Progress and results of backup restore jobs in the connected Pinecone project.",
        "docs_url": "https://docs.pinecone.io/reference/api/2026-07/control-plane/list_restore_jobs",
        "columns": {
            "restore_job_id": "Unique restore job identifier.",
            "backup_id": "Identifier of the backup being restored.",
            "target_index_name": "Name of the index receiving the restored records.",
            "target_index_id": "Identifier of the index receiving the restored records.",
            "status": "Restore job state.",
            "created_at": "Time the restore job started, when available.",
            "completed_at": "Time the restore job finished, null until completion.",
            "percent_complete": "Completion indicator, reported as 100 for completed jobs.",
        },
    },
}
