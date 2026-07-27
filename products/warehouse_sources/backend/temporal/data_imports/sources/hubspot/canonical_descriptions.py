"""Canonical, documentation-sourced descriptions for Hubspot CRM objects and properties.

Sourced from the official HubSpot CRM API reference (https://developers.hubspot.com/docs/api/crm).
Keyed by the lowercase endpoint names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Hubspot table. Columns map to HubSpot's default CRM
properties (`DEFAULT_*_PROPS` in `settings.py`). Covers every endpoint Hubspot exposes for sync; a
coverage test keeps this in lockstep with `ENDPOINTS`. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "A person tracked in HubSpot CRM — a lead, prospect, or customer.",
        "docs_url": "https://developers.hubspot.com/docs/api/crm/contacts",
        "columns": {
            "hs_object_id": "HubSpot's unique internal identifier for the contact.",
            "email": "The contact's primary email address.",
            "firstname": "The contact's first name.",
            "lastname": "The contact's last name.",
            "createdate": "Date the contact was created in HubSpot.",
            "lastmodifieddate": "Date any property on the contact was last modified.",
            "hs_lead_status": "The contact's sales, prospecting, or outreach status.",
            "hs_buying_role": "The contact's role in the buying decision (e.g. decision maker, champion).",
            "hs_analytics_first_timestamp": "Time of the contact's first recorded website session.",
            "hs_analytics_num_page_views": "Total number of page views by the contact.",
            "hs_seniority": "The contact's inferred job seniority level.",
            "hs_state_code": "Two-letter code for the contact's state or region.",
            "hs_shared_team_ids": "IDs of the HubSpot teams the contact is shared with.",
            "salesforcecampaignids": "IDs of associated Salesforce campaigns, set by the HubSpot-Salesforce integration.",
        },
    },
    "companies": {
        "description": "An organization or business tracked in HubSpot CRM.",
        "docs_url": "https://developers.hubspot.com/docs/api/crm/companies",
        "columns": {
            "hs_object_id": "HubSpot's unique internal identifier for the company.",
            "name": "The company's name.",
            "domain": "The company's primary website domain.",
            "createdate": "Date the company was created in HubSpot.",
            "hs_lastmodifieddate": "Date any property on the company was last modified.",
            "hs_lead_status": "The company's sales, prospecting, or outreach status.",
            "hs_csm_sentiment": "Customer success manager's recorded sentiment toward the company.",
            "industry": "The company's industry.",
            "website": "The company's website URL.",
            "hs_updated_by_user_id": "ID of the user who last updated the company.",
        },
    },
    "deals": {
        "description": "A sales opportunity or transaction tracked through a pipeline in HubSpot CRM.",
        "docs_url": "https://developers.hubspot.com/docs/api/crm/deals",
        "columns": {
            "hs_object_id": "HubSpot's unique internal identifier for the deal.",
            "dealname": "The name of the deal.",
            "amount": "The total monetary value of the deal.",
            "dealstage": "The deal's current stage within its pipeline.",
            "pipeline": "The pipeline the deal belongs to.",
            "closedate": "The date the deal is expected to close, or did close.",
            "createdate": "Date the deal was created in HubSpot.",
            "hs_lastmodifieddate": "Date any property on the deal was last modified.",
            "hs_mrr": "Monthly recurring revenue associated with the deal.",
            "hubspot_owner_id": "ID of the HubSpot user who owns the deal.",
            "hs_updated_by_user_id": "ID of the user who last updated the deal.",
        },
    },
    "tickets": {
        "description": "A customer support request tracked in HubSpot Service Hub.",
        "docs_url": "https://developers.hubspot.com/docs/api/crm/tickets",
        "columns": {
            "hs_object_id": "HubSpot's unique internal identifier for the ticket.",
            "subject": "Short summary of the ticket.",
            "content": "The body or description of the ticket.",
            "hs_pipeline": "The support pipeline the ticket belongs to.",
            "hs_pipeline_stage": "The ticket's current stage within its pipeline (e.g. new, waiting, closed).",
            "hs_ticket_priority": "The ticket's priority level.",
            "hs_ticket_category": "The category the ticket was filed under.",
            "createdate": "Date the ticket was created in HubSpot.",
            "hs_lastmodifieddate": "Date any property on the ticket was last modified.",
            "hubspot_companyid": "ID of the primary company associated with the ticket.",
        },
    },
    "quotes": {
        "description": "A sales quote (proposal of products and prices) sent to a customer in HubSpot.",
        "docs_url": "https://developers.hubspot.com/docs/api/crm/quotes",
        "columns": {
            "hs_object_id": "HubSpot's unique internal identifier for the quote.",
            "hs_title": "Title of the quote.",
            "hs_status": "The quote's current status (e.g. draft, pending approval, approved, published).",
            "hs_expiration_date": "Date the quote expires.",
            "hs_public_url_key": "Key used to build the quote's public, shareable URL.",
            "hs_createdate": "Date the quote was created in HubSpot.",
            "hs_lastmodifieddate": "Date any property on the quote was last modified.",
            "hs_esign_num_signers_required": "Number of signers required to e-sign the quote.",
        },
    },
    "emails": {
        "description": "A logged email engagement (sent or received) associated with CRM records in HubSpot.",
        "docs_url": "https://developers.hubspot.com/docs/api/crm/email",
        "columns": {
            "hs_object_id": "HubSpot's unique internal identifier for the email engagement.",
            "hs_timestamp": "Time the email was sent or received.",
            "hs_email_direction": "Direction of the email (e.g. EMAIL for outbound, INCOMING_EMAIL for inbound).",
            "hs_email_status": "Delivery status of the email (e.g. SENT, BOUNCED, FAILED).",
            "hs_email_subject": "Subject line of the email.",
            "hs_email_text": "Plain-text body of the email.",
            "hs_email_html": "HTML body of the email.",
            "hs_email_headers": "Raw email headers (from, to, cc) as a serialized string.",
            "hs_attachment_ids": "IDs of files attached to the email.",
            "hs_lastmodifieddate": "Date any property on the email was last modified.",
        },
    },
    "meetings": {
        "description": "A logged meeting engagement associated with CRM records in HubSpot.",
        "docs_url": "https://developers.hubspot.com/docs/api/crm/meetings",
        "columns": {
            "hs_object_id": "HubSpot's unique internal identifier for the meeting engagement.",
            "hs_timestamp": "Time the meeting is scheduled to occur.",
            "hs_meeting_title": "Title of the meeting.",
            "hs_meeting_body": "Description or agenda of the meeting.",
            "hs_internal_meeting_notes": "Internal notes about the meeting, not shared with the contact.",
            "hs_meeting_external_URL": "External calendar or video-conference URL for the meeting.",
            "hs_meeting_location": "Where the meeting takes place.",
            "hs_meeting_start_time": "Scheduled start time of the meeting.",
            "hs_meeting_end_time": "Scheduled end time of the meeting.",
            "hs_meeting_outcome": "Outcome of the meeting (e.g. scheduled, completed, canceled, no show).",
            "hs_activity_type": "The configured meeting/activity type.",
            "hs_attachment_ids": "IDs of files attached to the meeting.",
            "hs_lastmodifieddate": "Date any property on the meeting was last modified.",
            "hs_meeting_source": "How the meeting was created (e.g. CRM_UI, MEETINGS_PUBLIC).",
        },
    },
}
