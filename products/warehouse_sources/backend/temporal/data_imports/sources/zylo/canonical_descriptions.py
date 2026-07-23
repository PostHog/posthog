"""Canonical, documentation-sourced descriptions for Zylo endpoints and columns.

Sourced from the official Zylo Enterprise API reference (https://developer.zylo.com/reference).
Keyed by the endpoint names in `settings.py` `ZYLO_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Zylo table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Timestamps present on nearly every Zylo object; merged into each entry so we don't repeat them.
_SYSTEM_COLUMNS = {
    "zylo_created_at": "Date and time the record was created in Zylo.",
    "zylo_modified_at": "Date and time the record was last modified in Zylo.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_SYSTEM_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Applications": {
        "description": "A SaaS application discovered or added in Zylo's software catalog.",
        "docs_url": "https://developer.zylo.com/reference/applicationscontroller_getapplications",
        "columns": _columns(
            id="Unique identifier for the application.",
            app_name="The application's name.",
            app_label="Zylo's canonical label for the application.",
            status="Lifecycle status of the application (e.g. active).",
            category="High-level category the application belongs to.",
            subcategory="Sub-category within the application's category.",
            is_cloud="Whether the application is a cloud-hosted SaaS product.",
            holds_pii="Whether the application is flagged as holding personally identifiable information.",
            business_owner_user_email="Email of the business owner assigned to the application.",
            application_owner_user_email="Email of the application owner.",
            it_owner_user_email="Email of the IT owner assigned to the application.",
            next_action="Recommended next action for managing the application (e.g. cancel).",
            tags="Free-form tags applied to the application.",
        ),
    },
    "ApplicationLicenses": {
        "description": "A license seat for an application, typically assigned to a user.",
        "docs_url": "https://developer.zylo.com/reference/applicationlicensescontroller_getapplicationlicenses",
        "columns": _columns(
            id="Unique identifier for the license.",
            active="Whether the license is currently active.",
            application_id="ID of the application the license belongs to.",
            external_user_id="Identifier of the user the license is assigned to, from the source system.",
            is_paid_license="Whether the license is a paid seat.",
            last_activity_date="Date of the license holder's last recorded activity.",
            license_type="The license tier or plan name.",
            name="Display name of the license.",
        ),
    },
    "ApplicationUsers": {
        "description": "A user of an application, with usage and license activity.",
        "docs_url": "https://developer.zylo.com/reference/applicationuserscontroller_getapplicationusers",
        "columns": _columns(
            id="Unique identifier for the application user record.",
            application_id="ID of the application the user record belongs to.",
            email="Email address of the user.",
            full_name="Full name of the user.",
            first_name="First name of the user.",
            last_name="Last name of the user.",
            external_user_id="Identifier of the user from the source system.",
            active="Whether the user is currently active on the application.",
            is_paid_user="Whether the user occupies a paid license seat.",
            days_active="Number of days the user has been active on the application.",
            integration_type="Data source integration type this record was collected from.",
            license_names="Names of the licenses held by the user.",
            last_activity_date="Date of the user's last recorded activity on the application.",
        ),
    },
    "Contracts": {
        "description": "A software contract with a supplier, covering one or more applications.",
        "docs_url": "https://developer.zylo.com/reference/contractscontroller_getcontracts",
        "columns": _columns(
            id="Unique identifier for the contract.",
            name="Name of the contract.",
            number="Contract number.",
            status="Lifecycle status of the contract (e.g. Active, Expired, Inactive).",
            start_date="Date the contract begins.",
            end_date="Date the contract ends.",
            supplier_id="ID of the supplier the contract is with.",
            supplier_name="Name of the supplier the contract is with.",
            total_contract_value="Total value of the contract.",
            current_year_contract_value="Value of the contract attributable to the current year.",
            native_currency="Currency the contract's native monetary values are denominated in.",
            billing_frequency="How often the contract is billed.",
            renewal_state="Renewal status of the contract.",
            month_to_month="Whether the contract has moved to a month-to-month term.",
            can_have_contract_lines="Whether this contract has associated Contract Line Items.",
            total_licenses="Total number of licenses covered by the contract.",
            owner="Owner of the contract record.",
        ),
    },
    "ContractLineItems": {
        "description": "A single priced line item within a contract, e.g. a license tier or add-on.",
        "docs_url": "https://developer.zylo.com/reference/contractlineitemscontroller_getcontractlineitems",
        "columns": _columns(
            id="Unique identifier for the contract line item.",
            contract_id="ID of the parent contract.",
            application_id="ID of the application this line item relates to, if any.",
            line_description="Description of the line item.",
            license_type="License tier or plan name for the line item.",
            license_name="Name of the license the line item covers.",
            quantity="Quantity of licenses or units covered.",
            unit_of_measure="Unit the quantity is measured in.",
            unit_price="Price per unit.",
            native_unit_price="Price per unit in the contract's native currency.",
            total_price="Total price for the line item.",
            native_currency="Currency the line item's native monetary values are denominated in.",
            start_date="Date the line item's coverage begins.",
            end_date="Date the line item's coverage ends; null if ongoing.",
        ),
    },
    "Payments": {
        "description": "A payment made for an application, sourced from AP or expense data.",
        "docs_url": "https://developer.zylo.com/reference/paymentscontroller_getpayments",
        "columns": _columns(
            id="Unique identifier for the payment.",
            amount="Payment amount.",
            application_id="ID of the application the payment is for.",
            payment_date="Date the payment was made.",
            payment_type="Source of the payment record (AP or Expense).",
            payment_name="Name of the payment.",
            payment_description="Description of the payment.",
            supplier_name="Name of the supplier paid.",
            purchase_order_id="ID of the associated purchase order, if any.",
            transaction_id="Identifier of the underlying transaction.",
            cost_center="Cost center the payment is attributed to.",
            expense_type="Type of expense the payment represents.",
        ),
    },
    "PurchaseOrders": {
        "description": "A purchase order raised against a supplier for software spend. Premium feature — "
        "requires `applications:read` and `spend:read` API key scopes.",
        "docs_url": "https://developer.zylo.com/reference/purchaseorderscontroller_getpurchaseorders",
        "columns": _columns(
            id="Unique identifier for the purchase order.",
            number="Purchase order number.",
            status="Lifecycle status of the purchase order.",
            supplier_id="ID of the supplier the purchase order was raised against.",
            vendor_name="Name of the vendor on the purchase order.",
            account_number="Account number associated with the purchase order.",
            total_spend_against="Total amount spent against the purchase order.",
            remaining_spend_against="Remaining unspent amount on the purchase order.",
            percent_spend_against="Percentage of the purchase order value spent so far.",
            external_created_at="Date the source system reported as the purchase order's creation date.",
            external_closed_at="Date the source system reported the purchase order as closed.",
            requisition_number="Requisition number linked to the purchase order.",
        ),
    },
    "POLineItems": {
        "description": "A single line item within a purchase order.",
        "docs_url": "https://developer.zylo.com/reference/polineitemscontroller_getpolineitems",
        "columns": _columns(
            id="Unique identifier for the purchase order line item.",
            purchase_order_id="ID of the parent purchase order.",
            application_id="ID of the application this line item relates to, if any.",
            description="Description of the line item.",
            amount="Amount for the line item.",
            total_spend_against="Total amount spent against this line item.",
            remaining_spend_against="Remaining unspent amount on this line item.",
            percent_spend_against="Percentage of the line item's value spent so far.",
            is_saas="Whether the line item is classified as SaaS spend.",
            commodity_category="Commodity category the line item is classified under.",
            commodity_name="Commodity name for the line item.",
            department_name="Department the line item is attributed to.",
            expense_type="Type of expense the line item represents.",
            order_line_number="Line number within the purchase order.",
            requestor_name="Name of the requestor for the line item.",
            supplier_account_number="Supplier's account number for the line item.",
            supplier_name="Name of the supplier.",
            supplier_number="Zylo supplier number.",
            supplier_order_number="Supplier's order number for the line item.",
            external_created_at="Date the source system reported as the line item's creation date.",
        ),
    },
    "Suppliers": {
        "description": "A supplier (vendor) that PostHog customers buy software or services from.",
        "docs_url": "https://developer.zylo.com/reference/supplierscontroller_getsuppliers",
        "columns": _columns(
            id="Unique identifier for the supplier.",
            name="Name of the supplier.",
            domain="Primary domain of the supplier.",
            description="Description of the supplier.",
        ),
    },
    "SavingsEvents": {
        "description": "A recorded cost-savings event, e.g. a license reduction or contract renegotiation.",
        "docs_url": "https://developer.zylo.com/reference/savingseventscontroller_getsavingsevents",
        "columns": _columns(
            id="Unique identifier for the savings event.",
            application_id="ID of the application the savings event relates to.",
            name="Name of the savings event.",
            description="Description of the savings event.",
            event_type="Type of savings event.",
            value_type="Whether the recorded value is monetary or numerical.",
            monetary_value="Monetary value of the savings, when `value_type` is monetary.",
            numerical_value="Numerical value of the savings, when `value_type` is numerical.",
            unit_of_measure="Unit the numerical value is measured in.",
            transaction_date="Date of the transaction the savings event relates to.",
            is_custom="Whether the savings event was manually created rather than system-detected.",
            exclude_from_event_total="Whether the event is excluded from aggregate savings totals.",
            notes="Free-form notes on the savings event.",
        ),
    },
    "ApplicationBudgets": {
        "description": "A yearly budget allocation for an application.",
        "docs_url": "https://developer.zylo.com/reference/applicationbudgetscontroller_getapplicationbudgets",
        "columns": _columns(
            application_id="ID of the application the budget applies to.",
            year="Fiscal year the budget applies to.",
            budget_amount="Budgeted amount for the application in the given year.",
        ),
    },
    "ActivityHistory": {
        "description": "An audit log entry recording a change to a Zylo record.",
        "docs_url": "https://developer.zylo.com/reference/activityhistorycontroller_getactivityhistory",
        "columns": _columns(
            id="Unique identifier for the activity history entry.",
            resource_id="ID of the resource the activity relates to.",
            event_name="Name of the event that occurred.",
            event_by="Identifier of the user or system that performed the event.",
            event_at="Date and time the event occurred.",
            before="Value of the changed property before the event.",
            after="Value of the changed property after the event.",
        ),
    },
}
