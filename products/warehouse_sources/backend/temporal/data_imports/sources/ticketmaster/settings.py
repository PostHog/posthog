API_DOCS_URL = "https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/"
ENDPOINTS = {"events": "events.json", "attractions": "attractions.json", "venues": "venues.json"}
PRIMARY_KEYS = ["id"]
PAGE_SIZE = 200
MAX_RESULTS = 1000

AUTH_ERRORS = {
    401: "Ticketmaster rejected your API key. Copy a valid key from the Ticketmaster Developer Portal.",
    403: "Ticketmaster denied access. Check that your API key has access to the Discovery API.",
}
RESULT_LIMIT_ERROR = (
    "Ticketmaster search exceeds 1,000 results. Use a more specific search keyword and start a new sync."
)
KEYWORD_ERROR = "Enter a search keyword to limit the Ticketmaster results."
