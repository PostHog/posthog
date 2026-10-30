from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

API_VERSION = "3"
API_DOCS_URL = "https://www.logicmonitor.com/support/rest-api-v3-swagger-documentation"
PAGE_SIZE = 1000
MAX_ALERTS_PER_WINDOW = 10000

ENDPOINTS: dict[str, str] = {
    "alerts": "alert/alerts",
    "devices": "device/devices",
    "device_groups": "device/groups",
    "collectors": "setting/collector/collectors",
    "collector_groups": "setting/collector/groups",
    "sdts": "sdt/sdts",
    "websites": "website/websites",
    "ops_notes": "setting/opsnotes",
    "audit_logs": "setting/accesslogs",
    "device_datasources": "device/devices/{deviceId}/devicedatasources",
    # Lists every datasource instance of a device, so one request per device covers all of its datasources.
    "device_datasource_instances": "device/devices/{deviceId}/instances",
    "device_sdt_history": "device/devices/{deviceId}/historysdts",
}

# Select inventory fields because device properties and collector configuration can contain credentials.
FIELDS: dict[str, str] = {
    "devices": "id,name,displayName,description,createdOn,updatedOn,preferredCollectorId,hostGroupIds,disableAlerting",
    "device_groups": "id,name,description,fullPath,parentId,createdOn,disableAlerting",
    "collectors": "id,hostname,description,createdOn,updatedOn,collectorGroupId,numberOfHosts,isDown,build",
    "collector_groups": (
        "id,name,description,createOn,platform,numOfCollectors,numOfHosts,numOfInstances,autoBalance,"
        "autoBalanceStrategy,mismatchVersion"
    ),
    "websites": "id,name,description,type,overallAlertLevel,disableAlerting",
    "device_datasources": (
        "id,deviceId,deviceName,deviceDisplayName,dataSourceId,dataSourceName,dataSourceDisplayName,"
        "dataSourceDescription,dataSourceType,collectMethod,groupName,isMultiple,instanceNumber,"
        "monitoringInstanceNumber,alertStatus,alertStatusPriority,alertDisableStatus,sdtStatus,"
        "stopMonitoring,autoDiscovery,status,createdOn,updatedOn,assignedOn"
    ),
    "device_datasource_instances": (
        "id,name,displayName,description,deviceId,deviceDisplayName,deviceDataSourceId,dataSourceId,"
        "dataSourceType,groupId,groupName,collectorId,wildValue,wildValue2,stopMonitoring,disableAlerting,"
        "isUNCInstance,lockDescription"
    ),
}
PRIMARY_KEYS = ["id"]


def device_fanout(child_fields: str | None, *, include_device_id: bool = False) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="devices",
        resolve_param="deviceId",
        resolve_field="id",
        include_from_parent=["id"] if include_device_id else [],
        parent_field_renames={"id": "deviceId"} if include_device_id else {},
        parent_params={"fields": "id"},
        child_params={"fields": child_fields} if child_fields else {},
        # A device deleted after the device list was read has no children left to sync.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )


DEVICE_FANOUTS: dict[str, DependentEndpointConfig] = {
    "device_datasources": device_fanout(FIELDS["device_datasources"]),
    "device_datasource_instances": device_fanout(FIELDS["device_datasource_instances"]),
    # SDT history rows name the SDT target in itemId, which can be a device group, so the device id comes from the parent.
    "device_sdt_history": device_fanout(None, include_device_id=True),
}
# Device datasource, instance, and SDT history ids are only documented per device.
FANOUT_PRIMARY_KEYS = ["deviceId", "id"]

# Audit log entries never change after they are written, so new entries can be read by their time.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "audit_logs": [
        {
            "label": "happenedOn",
            "type": IncrementalFieldType.Integer,
            "field": "happenedOn",
            "field_type": IncrementalFieldType.Integer,
        }
    ],
}
