from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

Transport = Literal["soap", "rest"]

# SOAP Retrieve has no page-size parameter: it returns up to 2,500 records per batch and signals
# continuation with OverallStatus=MoreDataAvailable plus a RequestID.
#
# REST `$pageSize` cap. The Asset and Interaction APIs both reject values above 50 on the
# collection endpoints we read, so we page everything in 50s.
REST_PAGE_SIZE = 50

# Tracking events share the TrackingEvent base type, so they retrieve the same core properties.
_TRACKING_EVENT_PROPERTIES = (
    "SendID",
    "SubscriberKey",
    "EventDate",
    "EventType",
    "BatchID",
    "TriggeredSendDefinitionObjectID",
    "PartnerKey",
)

_EVENT_PRIMARY_KEYS = ["SendID", "SubscriberKey", "EventDate"]


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class SalesforceMarketingCloudEndpointConfig:
    name: str
    # Marketing Cloud splits its data across two APIs: the legacy SOAP partner API (subscribers,
    # sends, tracking events, data extension metadata) and the newer REST APIs (assets, journeys,
    # campaigns). Both are first-class, so each endpoint declares which one it speaks.
    transport: Transport
    primary_keys: list[str]
    # SOAP `ObjectType` and the explicit `Properties` list the Retrieve asks for. The partner API
    # has no wildcard — every column must be named.
    object_type: Optional[str] = None
    properties: tuple[str, ...] = ()
    # REST collection path (relative to the tenant's rest_instance_url) and the response key
    # holding the rows.
    path: Optional[str] = None
    data_key: str = "items"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Property the SOAP `SimpleFilterPart` filters on when syncing incrementally. Only set where
    # the partner API genuinely filters server-side.
    soap_incremental_property: Optional[str] = None
    # Stable creation/occurrence timestamp to partition on. Never an updated-at column.
    partition_key: Optional[str] = None
    should_sync_default: bool = True

    @property
    def incremental_field_names(self) -> set[str]:
        return {f["field"] for f in self.incremental_fields}


SALESFORCE_MARKETING_CLOUD_ENDPOINTS: dict[str, SalesforceMarketingCloudEndpointConfig] = {
    "subscribers": SalesforceMarketingCloudEndpointConfig(
        name="subscribers",
        transport="soap",
        object_type="Subscriber",
        properties=(
            "ID",
            "SubscriberKey",
            "EmailAddress",
            "Status",
            "EmailTypePreference",
            "CreatedDate",
            "ModifiedDate",
            "UnsubscribedDate",
            "PartnerKey",
        ),
        primary_keys=["ID"],
        incremental_fields=[_datetime_incremental_field("ModifiedDate")],
        soap_incremental_property="ModifiedDate",
        partition_key="CreatedDate",
    ),
    "lists": SalesforceMarketingCloudEndpointConfig(
        name="lists",
        transport="soap",
        object_type="List",
        properties=(
            "ID",
            "ObjectID",
            "ListName",
            "Description",
            "Category",
            "Type",
            "ListClassification",
            "CreatedDate",
            "ModifiedDate",
            "PartnerKey",
        ),
        primary_keys=["ID"],
        incremental_fields=[_datetime_incremental_field("ModifiedDate")],
        soap_incremental_property="ModifiedDate",
    ),
    "sends": SalesforceMarketingCloudEndpointConfig(
        name="sends",
        transport="soap",
        object_type="Send",
        properties=(
            "ID",
            "EmailName",
            "Subject",
            "FromAddress",
            "FromName",
            "SendDate",
            "SentDate",
            "Status",
            "IsMultipart",
            "NumberSent",
            "NumberDelivered",
            "NumberTargeted",
            "NumberErrored",
            "UniqueOpens",
            "UniqueClicks",
            "HardBounces",
            "SoftBounces",
            "OtherBounces",
            "Unsubscribes",
            "MissingAddresses",
            "InvalidAddresses",
            "ExistingUndeliverables",
            "ExistingUnsubscribes",
            "Duplicates",
            "ForwardedEmails",
            "CreatedDate",
            "ModifiedDate",
            "PartnerKey",
        ),
        primary_keys=["ID"],
        incremental_fields=[_datetime_incremental_field("ModifiedDate")],
        soap_incremental_property="ModifiedDate",
        partition_key="CreatedDate",
    ),
    "sent_events": SalesforceMarketingCloudEndpointConfig(
        name="sent_events",
        transport="soap",
        object_type="SentEvent",
        properties=_TRACKING_EVENT_PROPERTIES,
        primary_keys=_EVENT_PRIMARY_KEYS,
        incremental_fields=[_datetime_incremental_field("EventDate")],
        soap_incremental_property="EventDate",
        partition_key="EventDate",
    ),
    "open_events": SalesforceMarketingCloudEndpointConfig(
        name="open_events",
        transport="soap",
        object_type="OpenEvent",
        properties=_TRACKING_EVENT_PROPERTIES,
        primary_keys=_EVENT_PRIMARY_KEYS,
        incremental_fields=[_datetime_incremental_field("EventDate")],
        soap_incremental_property="EventDate",
        partition_key="EventDate",
    ),
    "click_events": SalesforceMarketingCloudEndpointConfig(
        name="click_events",
        transport="soap",
        object_type="ClickEvent",
        properties=(*_TRACKING_EVENT_PROPERTIES, "URL", "URLID", "LinkName", "LinkContent"),
        # A subscriber can click several links in the same send, so the clicked URL is part of the key.
        primary_keys=[*_EVENT_PRIMARY_KEYS, "URLID"],
        incremental_fields=[_datetime_incremental_field("EventDate")],
        soap_incremental_property="EventDate",
        partition_key="EventDate",
    ),
    "bounce_events": SalesforceMarketingCloudEndpointConfig(
        name="bounce_events",
        transport="soap",
        object_type="BounceEvent",
        properties=(*_TRACKING_EVENT_PROPERTIES, "BounceCategory", "BounceType", "SMTPCode", "SMTPReason"),
        primary_keys=_EVENT_PRIMARY_KEYS,
        incremental_fields=[_datetime_incremental_field("EventDate")],
        soap_incremental_property="EventDate",
        partition_key="EventDate",
    ),
    "unsub_events": SalesforceMarketingCloudEndpointConfig(
        name="unsub_events",
        transport="soap",
        object_type="UnsubEvent",
        properties=(*_TRACKING_EVENT_PROPERTIES, "ListID", "IsMasterUnsubscribed"),
        # An unsubscribe is recorded per list, so the list is part of the key.
        primary_keys=[*_EVENT_PRIMARY_KEYS, "ListID"],
        incremental_fields=[_datetime_incremental_field("EventDate")],
        soap_incremental_property="EventDate",
        partition_key="EventDate",
    ),
    # Data extension *metadata*, not rows. Data extension rowsets are per-customer dynamic schemas
    # with no server-side incremental filter, so we expose the catalog rather than pretending to
    # sync arbitrary user-defined tables.
    "data_extensions": SalesforceMarketingCloudEndpointConfig(
        name="data_extensions",
        transport="soap",
        object_type="DataExtension",
        properties=(
            "ObjectID",
            "CustomerKey",
            "Name",
            "Description",
            "CategoryID",
            "IsSendable",
            "IsTestable",
            "CreatedDate",
            "ModifiedDate",
            "PartnerKey",
        ),
        primary_keys=["ObjectID"],
        incremental_fields=[_datetime_incremental_field("ModifiedDate")],
        soap_incremental_property="ModifiedDate",
        partition_key="CreatedDate",
    ),
    "data_extension_fields": SalesforceMarketingCloudEndpointConfig(
        name="data_extension_fields",
        transport="soap",
        object_type="DataExtensionField",
        properties=(
            "ObjectID",
            "CustomerKey",
            "Name",
            "FieldType",
            "DefaultValue",
            "MaxLength",
            "Scale",
            "IsRequired",
            "IsPrimaryKey",
            "Ordinal",
            "CreatedDate",
            "ModifiedDate",
            "DataExtension.CustomerKey",
        ),
        primary_keys=["ObjectID"],
    ),
    "assets": SalesforceMarketingCloudEndpointConfig(
        name="assets",
        transport="rest",
        path="/asset/v1/content/assets",
        primary_keys=["id"],
    ),
    "journeys": SalesforceMarketingCloudEndpointConfig(
        name="journeys",
        transport="rest",
        path="/interaction/v1/interactions",
        # A journey id is reused across versions, so both make up the key.
        primary_keys=["id", "version"],
    ),
    "campaigns": SalesforceMarketingCloudEndpointConfig(
        name="campaigns",
        transport="rest",
        path="/hub/v1/campaigns",
        primary_keys=["id"],
    ),
}

ENDPOINTS = tuple(SALESFORCE_MARKETING_CLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SALESFORCE_MARKETING_CLOUD_ENDPOINTS.items()
}
