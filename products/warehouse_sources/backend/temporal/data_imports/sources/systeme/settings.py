from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://api.systeme.io/api/"
PAGE_SIZE = 100

ENDPOINTS = {
    "contacts": "contacts",
    "tags": "tags",
    "newsletters": "mailing/newsletters",
    "courses": "school/courses",
    "enrollments": "school/enrollments",
    "communities": "community/communities",
    "memberships": "community/memberships",
    "digital_products": "payment/digital-products",
    "physical_products": "payment/physical-products",
    "campaigns": "mailing/campaigns",
    "campaign_steps": "mailing/campaigns/{campaignId}/steps",
}

# Child endpoint -> parent endpoint whose `id` fills the child path's `{campaignId}`.
FANOUT_PARENTS = {"campaign_steps": "campaigns"}

INCREMENTAL_FIELDS = {"contacts": [incremental_field("registeredAt")]}
PARTITION_KEYS = {
    "contacts": "registeredAt",
    "tags": "createdAt",
    "digital_products": "createdAt",
    "physical_products": "createdAt",
}

AUTH_ERROR = "Systeme.io rejected your API key. Create a new key in your profile settings and reconnect."
PERMISSION_ERROR = "Your API key cannot access this Systeme.io resource. Check your account permissions and reconnect."
NON_RETRYABLE_ERRORS = {
    "401 Client Error": AUTH_ERROR,
    "403 Client Error": PERMISSION_ERROR,
}
