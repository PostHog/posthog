from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField

ANVIL_GRAPHQL_URL = "https://graphql.useanvil.com"

# Anvil caps `limit` at 500 rows per page; 100 keeps each response's size moderate while the
# rate limit (4 requests/second on development keys) bounds request throughput anyway.
PAGE_SIZE = 100

# Selections stay on metadata scalars. Filled PDFs, signed documents, submission form data
# (`payload`, `files`), and capability URLs (`continueURL`, `pin`) must never reach the
# warehouse, so they are not selected.
_ORGANIZATION_ITEM_FIELDS = """
eid
name
slug
isPersonal
isSubscribed
useTestSignatureProvider
signatureProviderType
availableSignatureProviderTypes
isSso
remainingUsers
logoURL
stylesheetURL
billingEmail
supportEmail
createdAt
updatedAt
"""

_CAST_ITEM_FIELDS = """
eid
type
name
title
isTemplate
versionNumber
latestDraftVersionNumber
publishedNumber
publishedAt
hasUnpublishedChanges
hasBeenPublished
allowedAliasIds
createdAt
updatedAt
archivedAt
"""

_WELD_ITEM_FIELDS = """
eid
slug
name
visibility
versionNumber
latestDraftVersionNumber
publishedNumber
publishedAt
hasUnpublishedChanges
hasBeenPublished
hasSigners
signatureProviderType
availableSignatureProviderTypes
submissionsCount
createdAt
updatedAt
archivedAt
expiresAt
"""

_WELD_DATA_ITEM_FIELDS = """
eid
displayTitle
status
isTest
isExpired
isComplete
isAllComplete
completionPercentage
numberRemainingSigners
hasSigners
payloadCanBeUpdated
weldVersionId
createdAt
updatedAt
dataUpdatedAt
expiresAt
archivedAt
embeddedAt
"""

_SIGNER_ITEM_FIELDS = """
eid
aliasId
status
provider
name
email
routingOrder
signatureExperience
signActionType
clientUserId
createdAt
updatedAt
completedAt
"""

_ETCH_PACKET_ITEM_FIELDS = f"""
eid
name
status
isTest
allowUpdates
containsFillData
numberRemainingSigners
detailsURL
createdAt
updatedAt
archivedAt
completedAt
sentAt
embeddedAt
documentGroup {{
eid
status
provider
currentRoutingStep
createdAt
updatedAt
completedAt
signers {{
{_SIGNER_ITEM_FIELDS}
}}
}}
"""

_SUBMISSION_ITEM_FIELDS = """
eid
status
currentStep
totalSteps
completionPercentage
isExcluded
touchedByUser
forge {
eid
name
}
signer {
eid
}
createdAt
updatedAt
completedAt
"""

# Log `metadata` and the actor's location are free-form and can carry personal data, so
# events keep only what happened, when, and which object ids were involved.
_WELD_DATA_LOG_EVENT_ITEM_FIELDS = """
eid
action
user {
eid
}
submission {
eid
}
createdAt
"""

_ETCH_LOG_EVENT_ITEM_FIELDS = """
eid
action
fileId
user {
eid
}
signer {
eid
}
createdAt
"""


@dataclass(frozen=True)
class AnvilNestedList:
    # Paged parent walk whose items carry the child list. Anvil exposes these children only as
    # unpaginated lists on a single parent, so selecting them inside the parent page avoids a
    # request per parent.
    parent: Literal["weld_datas", "etch_packets"]
    # Path from a parent item to the child list, e.g. ("documentGroup", "signers").
    path: tuple[str, ...]
    # Column stamped onto each child row with its parent item's eid.
    parent_key: str


@dataclass(frozen=True)
class AnvilEndpointConfig:
    # GraphQL selection for one row of this endpoint.
    item_fields: str
    # Paginated Page field on Organization (`casts`, `welds`, `etchPackets`); None for the
    # single-query organizations endpoint and the per-weld fan-out.
    organization_page_field: str | None = None
    # Fan out one `weld(eid: ...) { weldDatas }` page walk per weld across every organization.
    fan_out_weld_datas: bool = False
    # Child lists read from inside parent pages; walked in order when there is more than one.
    nested_lists: tuple[AnvilNestedList, ...] = ()
    # Anvil eids are 20-character object identifiers unique across their system, so a row's
    # own eid is a table-wide key even for fan-out children.
    primary_keys: list[str] = field(default_factory=lambda: ["eid"])
    # Stable creation timestamp for partitioning; None for the tiny organizations table.
    partition_key: str | None = "createdAt"
    description: str | None = None


ANVIL_ENDPOINTS: dict[str, AnvilEndpointConfig] = {
    "organizations": AnvilEndpointConfig(
        item_fields=_ORGANIZATION_ITEM_FIELDS,
        partition_key=None,
        description="The Anvil organizations your API key's user belongs to",
    ),
    "casts": AnvilEndpointConfig(
        item_fields=_CAST_ITEM_FIELDS,
        organization_page_field="casts",
        description="PDF templates, fetched per organization",
    ),
    "welds": AnvilEndpointConfig(
        item_fields=_WELD_ITEM_FIELDS,
        organization_page_field="welds",
        description="Workflow definitions, fetched per organization",
    ),
    "weld_datas": AnvilEndpointConfig(
        item_fields=_WELD_DATA_ITEM_FIELDS,
        fan_out_weld_datas=True,
        description=(
            "Workflow submissions, fetched per workflow (one page walk per weld), "
            "so syncs scale with the number of workflows"
        ),
    ),
    "etch_packets": AnvilEndpointConfig(
        item_fields=_ETCH_PACKET_ITEM_FIELDS,
        organization_page_field="etchPackets",
        description="E-signature packets with their signer status, fetched per organization",
    ),
    "submissions": AnvilEndpointConfig(
        item_fields=_SUBMISSION_ITEM_FIELDS,
        nested_lists=(AnvilNestedList(parent="weld_datas", path=("submissions",), parent_key="weldDataEid"),),
        description=(
            "Webform submissions within each workflow submission, with their step progress and completion "
            "times. Form answers are not synced"
        ),
    ),
    "workflow_signers": AnvilEndpointConfig(
        item_fields=_SIGNER_ITEM_FIELDS,
        nested_lists=(
            AnvilNestedList(parent="weld_datas", path=("documentGroup", "signers"), parent_key="weldDataEid"),
        ),
        description="Signers of each workflow submission sent for signature, with their signing status",
    ),
    "weld_data_log_events": AnvilEndpointConfig(
        item_fields=_WELD_DATA_LOG_EVENT_ITEM_FIELDS,
        nested_lists=(AnvilNestedList(parent="weld_datas", path=("weldDataLogEvents",), parent_key="weldDataEid"),),
        description="Actions taken while filling workflow webforms, such as views, saves, and completions",
    ),
    "etch_log_events": AnvilEndpointConfig(
        item_fields=_ETCH_LOG_EVENT_ITEM_FIELDS,
        nested_lists=(
            AnvilNestedList(parent="etch_packets", path=("etchLogEvents",), parent_key="etchPacketEid"),
            AnvilNestedList(parent="weld_datas", path=("etchLogEvents",), parent_key="weldDataEid"),
        ),
        description=(
            "Signing actions on e-signature packets and workflow submissions, such as views, signatures, "
            "downloads, and voids"
        ),
    ),
}

ENDPOINTS = tuple(ANVIL_ENDPOINTS.keys())

# The list fields take `dateStart`/`dateEnd` (welds, etchPackets) and `fromDate`/`toDate`
# (weldDatas) arguments, but Anvil does not document which timestamp they filter on or the
# ordering they imply, so no endpoint advertises a cursor and every table syncs as full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
