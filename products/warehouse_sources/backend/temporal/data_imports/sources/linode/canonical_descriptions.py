from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Linode (Akamai Connected Cloud) API v4 docs at
# https://techdocs.akamai.com/linode-api/reference. Partial coverage is fine; anything not listed
# falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "linodes": {
        "description": "Linode instances (virtual machines) on the account.",
        "docs_url": "https://techdocs.akamai.com/linode-api/reference/get-linode-instances",
        "columns": {
            "id": "Unique identifier for the Linode instance.",
            "label": "The user-supplied label for this Linode.",
            "region": "The region (data center) where the Linode is deployed.",
            "type": "The Linode plan type (e.g. g6-standard-2) that determines its resources.",
            "status": "Current run status of the Linode (e.g. running, offline, provisioning).",
            "ipv4": "The public and private IPv4 addresses assigned to this Linode.",
            "ipv6": "The IPv6 range assigned to this Linode.",
            "created": "When this Linode was created.",
            "updated": "When this Linode was last updated.",
        },
    },
    "volumes": {
        "description": "Block storage volumes on the account.",
        "docs_url": "https://techdocs.akamai.com/linode-api/reference/get-volumes",
        "columns": {
            "id": "Unique identifier for the volume.",
            "label": "The user-supplied label for this volume.",
            "status": "Current status of the volume (e.g. active, creating, resizing).",
            "size": "Size of the volume in GB.",
            "region": "The region where the volume resides.",
            "linode_id": "The id of the Linode the volume is attached to, or null if detached.",
            "created": "When this volume was created.",
            "updated": "When this volume was last updated.",
        },
    },
    "nodebalancers": {
        "description": "NodeBalancers (managed load balancers) on the account.",
        "docs_url": "https://techdocs.akamai.com/linode-api/reference/get-node-balancers",
        "columns": {
            "id": "Unique identifier for the NodeBalancer.",
            "label": "The user-supplied label for this NodeBalancer.",
            "region": "The region where the NodeBalancer is deployed.",
            "hostname": "The public hostname of the NodeBalancer.",
            "ipv4": "The public IPv4 address of the NodeBalancer.",
            "created": "When this NodeBalancer was created.",
            "updated": "When this NodeBalancer was last updated.",
        },
    },
    "lke_clusters": {
        "description": "Linode Kubernetes Engine (LKE) clusters on the account.",
        "docs_url": "https://techdocs.akamai.com/linode-api/reference/get-lke-clusters",
        "columns": {
            "id": "Unique identifier for the LKE cluster.",
            "label": "The user-supplied label for this cluster.",
            "region": "The region where the cluster is deployed.",
            "k8s_version": "The Kubernetes version running on the cluster's control plane.",
            "status": "Current status of the cluster (e.g. ready, not_ready).",
            "created": "When this cluster was created.",
            "updated": "When this cluster was last updated.",
        },
    },
    "domains": {
        "description": "DNS domains (zones) managed by the account's DNS Manager.",
        "docs_url": "https://techdocs.akamai.com/linode-api/reference/get-domains",
        "columns": {
            "id": "Unique identifier for the domain.",
            "domain": "The domain name (e.g. example.com).",
            "type": "Whether this is a master or slave zone.",
            "status": "Whether the domain is active, disabled, or has an edit_mode set.",
            "soa_email": "The start-of-authority email address for the zone.",
        },
    },
    "users": {
        "description": "Users with access to the Linode account.",
        "docs_url": "https://techdocs.akamai.com/linode-api/reference/get-users",
        "columns": {
            "username": "The unique username, used as the primary key.",
            "email": "The user's email address.",
            "restricted": "Whether the user only has access to a subset of resources (true) or full access (false).",
            "tfa_enabled": "Whether the user has two-factor authentication enabled.",
        },
    },
    "invoices": {
        "description": "Billing invoices issued to the account.",
        "docs_url": "https://techdocs.akamai.com/linode-api/reference/get-invoices",
        "columns": {
            "id": "Unique identifier for the invoice.",
            "date": "When the invoice was generated. Used as the incremental cursor.",
            "label": "The name/description of the invoice.",
            "total": "The total amount due on the invoice, in US dollars.",
            "subtotal": "The amount of the invoice before taxes, in US dollars.",
            "tax": "The amount of tax levied on the invoice, in US dollars.",
        },
    },
    "payments": {
        "description": "Payments made against the account.",
        "docs_url": "https://techdocs.akamai.com/linode-api/reference/get-payments",
        "columns": {
            "id": "Unique identifier for the payment.",
            "date": "When the payment was made.",
            "usd": "The amount of the payment, in US dollars.",
        },
    },
    "events": {
        "description": "Account audit events (the last 90 days of activity). Immutable and append-only.",
        "docs_url": "https://techdocs.akamai.com/linode-api/reference/get-events",
        "columns": {
            "id": "Unique, monotonically increasing identifier for the event. Used as the incremental cursor.",
            "action": "The type of action that triggered the event (e.g. linode_boot, volume_create).",
            "created": "When the event occurred.",
            "entity": "The resource the event is associated with (type, id, label, url).",
            "username": "The username of the user who triggered the event.",
            "status": "Current status of the event (e.g. finished, failed, notification).",
            "seen": "Whether the event has been seen.",
            "read": "Whether the event has been read.",
        },
    },
}
