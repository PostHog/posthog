from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "responses": {
        "description": "Individual survey responses (NPS, CSAT, or 5-star) with the score, comment, and contact details for each respondent.",
        "docs_url": "https://asknicely.asknice.ly/help/apidocs/responses",
        "columns": {
            "response_id": "Unique identifier for the response.",
            "person_id": "Identifier of the person (contact) the survey was sent to.",
            "contact_id": "Identifier of the contact record in AskNicely.",
            "name": "Name of the respondent.",
            "email": "Email address of the respondent.",
            "answer": "The score the respondent gave (e.g. 0-10 for NPS).",
            "answerlabel": "Label associated with the answer, where the survey uses labelled options.",
            "comment": "Free-text comment left by the respondent.",
            "note": "Internal notes attached to the response.",
            "status": "Delivery/response status of the survey (e.g. answered).",
            "dontcontact": "Whether the contact has opted out of further surveys.",
            "sent": "Unix timestamp when the survey was sent.",
            "opened": "Unix timestamp when the survey was opened, or 0 if never opened.",
            "responded": "Unix timestamp when the respondent answered the survey.",
            "lastemailed": "Unix timestamp when the contact was last emailed.",
            "created": "Unix timestamp when the contact record was created.",
            "segment": "Segment the contact belongs to.",
            "question_type": "Survey metric type for this response: nps, csat, or 5star.",
            "published": "Whether the response has been approved for publishing as a testimonial.",
            "publishedname": "Display name used when the response is published as a testimonial.",
            "deliverymethod": "Channel the survey was delivered through (e.g. email).",
        },
    },
}
