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
}

# Select inventory fields because device properties and collector configuration can contain credentials.
FIELDS: dict[str, str] = {
    "devices": "id,name,displayName,description,createdOn,updatedOn,preferredCollectorId,hostGroupIds,disableAlerting",
    "device_groups": "id,name,description,fullPath,parentId,createdOn,disableAlerting",
    "collectors": "id,hostname,description,createdOn,updatedOn,collectorGroupId,numberOfHosts,isDown,build",
    "websites": "id,name,description,type,overallAlertLevel,disableAlerting",
}
PRIMARY_KEYS = ["id"]
