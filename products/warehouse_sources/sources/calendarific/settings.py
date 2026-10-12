ENDPOINTS = ("holidays", "countries", "languages")

AUTH_ERROR = "Calendarific rejected your API key. Copy the key from your Calendarific dashboard and reconnect."
SUBSCRIPTION_ERROR = "Your Calendarific subscription has expired. Renew it in your Calendarific account and reconnect."

NON_RETRYABLE_ERRORS = {
    "401 Client Error": AUTH_ERROR,
    "403 Client Error": SUBSCRIPTION_ERROR,
    "auth failed": AUTH_ERROR,
}
