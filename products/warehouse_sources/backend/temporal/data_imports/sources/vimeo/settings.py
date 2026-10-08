BASE_URL = "https://api.vimeo.com"
PAGE_SIZE = 100
PRIMARY_KEYS = ["uri"]

ENDPOINTS = {
    "videos": "/me/videos",
    "folders": "/me/projects",
    "showcases": "/me/albums",
}

AUTH_ERROR = "Vimeo rejected your access token. Generate an authenticated token for your account and reconnect."
PERMISSION_ERROR = (
    "Vimeo denied access. Check your account permissions and enable the token's public and private scopes."
)
