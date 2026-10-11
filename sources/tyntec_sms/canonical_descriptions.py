from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://api.tyntec.com/reference/sms/current.html"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "MessageStatus": {
        "description": "Delivery status of a sent SMS message, looked up by its request ID. tyntec retains statuses for 3 months after a final delivery state is reached.",
        "docs_url": _DOCS_URL,
        "columns": {
            "requestId": "The unique identifier provided for each messaging request.",
            "from": "The phone number of the sending party in international format, if available.",
            "to": "The number provided by tyntec that received the respective message, in international format.",
            "status": "The message status, e.g. DELIVERED.",
            "submitDate": "The date when the message was sent out by tyntec for delivery.",
            "doneDate": "The timestamp when the message was successfully delivered.",
            "errorCode": "The GSM error code for an unsuccessful attempt.",
            "errorReason": "The reason for an unsuccessful attempt.",
            "mccmnc": "Representative IMSI prefix of the target network.",
            "parts": "Per-part delivery details (delivery state, part ID, price, status text) for concatenated messages.",
            "overallPrice": "The overall sum of prices for all parts of this message.",
            "priceEffective": "The date when the price became active.",
            "reference": "Custom reference that marks the delivery report.",
            "size": "The number of concatenated SMS parts.",
            "href": "The URL of the accepted message.",
            "ttid": "The tyntec operator's ID.",
        },
    },
    "Contacts": {
        "description": "A contact registered with tyntec's BYON (bring-your-own-number) contact service.",
        "docs_url": _DOCS_URL,
        "columns": {
            "companyAddress": "Company's postal address.",
            "companyName": "Company's name.",
            "contactEmail": "E-mail address.",
            "contactName": "Requestor's name.",
            "contactPhone": "Requestor's phone number.",
            "contactTitle": "Requestor's title.",
            "friendlyName": "Friendly name of the contact.",
        },
    },
    "PhoneNumbers": {
        "description": "A phone number registered in tyntec's BYON phone book (capped at 3000 entries per account).",
        "docs_url": _DOCS_URL,
        "columns": {
            "accountId": "The account that created this entry.",
            "contactId": "Contact ID of this entry.",
            "friendlyName": "Friendly name of this entry.",
            "requestId": "Request ID of this entry.",
            "status": "Status of this entry.",
        },
    },
    "PhoneRegistrations": {
        "description": "A phone number provisioning request in tyntec's BYON number service.",
        "docs_url": _DOCS_URL,
        "columns": {
            "accountId": "The account that created this entry.",
            "contactId": "Contact ID of this entry.",
            "friendlyName": "Friendly name of this entry.",
            "requestId": "Request ID of this entry.",
            "status": "Status of this entry.",
        },
    },
}
