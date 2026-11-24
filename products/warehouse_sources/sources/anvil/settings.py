from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.sources.sdk import IncrementalField

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

# User `preferences`, `onboarding`, and `extra` are free-form JSON, so memberships keep only the
# user's identity and account fields.
_ORGANIZATION_USER_ITEM_FIELDS = """
role
externalId
user {
eid
email
name
firstName
lastName
role
verifiedEmail
createdAt
updatedAt
}
createdAt
updatedAt
"""

# Template `config` and `signers` are free-form JSON that can hold draft signer names and
# emails, so templates keep their flags and the ids of the casts and packets they link.
_ETCH_TEMPLATE_ITEM_FIELDS = """
eid
name
isFree
isRepeatable
casts {
eid
}
etchPackets {
eid
}
createdAt
updatedAt
"""

# Forge `config`, `fieldInfo`, and `examplePayload` are large webform definitions and sample
# answers, so forges keep their version and publish state and the workflow they belong to.
_FORGE_ITEM_FIELDS = """
eid
name
slug
isRequired
versionNumber
versionId
latestDraftVersionNumber
publishedNumber
publishedAt
hasUnpublishedChanges
hasBeenPublished
weld {
eid
}
createdAt
updatedAt
archivedAt
"""

_ORGANIZATION_USER_INVITE_ITEM_FIELDS = """
eid
role
externalId
name
email
acceptedAt
revokedAt
createdAt
updatedAt
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
    # Read the unpaginated `organizationUsers` list of every organization in the single
    # organizations query.
    organization_users: bool = False
    # Unpaginated list field on Organization (`forges`, `organizationUserInvites`), read for
    # every organization in the single organizations query.
    organization_list_field: str | None = None
    # List field on Organization that takes `limit` and `offset` but returns a bare list with no
    # page metadata (`etchTemplates`).
    organization_offset_list_field: str | None = None
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
    "organization_users": AnvilEndpointConfig(
        item_fields=_ORGANIZATION_USER_ITEM_FIELDS,
        organization_users=True,
        # A membership has no eid of its own; a user holds at most one membership per organization.
        primary_keys=["organizationEid", "userEid"],
        description="Members of each Anvil organization with their role and the dates they joined",
    ),
    "organization_user_invites": AnvilEndpointConfig(
        item_fields=_ORGANIZATION_USER_INVITE_ITEM_FIELDS,
        organization_list_field="organizationUserInvites",
        description="Invitations to join each Anvil organization, with their role and when they were accepted or revoked",
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
    "forges": AnvilEndpointConfig(
        item_fields=_FORGE_ITEM_FIELDS,
        organization_list_field="forges",
        description="Webforms with their version and publish state, fetched per organization",
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
    "etch_templates": AnvilEndpointConfig(
        item_fields=_ETCH_TEMPLATE_ITEM_FIELDS,
        organization_offset_list_field="etchTemplates",
        description="E-signature templates that packets are created from, fetched per organization",
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
