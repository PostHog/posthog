"""Canonical, documentation-sourced descriptions for Spot by Flexera endpoints and columns.

Sourced from the official Spot by Flexera OpenAPI reference (https://docs.spot.io/api/). Keyed by
the resource names in `settings.py` `SPOT_IO_ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Spot table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "elastigroups": {
        "description": (
            "An AWS Elastigroup: a fleet of spot/on-demand EC2 instances managed together for "
            "cost-optimized capacity, with a defined scaling strategy and launch configuration."
        ),
        "docs_url": "https://docs.spot.io/api/?version=v3#tag/Elastigroup-AWS",
        "columns": {
            "id": "Unique identifier of the Elastigroup.",
            "name": "Name of the Elastigroup.",
            "description": "User-provided description of the Elastigroup.",
            "capacity": "Minimum, maximum, and target instance capacity for the group.",
            "strategy": "Risk and on-demand/spot balancing strategy used when provisioning capacity.",
            "compute": "Compute configuration: instance types, availability zones, and launch specification.",
            "scaling": "Scaling policies attached to the group.",
            "scheduling": "Scheduled tasks configured for the group.",
            "createdAt": "Time at which the Elastigroup was created.",
            "updatedAt": "Time at which the Elastigroup was last updated.",
        },
    },
    "ocean_clusters": {
        "description": (
            "An Ocean cluster: the configuration Spot uses to manage a Kubernetes cluster's "
            "worker node capacity across spot, on-demand, and reserved instances."
        ),
        "docs_url": "https://docs.spot.io/api/?version=v3#tag/Ocean-AWS",
        "columns": {
            "id": "Unique identifier of the Ocean cluster.",
            "name": "Name of the Ocean cluster.",
            "controllerClusterId": "Identifier used by the Ocean controller running inside the Kubernetes cluster.",
            "region": "AWS region the cluster runs in.",
            "autoScaler": "Auto-scaling configuration for the cluster's worker nodes.",
            "capacity": "Minimum, maximum, and target worker node capacity for the cluster.",
            "strategy": "Spot/on-demand balancing strategy used when provisioning worker nodes.",
            "compute": "Compute configuration: instance types, availability zones, and launch specification.",
            "createdAt": "Time at which the Ocean cluster was created.",
            "updatedAt": "Time at which the Ocean cluster was last updated.",
        },
    },
    "stateful_nodes": {
        "description": (
            "A Stateful Node: a single persistent EC2 instance managed by Spot with attached "
            "storage and network state preserved across spot interruptions."
        ),
        "docs_url": "https://docs.spot.io/api/?version=v3#tag/Stateful-Node-AWS",
        "columns": {
            "id": "Unique identifier of the Stateful Node.",
            "config": "Instance configuration: region, instance types, and launch specification.",
            "createdAt": "Time at which the Stateful Node was created.",
            "updatedAt": "Time at which the Stateful Node was last updated.",
        },
    },
    "elastigroup_costs": {
        "description": (
            "Per-instance realized cost and savings for an Elastigroup over a rolling 30-day "
            "window, broken down by running time and actual vs. potential (on-demand) spend."
        ),
        "docs_url": "https://docs.spot.io/api/?version=v3#tag/Elastigroup-AWS/paths/~1aws~1ec2~1group~1%7BgroupId%7D~1costs~1detailed/get",
        "columns": {
            "groupId": "Identifier of the Elastigroup this cost entry belongs to.",
            "elastigroup_name": "Name of the Elastigroup this cost entry belongs to.",
            "instanceId": "Identifier of the EC2 instance this cost entry covers.",
            "spotInstanceRequestId": "Identifier of the spot instance request, if the instance was a spot instance.",
            "instanceType": "EC2 instance type (e.g. m5.large).",
            "availabilityZone": "AWS availability zone the instance ran in.",
            "running": "Total running time for the instance over the window.",
            "savings": "Realized savings versus on-demand pricing for the instance over the window.",
            "costs": "Actual and potential (on-demand) cost for the instance over the window.",
        },
    },
    "elastigroup_events": {
        "description": (
            "Activity history of an Elastigroup: updates, scale-ups and scale-downs, spot "
            "interruptions and instance launches, one row per event."
        ),
        "docs_url": "https://docs.spot.io/api/?version=v3#operation/elastigroupAwsActivityEvents",
        "columns": {
            "groupId": "Identifier of the Elastigroup the event happened in.",
            "elastigroup_name": "Name of the Elastigroup the event happened in.",
            "eventType": "Type of the event (e.g. Update).",
            "createdAt": "Time at which the event happened.",
            "subEvents": "Details of the event: the sub-event type (e.g. scaleUp) and the new spot requests and instances.",
            "event_key": "Hash of the event content, used as the row identifier because Spot gives events no id.",
        },
    },
    "accounts": {
        "description": (
            "A Spot account in the organization. Resolves the accountId carried by elastigroups, "
            "Ocean clusters and cost rows. Listing all accounts needs an Organization Admin token."
        ),
        "docs_url": "https://docs.spot.io/api/?version=v3#operation/OrganizationsAndAccountsGetAccounts",
        "columns": {
            "accountId": "Unique identifier of the Spot account (e.g. act-12345678).",
            "organizationId": "Identifier of the Spot organization that owns the account.",
            "name": "Name of the account.",
            "providerExternalId": "Identifier of the connected cloud provider account (e.g. the AWS account id).",
        },
    },
    "ocean_cluster_nodes": {
        "description": (
            "A worker node currently running in an Ocean AWS Kubernetes cluster, with its instance "
            "details and the CPU, memory and GPU that workloads and headroom request on it."
        ),
        "docs_url": "https://docs.spot.io/api/?version=v3#operation/oceanAwsGetNodes",
        "columns": {
            "ocean_cluster_id": "Identifier of the Ocean cluster the node belongs to.",
            "instanceId": "AWS instance id of the node.",
            "instanceType": "AWS instance type of the node.",
            "availabilityZone": "AWS availability zone of the node.",
            "launchSpecId": "Identifier of the node's Virtual Node Group.",
            "launchSpecName": "Name of the node's Virtual Node Group.",
            "lifeCycle": "AWS lifecycle of the node (spot or on-demand).",
            "publicIp": "Public IP address of the node.",
            "nodeName": "Kubernetes node name.",
            "registrationStatus": "Registration status of the node in the cluster.",
            "workloadRequestedMilliCpu": "Milli CPUs that Kubernetes workloads request on the node.",
            "workloadRequestedMemoryInMiB": "Memory in MiB that Kubernetes workloads request on the node.",
            "workloadRequestedGpu": "GPUs that Kubernetes workloads request on the node.",
            "headroomRequestedMilliCpu": "Milli CPUs reserved for headroom on the node.",
            "headroomRequestedMemoryInMiB": "Memory in MiB reserved for headroom on the node.",
            "headroomRequestedGpu": "GPUs reserved for headroom on the node.",
            "allocatableMilliCpu": "Allocatable milli CPUs as registered in Kubernetes.",
            "allocatableMemoryInMiB": "Allocatable memory in MiB as registered in Kubernetes.",
            "allocatableGpu": "Allocatable GPUs as registered in Kubernetes.",
            "createdAt": "Time at which the node's instance was created.",
        },
    },
}
