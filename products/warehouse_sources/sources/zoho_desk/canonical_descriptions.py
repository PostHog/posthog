"""Canonical descriptions for Zoho Desk tables.

Sourced from the official Zoho Desk API reference (https://desk.zoho.com/DeskAPIDocument).
Keys match the schema names in `settings.py` `ENDPOINTS`.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

API_DOCS_URL = "https://desk.zoho.com/DeskAPIDocument"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "tickets": {
        "description": "A customer inquiry, request, complaint, or other interaction that support agents handle, recorded from creation to resolution.",
        "docs_url": f"{API_DOCS_URL}#Tickets",
        "columns": {
            "id": "ID of the ticket.",
            "ticketNumber": "Number of the ticket, as shown to agents and customers.",
            "subject": "Subject of the ticket.",
            "departmentId": "ID of the department the ticket belongs to.",
            "contactId": "ID of the contact who raised the ticket.",
            "productId": "ID of the product associated with the ticket.",
            "assigneeId": "ID of the agent the ticket is assigned to.",
            "email": "Email ID of the ticket.",
            "phone": "Phone number of the ticket.",
            "status": "Status of the ticket. A system-defined or custom value that falls under one of the status types.",
            "statusType": "Status type of the ticket: OPEN, ONHOLD, or CLOSED.",
            "category": "Category of the ticket.",
            "subCategory": "Subcategory of the ticket.",
            "dueDate": "Due date of the ticket.",
            "priority": "Priority of the ticket. System-defined values such as Medium, High, and Low, or a custom value.",
            "sentiment": "Whether the customer's overall tone in the ticket is positive, negative, or neutral. Null when the ticket sentiment feature is disabled.",
            "language": "Language preference of the ticket.",
            "channel": "Channel through which the ticket was created.",
            "channelCode": "Code of the ticket's channel.",
            "source": "Source through which the ticket originated.",
        },
    },
    "contacts": {
        "description": "An end customer who raises requests, enquiries, or complaints with the customer service team. Each contact is mapped to an account.",
        "docs_url": f"{API_DOCS_URL}#Contacts",
        "columns": {
            "id": "ID of the contact.",
        },
    },
    "accounts": {
        "description": "A customer organization that uses your products or services. An account can have multiple contacts.",
        "docs_url": f"{API_DOCS_URL}#Accounts",
        "columns": {
            "id": "ID of the account.",
        },
    },
    "agents": {
        "description": "A customer service executive in your organization, who interacts with contacts and resolves tickets.",
        "docs_url": f"{API_DOCS_URL}#Agents",
    },
    "departments": {
        "description": "An organizational division configured in the help desk, based on the business function it performs, such as marketing, sales, or finance.",
        "docs_url": f"{API_DOCS_URL}#Departments",
    },
    "teams": {
        "description": "A group of agents in a department. Tickets and tasks can be assigned to a team as well as to an agent.",
        "docs_url": f"{API_DOCS_URL}#Teams",
    },
    "products": {
        "description": "A good or service your organization sells.",
        "docs_url": f"{API_DOCS_URL}#Products",
    },
    "tasks": {
        "description": "A work activity assigned to an agent. A task does not have to relate to a ticket.",
        "docs_url": f"{API_DOCS_URL}#Tasks",
    },
    "calls": {
        "description": "A support-related call between a customer and the help desk. Each call is mapped to a contact.",
        "docs_url": f"{API_DOCS_URL}#Calls",
    },
    "events": {
        "description": "A pre-planned, usually customer-facing activity aimed at ticket resolution, such as a meeting or a demo.",
        "docs_url": f"{API_DOCS_URL}#Events",
    },
    "contracts": {
        "description": "A service commitment for an account or a product, which sets the level of service and the contract period.",
        "docs_url": f"{API_DOCS_URL}#Contracts",
    },
}
