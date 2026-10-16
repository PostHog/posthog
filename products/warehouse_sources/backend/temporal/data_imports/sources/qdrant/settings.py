BASE_URL = "https://api.cloud.qdrant.io"
API_VERSION = "v1"
PAGE_SIZE = 100

ENDPOINTS = {
    "clusters": "/api/cluster/v1/accounts/{account_id}/clusters",
    "backups": "/api/cluster/backup/v1/accounts/{account_id}/backups",
    "backup_schedules": "/api/cluster/backup/v1/accounts/{account_id}/backup_schedules",
    "backup_restores": "/api/cluster/backup/v1/accounts/{account_id}/backup_restores",
}

PRIMARY_KEYS = ["id"]
PARTITION_KEY = "createdAt"

AUTH_ERROR = "Qdrant rejected the Cloud Management Key. Check the key in Access Management > Cloud Management Keys."
PERMISSION_ERROR = "The Qdrant key lacks permission. Grant read:clusters, read:backups, or read:backup_schedules for the selected tables."
ACCOUNT_ERROR = "Enter a valid Qdrant account ID from the Cloud Console."
