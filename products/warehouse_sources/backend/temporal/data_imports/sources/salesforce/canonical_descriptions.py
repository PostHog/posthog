"""Canonical, documentation-sourced descriptions for Salesforce standard objects and fields.

Sourced from the official Salesforce Object Reference for the Salesforce Platform
(https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/).
Keyed by the standard sObject API names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Salesforce table. The source syncs a fixed set of standard
objects (it does not enumerate user-defined custom objects), so these are stable across teams.

Column keys use the normalized (snake_case) column names the pipeline writes to
`DataWarehouseTable.columns` — e.g. Salesforce's `BillingCity` is stored and matched as
`billing_city`. This mirrors every other source's canonical file and is what the enrichment pass
compares against. Custom fields (Salesforce `__c`, normalized to a `_c` suffix) are deliberately
omitted: their meaning varies per org, so they fall back to LLM enrichment. Columns absent here
also fall back to the LLM.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Audit fields present on every standard Salesforce object; merged into each entry.
_COMMON_COLUMNS = {
    "id": "Unique 18-character Salesforce record identifier.",
    "created_date": "Date and time the record was created.",
    "created_by_id": "ID of the user who created the record.",
    "last_modified_date": "Date and time the record was last modified.",
    "last_modified_by_id": "ID of the user who last modified the record.",
    "system_modstamp": "Date and time the record was last modified by a user or automated process.",
    "is_deleted": "Whether the record has been moved to the Recycle Bin.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Account": {
        "description": "An organization or person involved with your business, such as a customer or partner.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_account.htm",
        "columns": _columns(
            name="Name of the account.",
            type="Type of account (e.g. Customer, Partner, Prospect).",
            industry="Primary business industry of the account.",
            website="The account's website URL.",
            phone="The account's primary phone number.",
            owner_id="ID of the user who owns the account.",
            parent_id="ID of the parent account, if this account is part of a hierarchy.",
            annual_revenue="Estimated annual revenue of the account.",
            number_of_employees="Number of employees at the account.",
            billing_city="City portion of the account's billing address.",
            billing_country="Country portion of the account's billing address.",
            billing_longitude="Longitude of the account's billing address, used for mapping.",
            shipping_city="City portion of the account's shipping address.",
            description="Free-form text description of the account.",
            first_name="First name of the account, when it is a Person Account.",
            person_birthdate="Birthdate of the account, when it is a Person Account.",
            person_mailing_street="Street portion of the mailing address, when the account is a Person Account.",
            person_other_city="City portion of the secondary address, when the account is a Person Account.",
            person_other_country="Country portion of the secondary address, when the account is a Person Account.",
            person_assistant_name="Name of the account's assistant, when it is a Person Account.",
        ),
    },
    "Contact": {
        "description": "An individual associated with an account, such as an employee of a customer.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_contact.htm",
        "columns": _columns(
            first_name="Contact's first name.",
            last_name="Contact's last name.",
            name="Contact's full name.",
            email="Contact's email address.",
            phone="Contact's phone number.",
            title="Contact's job title.",
            account_id="ID of the account this contact is associated with.",
            owner_id="ID of the user who owns the contact.",
            reports_to_id="ID of the contact this person reports to.",
            mailing_city="City portion of the contact's mailing address.",
            mailing_country="Country portion of the contact's mailing address.",
            lead_source="Source from which this contact was generated.",
            record_type_id="ID of the record type, which controls available picklist values and page layout.",
        ),
    },
    "Lead": {
        "description": "A prospect or potential customer who has not yet been qualified.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_lead.htm",
        "columns": _columns(
            first_name="Lead's first name.",
            last_name="Lead's last name.",
            name="Lead's full name.",
            company="Company the lead is associated with.",
            email="Lead's email address.",
            phone="Lead's phone number.",
            title="Lead's job title.",
            status="Status of the lead in the qualification process.",
            lead_source="Source from which this lead was generated.",
            industry="Industry of the lead's company.",
            owner_id="ID of the user who owns the lead.",
            is_converted="Whether the lead has been converted into an account, contact, and opportunity.",
            converted_date="Date the lead was converted.",
            converted_account_id="ID of the account created when the lead was converted.",
            converted_contact_id="ID of the contact created when the lead was converted.",
            converted_opportunity_id="ID of the opportunity created when the lead was converted.",
            rating="Lead's rating (e.g. Hot, Warm, Cold).",
            email_bounced_reason="Reason an email sent to the lead bounced, if any.",
            last_transfer_date="Date the lead was last transferred to another owner.",
        ),
    },
    "Opportunity": {
        "description": "A potential sale or pending deal being tracked through the sales pipeline.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_opportunity.htm",
        "columns": _columns(
            name="Name of the opportunity.",
            account_id="ID of the account this opportunity is for.",
            contact_id="ID of the primary contact associated with the opportunity.",
            amount="Estimated total sale amount of the opportunity.",
            stage_name="Current stage of the opportunity in the sales process.",
            probability="Estimated percentage likelihood of closing the opportunity.",
            close_date="Expected or actual close date of the opportunity.",
            type="Type of opportunity (e.g. New Business, Existing Business).",
            lead_source="Source from which this opportunity was generated.",
            is_closed="Whether the opportunity has reached a closed stage.",
            is_won="Whether the opportunity was won.",
            forecast_category_name="Forecast category the opportunity falls into.",
            owner_id="ID of the user who owns the opportunity.",
            expected_revenue="Amount multiplied by probability — the weighted forecast revenue.",
            connection_sent_id="ID of the Salesforce-to-Salesforce connection the opportunity was shared through.",
        ),
    },
    "OpportunityHistory": {
        "description": "A historical snapshot of an opportunity's stage, amount, and probability at a point in time.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_opportunityhistory.htm",
        "columns": _columns(
            opportunity_id="ID of the opportunity this history record belongs to.",
            stage_name="The opportunity's stage at the time of this snapshot.",
            amount="The opportunity's amount at the time of this snapshot.",
            probability="The opportunity's probability at the time of this snapshot.",
            close_date="The opportunity's close date at the time of this snapshot.",
            forecast_category="Forecast category at the time of this snapshot.",
        ),
    },
    "Campaign": {
        "description": "A marketing initiative, such as an email blast or event, used to generate leads.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_campaign.htm",
        "columns": _columns(
            name="Name of the campaign.",
            type="Type of campaign (e.g. Email, Webinar, Advertisement).",
            status="Status of the campaign (e.g. Planned, In Progress, Completed).",
            start_date="Start date of the campaign.",
            end_date="End date of the campaign.",
            is_active="Whether the campaign is currently active and available for use.",
            budgeted_cost="Budgeted cost of the campaign.",
            actual_cost="Actual cost incurred by the campaign.",
            expected_revenue="Expected revenue generated by the campaign.",
            number_of_leads="Number of leads associated with the campaign.",
            number_of_contacts="Number of contacts associated with the campaign.",
            owner_id="ID of the user who owns the campaign.",
        ),
    },
    "User": {
        "description": "A user account in the Salesforce organization.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_user.htm",
        "columns": _columns(
            username="The user's login username, in email format.",
            name="The user's full name.",
            first_name="The user's first name.",
            last_name="The user's last name.",
            email="The user's email address.",
            is_active="Whether the user account is active.",
            profile_id="ID of the user's profile, which controls permissions.",
            user_role_id="ID of the user's role in the role hierarchy.",
            title="The user's job title.",
            department="The user's department.",
            manager_id="ID of the user's manager.",
            time_zone_sid_key="The user's time zone.",
            street="Street portion of the user's address.",
            number_of_failed_logins="Number of consecutive failed login attempts for the user.",
            email_preferences_auto_bcc="Whether the user is automatically BCC'd on outbound emails they send.",
        ),
    },
    "UserRole": {
        "description": "A role in the organization's role hierarchy, controlling record-level data access.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_userrole.htm",
        "columns": _columns(
            name="Name of the role.",
            parent_role_id="ID of the parent role in the hierarchy.",
            developer_name="Unique API name of the role.",
            rollup_description="Description of the role used in forecasting rollups.",
        ),
    },
    "Product2": {
        "description": "A product or service your organization sells, used in price books and opportunities.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_product2.htm",
        "columns": _columns(
            name="Name of the product.",
            product_code="Internal product code or SKU.",
            description="Description of the product.",
            is_active="Whether the product is active and available for use.",
            family="Product family the product belongs to.",
            quantity_unit_of_measure="Unit of measure for the product (e.g. each, kg).",
            revenue_schedule_type="How revenue for the product is scheduled (e.g. one-time or repeating).",
            quantity_installment_period="Period between installments for a quantity schedule (e.g. daily, monthly).",
        ),
    },
    "Pricebook2": {
        "description": "A price book — a list of products and their prices for a given market or segment.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_pricebook2.htm",
        "columns": _columns(
            name="Name of the price book.",
            description="Description of the price book.",
            is_active="Whether the price book is active.",
            is_standard="Whether this is the standard (default) price book.",
        ),
    },
    "PricebookEntry": {
        "description": "An entry linking a product to a price within a specific price book.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_pricebookentry.htm",
        "columns": _columns(
            name="Name of the price book entry (typically the product name).",
            pricebook2_id="ID of the price book this entry belongs to.",
            product2_id="ID of the product this entry prices.",
            unit_price="Price of the product in this price book.",
            is_active="Whether the price book entry is active.",
            use_standard_price="Whether this entry uses the standard price.",
            currency_iso_code="ISO currency code for the unit price.",
        ),
    },
    "Order": {
        "description": "An agreement between a company and an account to provision products or services.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_order.htm",
        "columns": _columns(
            order_number="Auto-generated reference number for the order.",
            account_id="ID of the account the order is for.",
            status="Status of the order (e.g. Draft, Activated).",
            effective_date="Date the order takes effect.",
            end_date="Date the order ends.",
            total_amount="Total amount of all order products.",
            type="Type of order.",
            owner_id="ID of the user who owns the order.",
            pricebook2_id="ID of the price book associated with the order.",
            opportunity_id="ID of the opportunity the order originated from, if any.",
        ),
    },
    "Event": {
        "description": "A calendar event, such as a meeting or call, logged against a record.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_event.htm",
        "columns": _columns(
            subject="Subject line of the event.",
            start_date_time="Date and time the event starts.",
            end_date_time="Date and time the event ends.",
            activity_date="Due date of the event.",
            location="Location of the event.",
            owner_id="ID of the user who owns the event.",
            who_id="ID of the contact or lead associated with the event.",
            what_id="ID of the related record (e.g. account or opportunity) for the event.",
            is_all_day_event="Whether the event lasts all day.",
            description="Description or notes for the event.",
            group_event_type="Whether the event is a non-group event, group event, or proposed event.",
        ),
    },
    "Task": {
        "description": "A to-do item, such as a call or follow-up, logged against a record.",
        "docs_url": "https://developer.salesforce.com/docs/atlas.en-us.object_reference.meta/object_reference/sforce_api_objects_task.htm",
        "columns": _columns(
            subject="Subject line of the task.",
            status="Status of the task (e.g. Not Started, In Progress, Completed).",
            priority="Priority of the task (e.g. High, Normal, Low).",
            activity_date="Due date of the task.",
            owner_id="ID of the user the task is assigned to.",
            who_id="ID of the contact or lead associated with the task.",
            what_id="ID of the related record (e.g. account or opportunity) for the task.",
            is_closed="Whether the task is in a closed state.",
            description="Description or notes for the task.",
            call_disposition="Result or outcome of a logged call task.",
        ),
    },
}
