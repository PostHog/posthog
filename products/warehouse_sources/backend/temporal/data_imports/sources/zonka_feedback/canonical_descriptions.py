from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Zonka Feedback API v2.1 docs (https://apidocs.zonkafeedback.com).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "responses": {
        "description": "A single feedback response submitted to a Zonka Feedback survey, including answers and respondent context.",
        "docs_url": "https://apidocs.zonkafeedback.com/",
        "columns": {
            "id": "The unique ID of the response.",
            "surveyId": "The ID of the survey this response was submitted to.",
            "contactId": "The ID of the contact who submitted the response, if known.",
            "channel": "The channel the response was collected through (email, SMS, web, kiosk, etc.).",
            "status": "The completion status of the response (e.g. complete, partial).",
            "language": "The language the survey was answered in.",
            "responseDate": "The timestamp the response was submitted, in ISO 8601 UTC.",
            "location": "The location associated with the response, if any.",
            "device": "The device the response was collected on, if any.",
            "answers": "The list of answers given to the survey's questions.",
        },
    },
    "surveys": {
        "description": "A Zonka Feedback survey — the questionnaire (CSAT, NPS, CES, etc.) distributed to collect feedback.",
        "docs_url": "https://apidocs.zonkafeedback.com/",
        "columns": {
            "id": "The unique ID of the survey.",
            "name": "The name of the survey.",
            "type": "The survey type (e.g. CSAT, NPS, CES).",
            "status": "Whether the survey is active or inactive.",
            "language": "The default language of the survey.",
            "createdOn": "The timestamp the survey was created, in ISO 8601 UTC.",
            "modifiedOn": "The timestamp the survey was last modified, in ISO 8601 UTC.",
        },
    },
    "contacts": {
        "description": "A contact in the Zonka Feedback account — a person surveys can be sent to and whose responses are attributed.",
        "docs_url": "https://apidocs.zonkafeedback.com/",
        "columns": {
            "id": "The unique ID of the contact.",
            "email": "The contact's email address.",
            "phone": "The contact's phone number.",
            "firstName": "The contact's first name.",
            "lastName": "The contact's last name.",
            "createdOn": "The timestamp the contact was created, in ISO 8601 UTC.",
            "modifiedOn": "The timestamp the contact was last modified, in ISO 8601 UTC.",
        },
    },
    "survey_links": {
        "description": "A shareable survey link generated through the Zonka Feedback Survey Links API — a unique URL used to distribute a survey through your own channels and track the response it collects.",
        "docs_url": "https://apidocs.zonkafeedback.com/",
        "columns": {
            "id": "The unique ID of the survey link.",
            "surveyId": "The ID of the survey this link opens.",
            "url": "The unique, shareable URL that opens the survey.",
            "trackingCode": "The short tracking code embedded in the link URL, used to attribute the collected response.",
            "status": "The current state of the link (e.g. active, expired, consumed).",
            "createdOn": "The timestamp the link was created, in ISO 8601 UTC.",
        },
    },
    "workspaces": {
        "description": "A workspace in the Zonka Feedback account. Workspaces group surveys and are used to segment reporting.",
        "docs_url": "https://apidocs.zonkafeedback.com/",
        "columns": {
            "id": "The unique ID of the workspace, referenced by `workspaceId` on surveys.",
            "workspaceName": "The name of the workspace.",
            "modifiedDate": "The timestamp the workspace was last modified, in ISO 8601 UTC.",
            "modifiedBy": "The name of the user who last modified the workspace.",
        },
    },
    "locations": {
        "description": "A location in the Zonka Feedback account, such as a site or branch that surveys and responses belong to.",
        "docs_url": "https://apidocs.zonkafeedback.com/",
        "columns": {
            "id": "The unique ID of the location, referenced by `locationId` on surveys and responses.",
            "name": "The name of the location.",
            "address": "The address of the location.",
            "externalId": "Your own identifier for the location.",
            "isActive": "Whether the location is active.",
            "labels": "The location labels assigned to the location.",
        },
    },
    "users": {
        "description": "A user of the Zonka Feedback account, such as an admin, a responder or a device user.",
        "docs_url": "https://apidocs.zonkafeedback.com/",
        "columns": {
            "id": "The unique ID of the user, referenced by user IDs on responses and tasks.",
            "name": "The user's name.",
            "email": "The user's email address.",
            "mobile": "The user's mobile number.",
            "externalId": "Your own identifier for the user.",
            "designation": "The user's job title.",
            "role": "The user's role: admin, viewrespond, viewonly, deviceuser or external.",
            "labels": "The user labels assigned to the user.",
            "lastLogin": "The timestamp the user last logged in, in ISO 8601 UTC.",
            "isOwner": "Whether the user is the account owner.",
            "isActive": "Whether the user is active.",
            "locationId": "The IDs of the locations the user is assigned to.",
        },
    },
    "distribution_logs": {
        "description": "One survey send through email, SMS or WhatsApp, with when the recipient opened and submitted it. Pair with responses to get delivery, open and response rates.",
        "docs_url": "https://apidocs.zonkafeedback.com/",
        "columns": {
            "to": "The email address or phone number the survey was sent to.",
            "sentDateTime": "The timestamp the survey was sent, in ISO 8601 UTC.",
            "surveyId": "The ID of the survey that was sent.",
            "surveyName": "The name of the survey that was sent.",
            "emailOpened": "The timestamp the recipient opened the email, or null.",
            "surveyOpened": "The timestamp the recipient opened the survey, or null.",
            "SurveySubmitted": "The timestamp the recipient submitted the survey, or null.",
            "locationName": "The name of the location the send is attributed to.",
            "channel": "The channel the survey was sent through: email, sms or whatsapp.",
            "status": "The distribution status: responded, surveyOpened, emailOpened or noResponse.",
        },
    },
}
