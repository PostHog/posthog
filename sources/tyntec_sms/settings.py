from products.warehouse_sources.backend.types import IncrementalField

MESSAGE_STATUS = "MessageStatus"
CONTACTS = "Contacts"
PHONE_NUMBERS = "PhoneNumbers"
PHONE_REGISTRATIONS = "PhoneRegistrations"

ENDPOINTS = (
    MESSAGE_STATUS,
    CONTACTS,
    PHONE_NUMBERS,
    PHONE_REGISTRATIONS,
)

# tyntec's SMS API exposes no server-side timestamp filter on any endpoint, so every table
# is full-refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}

# Path + the response-body key wrapping the row list for each BYON list endpoint. Responses
# are single wrapper objects, e.g. {"contacts": [...], "size": 2}.
LIST_ENDPOINTS: dict[str, tuple[str, str]] = {
    CONTACTS: ("/byon/contacts/v1", "contacts"),
    PHONE_NUMBERS: ("/byon/phonebook/v1/numbers", "provisioningRequests"),
    PHONE_REGISTRATIONS: ("/byon/provisioning/v1", "provisioningRequests"),
}

# Message statuses are fetched one request id at a time — tyntec has no bulk message-list
# endpoint (see https://api.tyntec.com/reference/sms/current.html).
MESSAGE_STATUS_PATH = "/messaging/v1/messages/{request_id}"

PRIMARY_KEYS: dict[str, list[str]] = {
    MESSAGE_STATUS: ["requestId"],
    # The OpenAPI schemas omit the id fields on the BYON list entities, but the read/edit/delete
    # endpoints key on contactId / phoneNumber, so live rows carry them. These tables are
    # full-refresh only (replace), so the keys never drive a Delta merge.
    CONTACTS: ["contactId"],
    PHONE_NUMBERS: ["phoneNumber"],
    PHONE_REGISTRATIONS: ["requestId"],
}

# Documented hard cap on the phonebook listing. We request the whole cap in one page rather
# than paginating: the API documents `page`/`size` params only on this endpoint, without
# defining the base page or whether `page` is honored, so paginating risks re-fetching the
# same rows forever.
PHONEBOOK_MAX_SIZE = 3000

# Each configured request id costs one serial HTTP request per sync, so cap the list to keep
# a single source from occupying an import worker with unbounded work.
MAX_REQUEST_IDS = 1000

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    MESSAGE_STATUS: "Delivery status of sent SMS messages, fetched per request ID configured on the source.",
    CONTACTS: "Contacts registered with tyntec's BYON (bring-your-own-number) contact service.",
    PHONE_NUMBERS: "Phone numbers registered in tyntec's BYON phone book.",
    PHONE_REGISTRATIONS: "Phone number provisioning requests in tyntec's BYON number service.",
}

# The BYON endpoints are in tyntec's official SMS API spec, but the live gateway answered
# 404 ("no Route matched") to authenticated and unauthenticated probes at implementation
# time — they appear to require the BYON service on the account (or have been sunset
# upstream). Default them to unselected so a fresh source doesn't fail its first sync on
# tables the account can't reach.
SHOULD_SYNC_DEFAULT: dict[str, bool] = {
    MESSAGE_STATUS: True,
    CONTACTS: False,
    PHONE_NUMBERS: False,
    PHONE_REGISTRATIONS: False,
}
