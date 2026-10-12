from posthog.dataclasses import frozen

REGION_HOSTS = {
    "global": "api.meraki.com",
    "canada": "api.meraki.ca",
    "china": "api.meraki.cn",
    "india": "api.meraki.in",
    "us_government": "api.gov-meraki.com",
}


@frozen
class MerakiEndpoint:
    path: str
    primary_key: str
    page_size: int = 1000


ENDPOINTS = {
    "networks": MerakiEndpoint(path="networks", primary_key="id"),
    "devices": MerakiEndpoint(path="devices", primary_key="serial"),
    "inventory_devices": MerakiEndpoint(path="inventory/devices", primary_key="serial"),
    "uplink_statuses": MerakiEndpoint(path="uplinks/statuses", primary_key="serial"),
    "assurance_alerts": MerakiEndpoint(path="assurance/alerts", primary_key="id", page_size=300),
}

AUTH_ERROR = "Cisco Meraki rejected your API key. Check the key and selected region."
PERMISSION_ERROR = (
    "Your API key cannot read this resource. Check your Meraki administrator permissions and organization ID."
)
NOT_FOUND_ERROR = "Cisco Meraki could not find this resource. Check your organization ID and selected region."
REGION_ERROR = "Select a supported Cisco Meraki region."
ORGANIZATION_ERROR = "Enter a valid Meraki organization ID. Use only letters, numbers, underscores, or hyphens."
