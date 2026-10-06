BASE_URL = "https://api.synthesia.io"
PAGE_SIZE = 100

ENDPOINTS = {
    "videos": "videos",
    "templates": "templates",
    "webhooks": "webhooks",
}

AUTH_ERROR = (
    "Synthesia rejected the API key. Create an active key with the Legacy (v2) scope in Developers > API keys. "
    "API access requires a Creator or Enterprise plan."
)
