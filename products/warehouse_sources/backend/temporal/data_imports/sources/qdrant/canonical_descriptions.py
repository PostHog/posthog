from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "clusters": {
        "description": "Qdrant database clusters in the selected cloud account.",
        "docs_url": "https://github.com/qdrant/qdrant-cloud-public-api/blob/main/proto/qdrant/cloud/cluster/v1/cluster.proto",
        "columns": {
            "id": "Unique cluster identifier.",
            "created_at": "Time when Qdrant created the cluster.",
            "account_id": "Identifier of the account that owns the cluster.",
            "name": "Cluster name.",
            "cloud_provider_id": "Cloud provider that hosts the cluster.",
            "cloud_provider_region_id": "Cloud provider region or hybrid cloud environment identifier.",
            "configuration": "Cluster configuration.",
            "state": "Cluster state.",
            "labels": "Cluster labels for the cloud console and billing reports.",
        },
    },
    "backups": {
        "description": "Database backups in the selected Qdrant Cloud account.",
        "docs_url": "https://github.com/qdrant/qdrant-cloud-public-api/blob/main/proto/qdrant/cloud/cluster/backup/v1/backup.proto",
        "columns": {
            "id": "Unique backup identifier.",
            "created_at": "Time when Qdrant created the backup.",
            "account_id": "Identifier of the account that owns the backup.",
            "cluster_id": "Identifier of the cluster that owns the backup.",
            "backup_schedule_id": "Identifier of the schedule that created the backup, when applicable.",
            "name": "Generated backup name, which does not change.",
            "status": "Backup status.",
            "retention_period": "Backup retention period, in seconds. An unset value means indefinite retention.",
        },
    },
    "backup_schedules": {
        "description": "Recurring backup schedules in the selected Qdrant Cloud account.",
        "docs_url": "https://github.com/qdrant/qdrant-cloud-public-api/blob/main/proto/qdrant/cloud/cluster/backup/v1/backup.proto",
        "columns": {
            "id": "Unique backup schedule identifier.",
            "created_at": "Time when Qdrant created the schedule.",
            "account_id": "Identifier of the account that owns the schedule.",
            "cluster_id": "Identifier of the cluster that the schedule backs up.",
            "schedule": "Backup schedule in crontab format.",
            "retention_period": "Backup retention period, in seconds. An unset value means indefinite retention.",
            "status": "Backup schedule status.",
        },
    },
    "backup_restores": {
        "description": "Backup restore operations in the selected Qdrant Cloud account.",
        "docs_url": "https://github.com/qdrant/qdrant-cloud-public-api/blob/main/proto/qdrant/cloud/cluster/backup/v1/backup.proto",
        "columns": {
            "id": "Unique restore identifier.",
            "created_at": "Time when Qdrant created the restore operation.",
            "account_id": "Identifier of the account that owns the restore operation.",
            "cluster_id": "Identifier of the cluster for the restore operation.",
            "backup_id": "Identifier of the backup to restore.",
            "status": "Restore status.",
        },
    },
}
