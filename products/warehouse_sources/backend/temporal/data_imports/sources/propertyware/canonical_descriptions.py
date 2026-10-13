"""Canonical, documentation-sourced descriptions for Propertyware endpoints and columns.

Sourced from the official Propertyware OpenAPI 3.0 spec. Keyed by the resource names in
`settings.py` `ENDPOINT_PATHS`, which match the `ExternalDataSchema.name` of a synced
Propertyware table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_API_DOCS_URL = "https://app.propertyware.com/apidocs/index.html"

# Audit fields shared by every Propertyware object.
_COMMON_COLUMNS = {
    "id": "Unique identifier.",
    "createdBy": "User who created the record.",
    "createdDateTime": "Date and time the record was created (UTC).",
    "lastModifiedBy": "User who last modified the record.",
    "lastModifiedDateTime": "Date and time the record was last modified (UTC).",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Portfolios": {
        "description": "A group of properties (buildings) managed together, typically for one owner.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            name="Portfolio name.",
            abbreviation="Abbreviated name assigned to the portfolio.",
            active="Whether the portfolio is active or inactive.",
            cashAccrual="Cash or accrual accounting basis.",
            closingDate="Date when the accounting period for the portfolio will close.",
            defaultBankAccountID="ID of the portfolio's default bank account.",
            targetOperatingReserve="Minimum balance to be maintained within the portfolio at all times.",
        ),
    },
    "Buildings": {
        "description": "A physical property (single-family home or multi-unit building) within a portfolio.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            name="Name of the property.",
            portfolioID="ID of the portfolio associated with this property.",
            active="Whether the property is active or inactive.",
            status="Property status (occupied/vacant).",
            propertyType="Type of property.",
            multiUnit="Whether the building is multi-family or single-family.",
            numberOfBedrooms="Number of bedrooms in the property.",
            numberOfBathrooms="Number of bathrooms in the property.",
            totalArea="Property total area.",
            targetRent="Property target rent.",
            yearBuilt="Property built year.",
            rentable="Whether the property is available for rent.",
        ),
    },
    "Units": {
        "description": "An individually leasable unit within a building.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            name="Name of the unit.",
            buildingID="ID of the building associated with this unit.",
            portfolioID="ID of the portfolio associated with this property.",
            leaseID="Related lease ID.",
            status="Property status (occupied/vacant).",
            targetRent="Property target rent.",
            numberOfBedrooms="Number of bedrooms in the property.",
            numberOfBathrooms="Number of bathrooms in the property.",
            rentable="Whether the property is available for rent.",
        ),
    },
    "Leases": {
        "description": "A lease agreement between one or more tenants and a portfolio owner for a unit or building.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            leaseName="Lease name.",
            portfolioID="ID of the portfolio associated with this lease.",
            buildingID="ID of the building associated with this lease.",
            unitID="ID of the unit associated with this lease.",
            status="Lease's current status.",
            active="Whether the lease is active.",
            startDate="Start date of the lease term.",
            endDate="End date of the lease term.",
            moveInDate="Day that the tenant(s) moved into the property.",
            moveOutDate="Day that the tenant(s) vacated the property.",
            baseRent="Property base rent.",
            leaseBalance="Lease balance.",
            arBalance="Lease accounts receivable balance.",
        ),
    },
    "LeaseCharges": {
        "description": "A charge posted to a lease (rent, fees, or other billed amounts).",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            leaseID="ID of the lease associated with this charge.",
            portfolioID="ID of the portfolio associated with this charge.",
            glAccountID="ID of the general ledger account associated with this charge.",
            amount="Charge amount.",
            amountDue="The amount due for the charge.",
            amountPaid="The amount paid for the charge.",
            date="Post date.",
            refNo="Reference number.",
        ),
    },
    "LeasePayments": {
        "description": "A payment applied against lease charges.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            leaseID="ID of the lease associated with this payment.",
            portfolioID="ID of the portfolio associated with this transaction.",
            contactID="ID of the contact associated with this payment.",
            glAccountID="General ledger account ID.",
            amount="Payment amount.",
            date="Post date.",
            depositDate="Date the payment was deposited.",
            paymentType="Payment type.",
            isDeposited="Whether the payment has been deposited.",
            refNo="Reference number.",
        ),
    },
    "LeaseAdjustments": {
        "description": "A manual adjustment posted to a lease's balance.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            leaseID="ID of the lease associated with this adjustment.",
            portfolioID="ID of the portfolio associated with this adjustment.",
            glAccountID="ID of the general ledger account associated with this adjustment.",
            amount="Adjustment amount.",
            date="Post date.",
            refNo="Reference number.",
        ),
    },
    "LeaseRefunds": {
        "description": "A refund issued from a lease's balance back to a tenant.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            leaseID="ID of the lease associated with the refund.",
            portfolioID="ID of the portfolio associated with the refund.",
            glAccountID="ID of the general ledger account associated with the refund.",
            destinationAccountID="ID of the bank account to send the refund from.",
            amount="Refund amount.",
            date="Post date.",
            payeePayer="Name of the payee.",
            refNo="Reference number.",
        ),
    },
    "Contacts": {
        "description": "A person record — tenant, owner, or other contact — in the account.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            firstName="First name.",
            lastName="Last name.",
            email="Email address.",
            company="Company where the contact is employed.",
            type="Contact type.",
            category="Contact category.",
            mobilePhone="Mobile phone.",
            namedOnLease="Whether the contact is named on a lease.",
        ),
    },
    "Prospects": {
        "description": "A prospective tenant who has expressed interest in leasing a property.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            portfolioID="ID of the portfolio associated with the prospect.",
            buildingID="ID of the building associated with the prospect.",
            unitID="ID of the unit associated with the prospect.",
            status="Prospect status.",
            type="Prospect type.",
            source="Prospect source.",
            moveInDate="Desired move-in date.",
            rent="Confirmed lease rent.",
            applicationFeePaid="Whether the application fee has been paid by the prospect.",
        ),
    },
    "Vendors": {
        "description": "A vendor or service provider paid for work performed on managed properties.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            name="Vendor name.",
            companyName="Name of the vendor's company.",
            type="The type of vendor.",
            active="Whether the vendor is active.",
            email="Email address.",
            phone="Phone number.",
            taxId="Tax identification number.",
            eligible1099="Whether the vendor is eligible for a 1099 form.",
        ),
    },
    "Bills": {
        "description": "A bill owed to a vendor, optionally tied to a work order.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            vendorID="The ID of the vendor related to the bill.",
            workOrderID="The ID of the work order associated with the bill.",
            markupGLAccountID="The ID of the markup/discount general ledger account associated with the bill.",
            amount="Bill amount.",
            billDate="Entry date.",
            dueDate="Due date.",
            paymentDate="Date the bill was paid.",
            credit="Whether the bill is a vendor credit.",
            refNo="Reference number.",
        ),
    },
    "BillPayments": {
        "description": "A payment made to a vendor against one or more bills.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            vendorID="ID of the vendor associated with this payment.",
            paymentAccountID="ID of the payment general ledger account.",
            amount="Payment amount.",
            paymentDate="Payment date.",
            paymentMethod="Payment method.",
            checkNumber="Payment check number.",
        ),
    },
    "WorkOrders": {
        "description": "A maintenance work order for a building or unit.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            portfolioID="ID of the portfolio associated with this work order.",
            buildingID="ID of the building associated with this work order.",
            unitID="ID of the unit associated with this work order.",
            status="Current status of the work order.",
            priority="Priority of the work order: low, medium, or high.",
            type="Classifies the work order (general, service request, turnover, inspection, estimate, etc).",
            category="Classifies the work order into a category.",
            description="Detailed description of the problem.",
            completedDate="Date on which the work was completed.",
            costEstimate="Estimated, actual, and invoiced cost of the work order.",
        ),
    },
    "Inspections": {
        "description": "A property inspection scheduled or completed for a lease or building.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            portfolioID="ID of the portfolio associated with this inspection.",
            buildingID="ID of the building associated with this inspection.",
            leaseID="ID of the lease associated with this inspection.",
            inspectorID="ID of the inspector.",
            status="Inspection status.",
            type="Inspection type.",
            scheduledDateAndTime="Date and time the inspection is/was scheduled to occur.",
            inspectedDateAndTime="Date and time the inspection occurred.",
        ),
    },
    "GLAccounts": {
        "description": "A general ledger account used for accounting entries across the account.",
        "docs_url": _API_DOCS_URL,
        "columns": _columns(
            name="Account name.",
            accountNumber="Account number.",
            accountCode="Account code.",
            accountType="Account type.",
            active="Whether the account is active.",
            description="Description of the account.",
            parentGLAccountId="Parent account ID.",
            rentAccount="Whether the account is a rent account.",
        ),
    },
}
