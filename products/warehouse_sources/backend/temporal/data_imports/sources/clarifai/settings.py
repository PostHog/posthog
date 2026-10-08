DEFAULT_API_HOST = "https://api.clarifai.com"
PAGE_SIZE = 128
ENDPOINTS = ("models", "workflows", "datasets", "concepts")
PRIMARY_KEYS = ["id"]

AUTH_ERROR = "Clarifai rejected the token. Check your personal access token and app access."
PERMISSION_ERROR = (
    "The Clarifai token lacks permission. Grant read access to the selected resource and its list endpoint."
)
HOST_ERROR = "Enter a public HTTPS API host without a path, query, or credentials."
RESOURCE_ERROR = "Clarifai could not find the resource. Check the user ID and app ID."
