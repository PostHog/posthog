from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Fly.io Machines API docs (https://fly.io/docs/machines/api/).
# Keyed by endpoint/schema name (matching ENDPOINTS). Any column not listed here falls back to
# LLM enrichment, which is given the source name, endpoint, docs_url, and column data types.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "apps": {
        "description": "Fly.io apps in the organization. An app is the top-level unit that groups machines, volumes, and networking.",
        "docs_url": "https://fly.io/docs/machines/api/apps-resource/",
        "columns": {
            "id": "Unique identifier for the app.",
            "internal_numeric_id": "Fly.io internal numeric identifier for the app.",
            "name": "The app name (globally unique across Fly.io).",
            "machine_count": "Number of machines currently belonging to the app.",
            "volume_count": "Number of volumes currently belonging to the app.",
            "network": "Name of the private network the app's machines are attached to.",
            "organization": "Organization the app belongs to (slug, name, and internal numeric id).",
            "status": "Current status of the app (e.g. deployed, suspended, pending).",
        },
    },
    "machines": {
        "description": "Fly.io machines (Firecracker microVMs) across the organization, one row per machine with its owning app.",
        "docs_url": "https://fly.io/docs/machines/api/machines-resource/",
        "columns": {
            "id": "Unique identifier for the machine.",
            "app_name": "Name of the app this machine belongs to.",
            "name": "Human-readable machine name.",
            "state": "Current lifecycle state (e.g. started, stopped, suspended, destroyed).",
            "region": "Fly.io region the machine runs in (e.g. iad, lhr, syd).",
            "private_ip": "The machine's private IPv6 address on the app's network.",
            "config": "The machine configuration overview (guest resources, image, and services). Secret-bearing fields are excluded: environment variables, secrets, inline file contents, user-defined metadata (only Fly's own platform keys are kept), and request headers on services and checks.",
            "version": "Version identifier of the machine's current configuration.",
            "created_at": "Timestamp the machine was created (RFC 3339).",
            "updated_at": "Timestamp the machine was last updated (RFC 3339).",
        },
    },
    "volumes": {
        "description": "Fly.io volumes (persistent storage) across the organization, one row per volume with its owning app.",
        "docs_url": "https://fly.io/docs/machines/api/volumes-resource/",
        "columns": {
            "id": "Unique identifier for the volume.",
            "app_name": "Name of the app this volume belongs to.",
            "name": "Human-readable volume name.",
            "state": "Current state of the volume (e.g. created, pending_destroy).",
            "region": "Fly.io region the volume is stored in.",
            "zone": "Hardware zone within the region hosting the volume.",
            "size_gb": "Provisioned size of the volume in gigabytes.",
            "encrypted": "Whether the volume is encrypted at rest.",
            "fstype": "Filesystem type of the volume (e.g. ext4).",
            "auto_backup_enabled": "Whether automatic daily snapshots are enabled.",
            "snapshot_retention": "Number of days snapshots are retained.",
            "attached_machine_id": "ID of the machine the volume is currently attached to, if any.",
            "attached_alloc_id": "ID of the allocation the volume is attached to (legacy apps).",
            "block_size": "Block size of the volume's filesystem, in bytes.",
            "blocks": "Total number of filesystem blocks.",
            "blocks_free": "Number of free filesystem blocks.",
            "blocks_avail": "Number of filesystem blocks available to unprivileged users.",
            "bytes_total": "Total capacity of the volume in bytes.",
            "bytes_used": "Bytes currently used on the volume.",
            "host_status": "Status of the host machine backing the volume.",
            "type": "Storage type of the volume.",
            "created_at": "Timestamp the volume was created (RFC 3339).",
            "updated_at": "Timestamp the volume was last updated (RFC 3339).",
        },
    },
}
