from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logicmonitor.settings import API_DOCS_URL

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "alerts": {
        "description": "Alerts for monitored resources, including active and cleared alerts within the account's retention period.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Unique alert identifier.",
            "startEpoch": "Time when the alert started, in Unix seconds.",
            "endEpoch": "Time when the alert ended, in Unix seconds.",
            "severity": "Severity: 2 means warning, 3 means error, and 4 means critical.",
            "acked": "Whether a user acknowledged the alert.",
            "cleared": "Whether the alert cleared.",
            "monitorObjectId": "Identifier of the monitored object.",
            "monitorObjectName": "Name of the monitored object.",
            "resourceTemplateName": "Name of the DataSource in alert.",
            "instanceName": "Name of the instance in alert.",
            "dataPointName": "Name of the datapoint in alert.",
        },
    },
    "devices": {
        "description": "Monitored device inventory and collector assignments.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Unique device identifier.",
            "name": "Hostname or IP address of the device.",
            "displayName": "Device name shown in LogicMonitor.",
            "createdOn": "Time when the device was added, in Unix seconds.",
            "updatedOn": "Time when the device last changed, in Unix seconds.",
            "preferredCollectorId": "Identifier of the preferred collector for this device.",
            "hostGroupIds": "Comma-separated identifiers of groups that contain this device.",
        },
    },
    "device_groups": {
        "description": "Groups that organize monitored devices.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Unique device group identifier.",
            "name": "Device group name.",
            "fullPath": "Group path, including parent groups.",
            "parentId": "Identifier of the parent group.",
            "createdOn": "Time when the group was created, in Unix seconds.",
        },
    },
    "collectors": {
        "description": "Collectors, their availability, and the number of devices they monitor.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Unique collector identifier.",
            "hostname": "Hostname of the device that runs the collector.",
            "collectorGroupId": "Identifier of the collector's group.",
            "numberOfHosts": "Number of devices monitored by the collector.",
            "isDown": "Whether the collector is currently down.",
            "build": "Collector version.",
        },
    },
    "sdts": {
        "description": "Scheduled downtime for resources and monitoring components.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Scheduled downtime identifier, including its resource type prefix.",
            "type": "Type of resource covered by this scheduled downtime.",
            "sdtType": "Schedule type, such as one-time, daily, weekly, or monthly.",
            "startDateTime": "Start of the scheduled downtime, in Unix milliseconds.",
            "endDateTime": "End of the scheduled downtime, in Unix milliseconds.",
        },
    },
    "websites": {
        "description": "Website monitors and their alert settings.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Unique website monitor identifier.",
            "name": "Website monitor name.",
            "type": "Check type: pingcheck or webcheck.",
            "overallAlertLevel": "Alert severity when the website fails its configured checks.",
            "disableAlerting": "Whether alerting is disabled for this website.",
        },
    },
}
