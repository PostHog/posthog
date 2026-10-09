BASE_URL = "https://api.kisi.io"
PAGE_SIZE = 100
MAX_OFFSET = 20_000

ENDPOINTS = ("locks", "places", "users", "groups", "role_assignments", "controllers", "readers")
PRIMARY_KEYS = ["id"]
PARTITION_KEYS = ["created_at"]

AUTH_ERROR = "Kisi rejected the API key. Create a new key in My Account > API and reconnect."
PERMISSION_ERROR = "The Kisi API key cannot read this resource. Check the account permissions in Kisi."
OFFSET_ERROR = "Kisi's pagination limit prevents a complete import. Contact Kisi support for an export of this table."
