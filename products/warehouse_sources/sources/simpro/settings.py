from dataclasses import dataclass

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

SIMPRO_API_VERSION = "v1.0"

# Simpro documents 250 as the largest pageSize a list endpoint accepts.
PAGE_SIZE = 250

# Every Simpro build is served from one of these domains. A bare build name uses the first one.
BUILD_DOMAINS = ("simprosuite.com", "simprocloud.com")
DEFAULT_BUILD_DOMAIN = BUILD_DOMAINS[0]

COMPANY_ID_COLUMN = "CompanyID"
DATE_MODIFIED = "DateModified"


@dataclass(frozen=True)
class SimproEndpointConfig:
    name: str
    path: str
    # Simpro list endpoints return only a few columns unless `columns=` names the rest. None sends
    # no `columns` parameter, for endpoints whose default list already returns the full object.
    columns: tuple[str, ...] | None
    # List endpoints with an `Archived` column return only active rows by default, so these
    # endpoints run one pass with `Archived=false` and one with `Archived=true`.
    archivable: bool = False
    # Whether the `DateModified=ge(...)` search filter can drive incremental syncs.
    incremental: bool = False
    partition_key: str | None = None


_CUSTOMER_COLUMNS = (
    "Phone",
    "DoNotCall",
    "AltPhone",
    "Email",
    "Address",
    "BillingAddress",
    "CustomerType",
    "Tags",
    "AmountOwing",
    "Rates",
    "Profile",
    "PreferredTechs",
    "Archived",
    "Sites",
    "Contracts",
    "Contacts",
    "ResponseTimes",
    "CustomFields",
    "DateCreated",
    "DateModified",
)

ENDPOINT_CONFIGS: dict[str, SimproEndpointConfig] = {
    config.name: config
    for config in (
        SimproEndpointConfig(
            name="company_customers",
            path="customers/companies/",
            columns=("ID", "CompanyName", "Fax", "Website", "EIN", "CompanyNumber", *_CUSTOMER_COLUMNS),
            archivable=True,
            incremental=True,
            partition_key="DateCreated",
        ),
        SimproEndpointConfig(
            name="individual_customers",
            path="customers/individuals/",
            columns=("ID", "Title", "GivenName", "FamilyName", "CellPhone", *_CUSTOMER_COLUMNS),
            archivable=True,
            incremental=True,
            partition_key="DateCreated",
        ),
        SimproEndpointConfig(
            name="sites",
            path="sites/",
            columns=(
                "ID",
                "Name",
                "Address",
                "BillingAddress",
                "BillingContact",
                "PrimaryContact",
                "PublicNotes",
                "PrivateNotes",
                "Zone",
                "PreferredTechnicians",
                "Customers",
                "Archived",
                "STCZone",
                "VEECZone",
                "CustomFields",
                "Rates",
                "DateModified",
            ),
            archivable=True,
            incremental=True,
        ),
        SimproEndpointConfig(
            name="contacts",
            path="contacts/",
            columns=(
                "ID",
                "Title",
                "GivenName",
                "FamilyName",
                "Email",
                "WorkPhone",
                "Fax",
                "CellPhone",
                "AltPhone",
                "Department",
                "Position",
                "Notes",
                "CustomFields",
                "Customers",
                "Sites",
                "Vendors",
                "DateModified",
            ),
            incremental=True,
        ),
        SimproEndpointConfig(
            name="jobs",
            path="jobs/",
            columns=(
                "ID",
                "Type",
                "Customer",
                "CustomerContract",
                "CustomerContact",
                "AdditionalContacts",
                "Site",
                "SiteContact",
                "OrderNo",
                "RequestNo",
                "Name",
                "Description",
                "Notes",
                "DateIssued",
                "DueDate",
                "DueTime",
                "CompletedDate",
                "Tags",
                "Salesperson",
                "ProjectManager",
                "Technicians",
                "Stage",
                "ArchiveReason",
                "Status",
                "ResponseTime",
                "IsVariation",
                "LinkedVariations",
                "ConvertedFromQuote",
                "ConvertedFrom",
                "AutoAdjustStatus",
                "IsRetentionEnabled",
                "Total",
                "Totals",
                "CustomFields",
                "STC",
                "DateModified",
            ),
            # Changes to a job's sections and cost centres can move its totals without moving its
            # DateModified, so a DateModified filter could miss them. Jobs sync in full.
        ),
        SimproEndpointConfig(
            name="quotes",
            path="quotes/",
            columns=(
                "ID",
                "Customer",
                "AdditionalCustomers",
                "CustomerContact",
                "AdditionalContacts",
                "Site",
                "SiteContact",
                "ConvertedFromLead",
                "Name",
                "Description",
                "Notes",
                "Type",
                "Salesperson",
                "ProjectManager",
                "Technicians",
                "DateIssued",
                "DateApproved",
                "DueDate",
                "ValidityDays",
                "OrderNo",
                "RequestNo",
                "IsClosed",
                "ArchiveReason",
                "Stage",
                "CustomerStage",
                "JobNo",
                "IsVariation",
                "LinkedJobID",
                "Forecast",
                "Total",
                "Totals",
                "Status",
                "Tags",
                "AutoAdjustStatus",
                "CustomFields",
                "STC",
                "DateModified",
            ),
            incremental=True,
        ),
        SimproEndpointConfig(
            name="leads",
            path="leads/",
            columns=(
                "ID",
                "LeadName",
                "Customer",
                "AdditionalCustomers",
                "CustomerContact",
                "AdditionalContacts",
                "Site",
                "SiteContact",
                "Stage",
                "FollowUpDate",
                "Description",
                "Notes",
                "CostCenter",
                "Tags",
                "Salesperson",
                "ProjectManager",
                "Status",
                "Forecast",
                "AutoAdjustStatus",
                "CustomFields",
                "DateCreated",
                "DateModified",
            ),
            incremental=True,
            partition_key="DateCreated",
        ),
        SimproEndpointConfig(
            name="invoices",
            path="invoices/",
            columns=(
                "ID",
                "Type",
                "Customer",
                "Jobs",
                "RecurringInvoice",
                "DateIssued",
                "Period",
                "PaymentTerms",
                "ProgressClaimNumber",
                "IsFinalClaim",
                "Stage",
                "PerItem",
                "OrderNo",
                "LatePaymentFee",
                "CISDeductionRate",
                "ExchangeRate",
                "AccountingCategory",
                "Status",
                "AutoAdjustStatus",
                "Description",
                "Notes",
                "Total",
                "IsRetainage",
                "Retainage",
                "IsPaid",
                "DatePaid",
                "Currency",
                "CustomFields",
                "CostCenters",
                "DateCreated",
                "DateModified",
            ),
            incremental=True,
            partition_key="DateCreated",
        ),
        SimproEndpointConfig(
            name="credit_notes",
            path="creditNotes/",
            columns=(
                "ID",
                "Customer",
                "InvoiceNo",
                "Jobs",
                "CostCenters",
                "DateIssued",
                "Stage",
                "Status",
                "Total",
                "DateModified",
            ),
            incremental=True,
        ),
        SimproEndpointConfig(
            name="customer_payments",
            path="customerPayments/",
            columns=None,
        ),
        SimproEndpointConfig(
            name="employees",
            path="employees/",
            # Leaves out the home address, date of birth, emergency contact, masked SSN and bank details.
            columns=(
                "ID",
                "Name",
                "Position",
                "Availability",
                "DateOfHire",
                "PrimaryContact",
                "AccountSetup",
                "UserProfile",
                "Archived",
                "AssignedCostCenters",
                "Zones",
                "DefaultZone",
                "DefaultCompany",
                "CustomFields",
                "PayRates",
                "DateCreated",
                "DateModified",
            ),
            archivable=True,
            incremental=True,
            partition_key="DateCreated",
        ),
        SimproEndpointConfig(
            name="schedules",
            path="schedules/",
            columns=("ID", "Type", "Reference", "TotalHours", "Staff", "Date", "Blocks", "DateModified"),
            incremental=True,
        ),
        SimproEndpointConfig(
            name="catalog_items",
            path="catalogs/",
            columns=("ID", "PartNo", "Name", "Archived", "DateModified"),
            archivable=True,
            incremental=True,
        ),
        SimproEndpointConfig(
            name="vendors",
            path="vendors/",
            columns=("ID", "Name", "Profile", "Archived", "DateCreated", "DateModified"),
            archivable=True,
            incremental=True,
            partition_key="DateCreated",
        ),
        SimproEndpointConfig(
            name="vendor_orders",
            path="vendorOrders/",
            columns=(
                "ID",
                "Type",
                "Description",
                "IsInventoryItem",
                "AssignedTo",
                "Stage",
                "Status",
                "StatusAutoAdjust",
                "DateIssued",
                "Vendor",
                "QuoteNo",
                "Reference",
                "DueDate",
                "VendorQuote",
                "VendorNotes",
                "PrivateNotes",
                "CreatedBy",
                "Archived",
                "Totals",
                "DateModified",
            ),
            archivable=True,
            # Receipts and credits on an order can change without moving the order's DateModified.
        ),
        SimproEndpointConfig(
            name="cost_centers",
            path="setup/accounts/costCenters/",
            columns=("ID", "Name", "IncomeAccountNo", "ExpenseAccountNo", "Type", "Archived", "IsMembershipCostCenter"),
            archivable=True,
        ),
    )
}

ENDPOINTS = tuple(ENDPOINT_CONFIGS)

PRIMARY_KEYS = [COMPANY_ID_COLUMN, "ID"]

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": DATE_MODIFIED,
            "type": IncrementalFieldType.DateTime,
            "field": DATE_MODIFIED,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name, config in ENDPOINT_CONFIGS.items()
    if config.incremental
}
