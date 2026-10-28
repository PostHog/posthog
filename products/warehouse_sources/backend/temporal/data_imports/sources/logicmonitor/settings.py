from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)

API_VERSION = "3"
API_DOCS_URL = "https://www.logicmonitor.com/support/rest-api-v3-swagger-documentation"
PAGE_SIZE = 1000
MAX_ALERTS_PER_WINDOW = 10000

ENDPOINTS: dict[str, str] = {
    "alerts": "alert/alerts",
    "devices": "device/devices",
    "device_groups": "device/groups",
    "collectors": "setting/collector/collectors",
    "sdts": "sdt/sdts",
    "websites": "website/websites",
    "device_datasources": "device/devices/{deviceId}/devicedatasources",
    # Lists every datasource instance of a device, so one request per device covers all of its datasources.
    "device_datasource_instances": "device/devices/{deviceId}/instances",
}

# Select inventory fields because device properties and collector configuration can contain credentials.
FIELDS: dict[str, str] = {
    "devices": "id,name,displayName,description,createdOn,updatedOn,preferredCollectorId,hostGroupIds,disableAlerting",
    "device_groups": "id,name,description,fullPath,parentId,createdOn,disableAlerting",
    "collectors": "id,hostname,description,createdOn,updatedOn,collectorGroupId,numberOfHosts,isDown,build",
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

DEVICE_FANOUTS: dict[str, DependentEndpointConfig] = {
    name: DependentEndpointConfig(
        parent_name="devices",
        resolve_param="deviceId",
        resolve_field="id",
        include_from_parent=[],
        parent_params={"fields": "id"},
        child_params={"fields": FIELDS[name]},
        # A device deleted after the device list was read has no children left to sync.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )
    for name in ("device_datasources", "device_datasource_instances")
}
# Device datasource and instance ids are only documented per device.
FANOUT_PRIMARY_KEYS = ["deviceId", "id"]
