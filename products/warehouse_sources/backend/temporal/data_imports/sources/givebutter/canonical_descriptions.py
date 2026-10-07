from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "Fundraising campaigns, including goals, amounts raised, donor counts, and event settings.",
        "docs_url": "https://docs.givebutter.com/api-reference/campaigns/list-all-campaigns",
        "columns": {
            "id": "Unique campaign identifier.",
            "goal": "Fundraising goal for the campaign.",
            "raised": "Amount raised by the campaign.",
        },
    },
    "campaign_members": {
        "description": "Individual fundraisers participating in a campaign, with their goals and amounts raised.",
        "docs_url": "https://docs.givebutter.com/api-reference/campaign-members/list-all-campaign-members",
        "columns": {"_campaigns_id": "Identifier of the campaign containing this member."},
    },
    "campaign_teams": {
        "description": "Fundraising teams within campaigns, including members, goals, and amounts raised.",
        "docs_url": "https://docs.givebutter.com/api-reference/campaign-teams/list-all-campaign-teams",
        "columns": {"_campaigns_id": "Identifier of the campaign containing this team."},
    },
    "campaign_tickets": {
        "description": "Ticket types offered by a campaign, including prices, bundles, and available quantities.",
        "docs_url": "https://docs.givebutter.com/api-reference/campaign-tickets/list-all-campaign-tickets",
        "columns": {"_campaigns_id": "Identifier of the campaign offering this ticket type."},
    },
    "campaign_discount_codes": {
        "description": "Campaign discount codes, including usage limits, validity dates, and applicable items.",
        "docs_url": "https://docs.givebutter.com/api-reference/campaign-discount-codes/list-all-discount-codes",
        "columns": {"_campaigns_id": "Identifier of the campaign offering this discount code."},
    },
    "contacts": {
        "description": "Donor and organization contact records, including contact details, tags, and giving statistics.",
        "docs_url": "https://docs.givebutter.com/api-reference/contacts/list-all-contacts",
        "columns": {
            "id": "Unique contact identifier.",
            "tags": "Tags assigned to the contact.",
            "stats": "Giving statistics for the contact.",
        },
    },
    "contact_activities": {
        "description": "Activities recorded for a contact, including activity type, occurrence time, and associated resource.",
        "docs_url": "https://docs.givebutter.com/api-reference/contact-activities/list-all-contact-activities",
        "columns": {"_contacts_id": "Identifier of the contact associated with this activity."},
    },
    "funds": {
        "description": "Designated fundraising funds, including fund codes, amounts raised, and supporter counts.",
        "docs_url": "https://docs.givebutter.com/api-reference/funds/list-all-funds",
        "columns": {"id": "Unique fund identifier.", "code": "Code assigned to the fund."},
    },
    "households": {
        "description": "Households grouping related contacts, with household names and the head contact.",
        "docs_url": "https://docs.givebutter.com/api-reference/households/list-all-households",
        "columns": {
            "id": "Unique household identifier.",
            "head_contact_id": "Identifier of the household's head contact.",
        },
    },
    "payouts": {
        "description": "Payouts of raised funds, including amounts, fees, payment methods, and payout status.",
        "docs_url": "https://docs.givebutter.com/api-reference/payouts/list-all-payouts",
        "columns": {"id": "Unique payout identifier.", "paid_at": "Time the payout was paid."},
    },
    "plans": {
        "description": "Recurring donation plans, including amounts, payment frequency, status, and the next billing date.",
        "docs_url": "https://docs.givebutter.com/api-reference/recurring-plans/list-all-recurring-plans",
        "columns": {"id": "Unique recurring plan identifier.", "contact_id": "Identifier of the donating contact."},
    },
    "pledges": {
        "description": "Donation pledges, including committed amounts, fulfilled amounts, and installment schedules.",
        "docs_url": "https://docs.givebutter.com/api-reference/pledges/list-all-pledges",
        "columns": {"id": "Unique pledge identifier.", "contact_id": "Identifier of the pledging contact."},
    },
    "tickets": {
        "description": "Issued tickets, including attendee details, transaction identifiers, and check-in times.",
        "docs_url": "https://docs.givebutter.com/api-reference/tickets/list-all-tickets",
        "columns": {
            "id": "Unique ticket identifier.",
            "transaction_id": "Identifier of the transaction for this ticket.",
        },
    },
    "transactions": {
        "description": "Donations and payments, including donor, campaign, fund, fees, refunds, and payout details.",
        "docs_url": "https://docs.givebutter.com/api-reference/transactions/list-all-transactions",
        "columns": {
            "id": "Unique transaction identifier.",
            "contact_id": "Identifier of the contact associated with the transaction.",
            "campaign_id": "Identifier of the campaign receiving the transaction.",
            "fund_id": "Identifier of the designated fund.",
            "payout_id": "Identifier of the payout associated with the transaction.",
        },
    },
}
