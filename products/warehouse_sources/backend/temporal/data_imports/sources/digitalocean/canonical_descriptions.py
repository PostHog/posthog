from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Curated from the DigitalOcean API v2 reference (https://docs.digitalocean.com/reference/api/).
# Applied directly as authoritative column/table descriptions; any endpoint or column not
# covered here falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "droplets": {
        "description": "Virtual machines (Droplets) running in your account.",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Droplets",
        "columns": {
            "id": "Unique numeric identifier for the Droplet.",
            "name": "Human-readable name of the Droplet.",
            "memory": "RAM allocated to the Droplet, in megabytes.",
            "vcpus": "Number of virtual CPUs.",
            "disk": "Disk size allocated to the Droplet, in gigabytes.",
            "region": "Region object the Droplet is deployed in.",
            "image": "Base image the Droplet was created from.",
            "size_slug": "Slug identifying the Droplet's size plan.",
            "status": "Current status (e.g. new, active, off, archive).",
            "created_at": "Time when the Droplet was created (ISO 8601).",
            "tags": "Tags applied to the Droplet.",
        },
    },
    "apps": {
        "description": "App Platform applications and their current specification.",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Apps",
        "columns": {
            "id": "Unique identifier for the app.",
            "spec": "The app's specification (services, static sites, and settings).",
            "default_ingress": "Default URL where the app is reachable.",
            "created_at": "Time when the app was created (ISO 8601).",
            "updated_at": "Time when the app was last updated (ISO 8601).",
            "active_deployment": "The currently live deployment.",
        },
    },
    "kubernetes_clusters": {
        "description": "DigitalOcean Kubernetes (DOKS) clusters.",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Kubernetes",
        "columns": {
            "id": "Unique identifier for the cluster.",
            "name": "Human-readable name of the cluster.",
            "region": "Region slug the cluster runs in.",
            "version": "Kubernetes version running on the cluster.",
            "node_pools": "Worker node pools attached to the cluster.",
            "status": "Current cluster status.",
            "created_at": "Time when the cluster was created (ISO 8601).",
        },
    },
    "databases": {
        "description": "Managed database clusters (Postgres, MySQL, Redis, MongoDB, Kafka).",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Databases",
        "columns": {
            "id": "Unique identifier for the database cluster.",
            "name": "Human-readable name of the cluster.",
            "engine": "Database engine (e.g. pg, mysql, redis).",
            "version": "Engine version.",
            "region": "Region slug the cluster runs in.",
            "status": "Current cluster status.",
            "num_nodes": "Number of nodes in the cluster.",
            "created_at": "Time when the cluster was created (ISO 8601).",
        },
    },
    "volumes": {
        "description": "Block storage volumes.",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Block-Storage",
        "columns": {
            "id": "Unique identifier for the volume.",
            "name": "Human-readable name of the volume.",
            "size_gigabytes": "Size of the volume, in gigabytes.",
            "region": "Region the volume is available in.",
            "droplet_ids": "Droplets the volume is attached to.",
            "created_at": "Time when the volume was created (ISO 8601).",
        },
    },
    "snapshots": {
        "description": "Snapshots of Droplets and volumes.",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Snapshots",
        "columns": {
            "id": "Unique identifier for the snapshot.",
            "name": "Human-readable name of the snapshot.",
            "resource_id": "Identifier of the resource the snapshot was taken from.",
            "resource_type": "Type of resource (droplet or volume).",
            "regions": "Regions the snapshot is available in.",
            "min_disk_size": "Minimum disk size required to use the snapshot, in gigabytes.",
            "size_gigabytes": "Size of the snapshot, in gigabytes.",
            "created_at": "Time when the snapshot was created (ISO 8601).",
        },
    },
    "load_balancers": {
        "description": "Load balancers distributing traffic across Droplets.",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Load-Balancers",
        "columns": {
            "id": "Unique identifier for the load balancer.",
            "name": "Human-readable name of the load balancer.",
            "ip": "Public IP address of the load balancer.",
            "region": "Region the load balancer runs in.",
            "status": "Current status of the load balancer.",
            "forwarding_rules": "Rules mapping inbound to backend traffic.",
            "created_at": "Time when the load balancer was created (ISO 8601).",
        },
    },
    "projects": {
        "description": "Projects used to organize resources in your account.",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Projects",
        "columns": {
            "id": "Unique identifier for the project.",
            "name": "Human-readable name of the project.",
            "purpose": "Stated purpose of the project.",
            "environment": "Environment label (Development, Staging, Production).",
            "is_default": "Whether this is the account's default project.",
            "created_at": "Time when the project was created (ISO 8601).",
        },
    },
    "vpcs": {
        "description": "Virtual Private Cloud networks.",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/VPCs",
        "columns": {
            "id": "Unique identifier for the VPC.",
            "name": "Human-readable name of the VPC.",
            "region": "Region slug the VPC is scoped to.",
            "ip_range": "Private IP address range in CIDR notation.",
            "default": "Whether this is the region's default VPC.",
            "created_at": "Time when the VPC was created (ISO 8601).",
        },
    },
    "images": {
        "description": "User-owned images (snapshots, backups, and custom images).",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Images",
        "columns": {
            "id": "Unique numeric identifier for the image.",
            "name": "Human-readable name of the image.",
            "type": "Type of image (snapshot, backup, or custom).",
            "distribution": "Base distribution of the image.",
            "regions": "Regions the image is available in.",
            "size_gigabytes": "Size of the image, in gigabytes.",
            "created_at": "Time when the image was created (ISO 8601).",
        },
    },
    "domains": {
        "description": "DNS domains managed by DigitalOcean.",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Domains",
        "columns": {
            "name": "The domain name (used as the primary key).",
            "ttl": "Default time-to-live for the domain's records, in seconds.",
            "zone_file": "The domain's complete zone file.",
        },
    },
    "ssh_keys": {
        "description": "SSH public keys registered on the account.",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/SSH-Keys",
        "columns": {
            "id": "Unique numeric identifier for the key.",
            "fingerprint": "Fingerprint of the SSH public key.",
            "public_key": "The SSH public key.",
            "name": "Human-readable name of the key.",
        },
    },
    "reserved_ips": {
        "description": "Reserved (formerly floating) IP addresses.",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Reserved-IPs",
        "columns": {
            "ip": "The reserved IP address (used as the primary key).",
            "region": "Region the reserved IP is available in.",
            "droplet": "Droplet the reserved IP is currently assigned to, if any.",
            "project_id": "Project the reserved IP belongs to.",
        },
    },
    "tags": {
        "description": "Tags used to label and group resources.",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Tags",
        "columns": {
            "name": "The tag name (used as the primary key).",
            "resources": "Summary of resources the tag is applied to.",
        },
    },
    "invoices": {
        "description": "Billing invoices for the account.",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Billing",
        "columns": {
            "invoice_uuid": "Unique identifier for the invoice.",
            "amount": "Total amount of the invoice.",
            "invoice_period": "Billing period the invoice covers (YYYY-MM).",
        },
    },
    "billing_history": {
        "description": "Append-only ledger of billing events (invoices, payments, credits).",
        "docs_url": "https://docs.digitalocean.com/reference/api/api-reference/#tag/Billing",
        "columns": {
            "description": "Description of the billing event.",
            "amount": "Amount associated with the event.",
            "invoice_id": "Identifier of the related invoice, when applicable.",
            "invoice_uuid": "UUID of the related invoice, when applicable.",
            "date": "Time the billing event occurred (ISO 8601).",
            "type": "Type of billing event (e.g. Invoice, Payment).",
        },
    },
}
