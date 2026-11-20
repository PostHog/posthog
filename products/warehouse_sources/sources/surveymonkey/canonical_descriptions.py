"""Canonical, documentation-sourced descriptions for SurveyMonkey endpoints and columns.

Sourced from the official SurveyMonkey API reference (https://api.surveymonkey.com/v3/docs).
Keyed by the endpoint names in `settings.py` `SURVEYMONKEY_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced SurveyMonkey table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "surveys": {
        "description": "A survey in your SurveyMonkey account, with its title, structure, and response counts.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#surveys",
        "columns": {
            "id": "Unique identifier for the survey.",
            "title": "The survey's title.",
            "nickname": "Internal nickname for the survey, not shown to respondents.",
            "language": "Language the survey is written in.",
            "category": "Category the survey belongs to.",
            "question_count": "Number of questions in the survey.",
            "page_count": "Number of pages in the survey.",
            "response_count": "Number of responses collected for the survey.",
            "date_created": "Time at which the survey was created.",
            "date_modified": "Time at which the survey was last modified.",
            "preview": "URL to preview the survey.",
            "href": "API URL of the survey resource.",
        },
    },
    "survey_responses": {
        "description": "An individual respondent's submission to a survey, including their answers.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#survey-responses",
        "columns": {
            "id": "Unique identifier for the response.",
            "survey_id": "ID of the survey this response belongs to.",
            "collector_id": "ID of the collector that gathered this response.",
            "recipient_id": "ID of the recipient who submitted the response, if known.",
            "response_status": "Status of the response (e.g. completed, partial, overquota, disqualified).",
            "total_time": "Total time the respondent spent on the survey, in seconds.",
            "ip_address": "IP address from which the response was submitted.",
            "date_created": "Time at which the response was started.",
            "date_modified": "Time at which the response was last modified.",
            "pages": "Array of pages with the respondent's answers to each question.",
            "href": "API URL of the response resource.",
        },
    },
    "survey_pages": {
        "description": "A page within a survey that groups a set of questions.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#survey-pages",
        "columns": {
            "id": "Unique identifier for the page.",
            "title": "The page's title.",
            "description": "Description shown at the top of the page.",
            "position": "Position of the page within the survey.",
            "question_count": "Number of questions on the page.",
            "href": "API URL of the page resource.",
        },
    },
    "survey_questions": {
        "description": "A question on a survey, extracted from the survey's page details.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#survey-pages-id-questions",
        "columns": {
            "id": "Unique identifier for the question.",
            "heading": "The question's text as shown to respondents.",
            "position": "Position of the question within its page.",
            "family": "Question family (e.g. single_choice, multiple_choice, open_ended, matrix).",
            "subtype": "Question subtype that refines the family (e.g. vertical, menu, essay).",
            "required": "Whether an answer to the question is required.",
            "answers": "Available answer choices and options for the question.",
            "href": "API URL of the question resource.",
        },
    },
    "collectors": {
        "description": "A method used to distribute a survey and gather responses (e.g. a web link or email invitation).",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#collectors",
        "columns": {
            "id": "Unique identifier for the collector.",
            "name": "The collector's name.",
            "type": "Type of collector (e.g. weblink, email).",
            "status": "Status of the collector (e.g. open, closed).",
            "response_count": "Number of responses collected by this collector.",
            "date_created": "Time at which the collector was created.",
            "date_modified": "Time at which the collector was last modified.",
            "href": "API URL of the collector resource.",
        },
    },
    "survey_trends": {
        "description": "Answer counts for each question of a survey, bucketed by day.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#surveys-id-trends",
        "columns": {
            "id": "Unique identifier for the question.",
            "survey_id": "Identifier of the survey the question belongs to.",
            "href": "API URL of the question resource.",
            "trends": "Answer counts per time bucket. Empty for question types without trends.",
        },
    },
    "collector_messages": {
        "description": "An email or SMS invite or reminder message sent from a collector.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#collectors-id-messages",
        "columns": {
            "id": "Unique identifier for the message.",
            "collector_id": "Identifier of the collector that sends the message.",
            "survey_id": "Identifier of the survey the collector belongs to.",
            "status": "Status of the message (e.g. not_sent, scheduled, sent).",
            "type": "Type of message (e.g. invite, reminder, thank_you).",
            "href": "API URL of the message resource.",
        },
    },
    "collector_recipients": {
        "description": "A contact who gets a collector's email or SMS messages, with their delivery and response status.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#collectors-id-recipients",
        "columns": {
            "id": "Unique identifier for the recipient.",
            "collector_id": "Identifier of the collector the recipient belongs to.",
            "survey_id": "Identifier of the survey the collector belongs to.",
            "email": "Email address of the recipient.",
            "phone_number": "Phone number of the recipient, for SMS collectors.",
            "survey_response_status": "Response state of the recipient: not_responded, partially_responded or completely_responded.",
            "mail_status": "Delivery state of the invite: sent, not_sent or processing.",
            "custom_fields": "Custom contact fields of the recipient.",
            "extra_fields": "Extra contact fields of the recipient.",
            "href": "API URL of the recipient resource.",
        },
    },
    "collector_message_stats": {
        "description": "Delivery, open, click, bounce and response counts for one collector message.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#collectors-id-messages-id-stats",
        "columns": {
            "message_id": "Identifier of the message the counts belong to.",
            "collector_id": "Identifier of the collector that sends the message.",
            "survey_id": "Identifier of the survey the collector belongs to.",
            "recipients": "Number of recipients of the message.",
            "mail_status": "Recipient counts by delivery state: sent, not_sent, opened, link_clicked, bounced, opted_out.",
            "survey_response_status": "Recipient counts by response state: not_responded, partially_responded, completely_responded.",
        },
    },
    "survey_rollups": {
        "description": "Answer counts per question of a survey, computed by SurveyMonkey from all its responses.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#api-endpoints-get-surveys-survey_id-rollups",
        "columns": {
            "id": "Identifier of the question the counts belong to.",
            "survey_id": "Identifier of the survey the question belongs to.",
            "family": "Question family (e.g. single_choice, matrix, open_ended).",
            "subtype": "Question subtype within its family.",
            "summary": "Counts of respondents who answered or skipped the question, with a count for each choice and basic statistics for close-ended questions.",
            "href": "API URL of the question's rollup.",
        },
    },
    "collector_stats": {
        "description": "Delivery, open, click, bounce and response counts over all messages of one email or SMS collector.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#api-endpoints-get-collectors-collector_id-stats",
        "columns": {
            "collector_id": "Identifier of the collector the counts belong to.",
            "survey_id": "Identifier of the survey the collector belongs to.",
            "recipients": "Number of recipients of the collector's messages.",
            "mail_status": "Recipient counts by delivery state: sent, not_sent, opened, link_clicked, bounced, opted_out.",
            "survey_response_status": "Recipient counts by response state: not_responded, partially_responded, completely_responded.",
        },
    },
    "contacts": {
        "description": "A contact in the account's address book, which email and SMS collectors send invites to.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#api-endpoints-get-contacts-bulk",
        "columns": {
            "id": "Unique identifier for the contact.",
            "first_name": "First name of the contact.",
            "last_name": "Last name of the contact.",
            "email": "Email address of the contact.",
            "phone_number": "Phone number of the contact.",
            "custom_fields": "Custom contact fields, keyed by field number.",
            "contact_status": "Status of the contact: active, optout or bounced.",
            "href": "API URL of the contact resource.",
        },
    },
    "contact_lists": {
        "description": "A named list of contacts that a collector can send invites to.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#api-endpoints-get-contact_lists",
        "columns": {
            "id": "Unique identifier for the contact list.",
            "name": "Name of the contact list.",
            "href": "API URL of the contact list resource.",
        },
    },
    "contact_list_contacts": {
        "description": "A contact that is a member of a contact list, one row per list and contact.",
        "docs_url": "https://api.surveymonkey.com/v3/docs?shell#api-endpoints-get-contact_lists-contact_list_id-contacts-bulk",
        "columns": {
            "id": "Identifier of the contact.",
            "contact_list_id": "Identifier of the contact list the contact is a member of.",
            "first_name": "First name of the contact.",
            "last_name": "Last name of the contact.",
            "email": "Email address of the contact.",
            "phone_number": "Phone number of the contact.",
            "custom_fields": "Custom contact fields, keyed by field number.",
            "contact_status": "Status of the contact: active, optout or bounced.",
            "href": "API URL of the contact resource.",
        },
    },
}
