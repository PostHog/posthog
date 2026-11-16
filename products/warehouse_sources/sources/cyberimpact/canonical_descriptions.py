from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_DOCS = "https://api.cyberimpact.com/docs"

_MEMBER_COLUMNS = {
    "id": "Unique numerical ID of the member.",
    "email": "Email address of the member.",
    "firstname": "First name of the member.",
    "lastname": "Last name of the member.",
    "company": "Company of the member.",
    "gender": "Gender of the member: m, f or o.",
    "language": "Language of the member: en_ca or fr_ca.",
    "joinedOn": "Time the member was added to the account.",
    "updatedOn": "Time the member was last updated.",
    "consentType": "Type of consent the account holds for the member, for example implied.",
    "postalCode": "Postal code of the member.",
    "country": "ISO 3166-1 alpha-2 country code of the member.",
    "note": "Free-text note on the member.",
    "birthdate": "Birth date of the member.",
    "customFields": "Custom field values of the member, keyed by custom field ID.",
}

_RECIPIENT_COLUMNS = {
    "mailing_id": "ID of the mailing.",
    "idMember": "ID of the member. Null when the member no longer exists.",
    **{key: value for key, value in _MEMBER_COLUMNS.items() if key != "id"},
}

_MAILING_COLUMNS = {
    "id": "Unique numerical ID of the mailing.",
    "subject": "Subject line of the mailing.",
    "language": "Language of the mailing: en_ca or fr_ca.",
    "recipientsCount": "Number of recipients of the mailing.",
    "mailFrom": "Sender email address of the mailing.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "members": {
        "description": "Subscribed members (contacts) of the account, both in groups and in no group.",
        "docs_url": _DOCS,
        "columns": {
            **_MEMBER_COLUMNS,
            "mailingsReceived": "Number of mailings the member received.",
            "mailingsOpened": "Number of mailings the member opened.",
            "mailingsClicked": "Number of mailings in which the member clicked a link.",
        },
    },
    "unsubscribed_members": {
        "description": "Members who unsubscribed from the account's mailings.",
        "docs_url": _DOCS,
        "columns": {
            **{key: value for key, value in _MEMBER_COLUMNS.items() if key != "id"},
            "unsubscribedOn": "Time the member unsubscribed.",
        },
    },
    "bounced_members": {
        "description": "Members for whom the last mailing sent to them returned a hard bounce.",
        "docs_url": _DOCS,
        "columns": {
            **{key: value for key, value in _MEMBER_COLUMNS.items() if key != "id"},
            "hardBouncedOn": "Time of the hard bounce.",
        },
    },
    "groups": {
        "description": "Groups (mailing lists) of the account.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique numerical ID of the group.",
            "title": "Name of the group.",
            "isPublic": "Whether the group is public.",
            "membersCount": "Number of members in the group.",
            "mailingsCount": "Number of mailings sent to the group.",
            "createdOn": "Time the group was created.",
            "isDynamic": "Whether the group is dynamic.",
        },
    },
    "group_members": {
        "description": "Members of each group, one row per group and member.",
        "docs_url": _DOCS,
        "columns": {"group_id": "ID of the group.", **_MEMBER_COLUMNS},
    },
    "custom_fields": {
        "description": "Custom member fields defined in the account.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique numerical ID of the custom field. Keys of the members' customFields use it.",
            "name": "Name of the custom field.",
            "type": "Type of the custom field: text, date, integer or decimal number.",
        },
    },
    "sent_mailings": {
        "description": "Sent mailings, without archived mailings.",
        "docs_url": _DOCS,
        "columns": {**_MAILING_COLUMNS, "startedOn": "Time the sending started."},
    },
    "scheduled_mailings": {
        "description": "Mailings scheduled to be sent.",
        "docs_url": _DOCS,
        "columns": {**_MAILING_COLUMNS, "scheduledOn": "Time the mailing is scheduled to be sent."},
    },
    "archived_mailings": {
        "description": "Archived mailings.",
        "docs_url": _DOCS,
        "columns": {
            **_MAILING_COLUMNS,
            "startedOn": "Time the sending started.",
            "archivedOn": "Time the mailing was archived.",
        },
    },
    "mailing_stats": {
        "description": "Details and delivery, open and click statistics of each sent mailing.",
        "docs_url": _DOCS,
        "columns": {
            **_MAILING_COLUMNS,
            "startedOn": "Time the sending started.",
            "scheduledOn": "Time the mailing was scheduled to be sent.",
            "replyTo": "Reply-to email address of the mailing.",
            "bodyHtml": "HTML body of the mailing.",
            "bodyText": "Plain text body of the mailing.",
            "emailsSent": "Number of emails sent.",
            "emailsDelivered": "Number of emails delivered.",
            "emailsStopped": "Number of emails stopped before delivery.",
            "views": "Number of recipients who opened the mailing.",
            "clicks": "Number of recipients who clicked a link in the mailing.",
            "sentToFriend": "Number of times the mailing was forwarded to a friend.",
            "incorrectAddresses": "Number of recipients with an incorrect address.",
            "technicalProblems": "Number of emails that failed because of a technical problem.",
            "deliveryRate": "Share of sent emails that were delivered.",
            "clickRate": "Share of recipients who clicked a link.",
            "viewRate": "Share of recipients who opened the mailing.",
            "status": "Status of the mailing, for example sent.",
            "fromName": "Sender name of the mailing.",
            "mailingStatistics": "Statistics mode: detailed, or anonymized for anonymous opens and clicks.",
            "links": "Links in the mailing with their unique and total click counts.",
            "recipientGroups": "Groups the mailing was sent to.",
            "viewOnlineURL": "URL of the online version of the mailing.",
        },
    },
    "mailing_opens": {
        "description": "Recipients who opened each sent mailing, one row per mailing and recipient.",
        "docs_url": _DOCS,
        "columns": {**_RECIPIENT_COLUMNS, "openedOn": "Time the recipient opened the mailing."},
    },
    "mailing_clicks": {
        "description": "Recipients who clicked a link in each sent mailing, one row per mailing and recipient.",
        "docs_url": _DOCS,
        "columns": {**_RECIPIENT_COLUMNS, "clickedOn": "Time the recipient clicked a link in the mailing."},
    },
    "templates": {
        "description": "Email templates of the account.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique numerical ID of the template.",
            "title": "Name of the template.",
            "createdOn": "Time the template was created.",
            "updatedOn": "Time the template was last updated.",
        },
    },
}
