"""Canonical, documentation-sourced descriptions for Simpro endpoints and columns.

Sourced from the Simpro REST API v1.0 reference (https://developer.simprogroup.com/apidoc/).
Keyed by the endpoint names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Simpro table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_DOCS = "https://developer.simprogroup.com/apidoc/?page="

_COMMON_COLUMNS = {
    "CompanyID": "ID of the Simpro company the row was read from. Builds without multi-company setup use company 0.",
    "ID": "Unique identifier of the record in the Simpro build.",
    "DateModified": "Time the record was last modified, in RFC 3339 format with the build's UTC offset.",
    "CustomFields": "Values of the custom fields that the build defines for this record type.",
}

_CUSTOMER_COLUMNS = {
    "Phone": "Telephone number.",
    "DoNotCall": "Whether the customer must not be contacted by phone.",
    "AltPhone": "Alternative telephone number.",
    "Email": "Email address of the customer.",
    "Address": "Physical address of the customer's office.",
    "BillingAddress": "Mailing address for the customer's bills.",
    "CustomerType": "Whether this is a customer or a lead.",
    "Tags": "User-defined customer tags that apply to this customer.",
    "AmountOwing": "Amount the customer owes.",
    "Rates": "Pricing rates that apply to the customer, such as the price tier and markups.",
    "Profile": "Customer profile settings, such as the customer group, payment terms and notes.",
    "PreferredTechs": "Technicians that Simpro assigns to this customer's quotes and jobs automatically.",
    "Archived": "Whether the customer is archived.",
    "Sites": "Sites to which this customer is linked.",
    "Contracts": "Service contracts of the customer.",
    "Contacts": "Contacts of the customer.",
    "ResponseTimes": "Response times that apply to the customer.",
    "DateCreated": "Time the customer was created, in RFC 3339 format.",
}


def _columns(*groups: dict[str, str], **columns: str) -> dict[str, str]:
    merged = dict(_COMMON_COLUMNS)
    for group in groups:
        merged.update(group)
    merged.update(columns)
    return merged


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "company_customers": {
        "description": "Customers that are businesses, with their contact details, billing settings and linked sites.",
        "docs_url": f"{_DOCS}e6d0e1c8fc6a4fcf47869df87e04cd88",
        "columns": _columns(
            _CUSTOMER_COLUMNS,
            CompanyName="Name of the customer company.",
            Fax="Fax number.",
            Website="Website of the customer.",
            EIN="Business tax number of the customer, such as the EIN, ABN, GST or VAT registration number.",
            CompanyNumber="Company number of the customer. UK builds only.",
        ),
    },
    "individual_customers": {
        "description": "Customers that are people, with their contact details, billing settings and linked sites.",
        "docs_url": f"{_DOCS}e6d0e1c8fc6a4fcf47869df87e04cd88",
        "columns": _columns(
            _CUSTOMER_COLUMNS,
            Title="Title of the customer, such as Mr or Dr.",
            GivenName="Given name of the customer.",
            FamilyName="Family name of the customer.",
            CellPhone="Mobile phone number.",
        ),
    },
    "sites": {
        "description": "Sites: the locations where work is done for customers.",
        "docs_url": f"{_DOCS}3faa64303d5f5bcd043bb88f6768e603",
        "columns": _columns(
            Name="Name of the site.",
            Address="Address of the site.",
            BillingAddress="Billing address of the site.",
            BillingContact="Contact who receives bills for the site.",
            PrimaryContact="Main contact at the site.",
            PublicNotes="Notes that customers can see. Can contain HTML.",
            PrivateNotes="Internal notes. Can contain HTML.",
            Zone="Zone of the site.",
            PreferredTechnicians="Preferred technicians of the site, with asset type and service level.",
            Customers="Customers linked to the site.",
            Archived="Whether the site is archived.",
            STCZone="Small-scale technology certificate (STC) zone number of the site location.",
            VEECZone="Victorian Energy Efficiency Certificate (VEEC) zone of the site location.",
            Rates="Pricing rates that apply to the site.",
        ),
    },
    "contacts": {
        "description": "Contacts: people linked to customers, sites or vendors.",
        "docs_url": f"{_DOCS}9aa698f602b1e5694855cee73a683488",
        "columns": _columns(
            Title="Title of the contact.",
            GivenName="Given name of the contact.",
            FamilyName="Family name of the contact.",
            Email="Email address of the contact.",
            WorkPhone="Work phone number.",
            Fax="Fax number.",
            CellPhone="Mobile phone number.",
            AltPhone="Alternate phone number, which can be a home phone.",
            Department="Department of the contact.",
            Position="Position of the contact.",
            Notes="Notes about the contact.",
            Customers="Customers to which the contact is linked.",
            Sites="Sites to which the contact is linked.",
            Vendors="Vendors to which the contact is linked.",
        ),
    },
    "jobs": {
        "description": "Jobs: service and project work done for a customer at a site, with stage, status and totals.",
        "docs_url": f"{_DOCS}12ceff2290bb9039beaa8f36d5dec226",
        "columns": _columns(
            Type="Job type, such as Project or Service.",
            Customer="Customer of the job.",
            CustomerContract="Customer contract the job is done under.",
            CustomerContact="Customer contact for the job.",
            Site="Site where the job is done.",
            SiteContact="Site contact for the job.",
            OrderNo="Customer order number.",
            Name="Name of the job.",
            Description="Description of the job. Can contain HTML.",
            Notes="Notes on the job. Can contain HTML.",
            DateIssued="Date the job was issued, as YYYY-MM-DD.",
            DueDate="Date the job is due, as YYYY-MM-DD.",
            DueTime="Time the job is due, as HH:MM.",
            CompletedDate="Date the job was completed, as YYYY-MM-DD.",
            Salesperson="Salesperson of the job.",
            ProjectManager="Project manager of the job.",
            Technicians="Technicians assigned to the job.",
            Stage="Job stage: jobs move from pending to in progress, complete, invoiced and archived.",
            ArchiveReason="Reason the job was archived.",
            Status="Workflow status of the job.",
            IsVariation="Whether the job is a variation of another job.",
            ConvertedFrom="Quote or recurring job the job was converted from, if any.",
            Total="Total of the job, excluding and including tax.",
            Totals="Cost, revenue and profit totals of the job.",
        ),
    },
    "quotes": {
        "description": "Quotes: priced proposals for work, which can convert into jobs.",
        "docs_url": f"{_DOCS}c9a28e7f0dbc3ed20a161351c4f29a7b",
        "columns": _columns(
            Customer="Customer of the quote.",
            Site="Site where the quoted work is done.",
            ConvertedFromLead="Lead the quote was converted from, if any.",
            Name="Name of the quote.",
            Description="Description of the quote. Can contain HTML.",
            DateIssued="Date the quote was issued, as YYYY-MM-DD.",
            DateApproved="Date the quote was approved, as YYYY-MM-DD.",
            DueDate="Date the quote is due, as YYYY-MM-DD.",
            ValidityDays="Number of days the quote stays valid.",
            IsClosed="Whether the quote is closed.",
            Stage="Quote stage, such as in progress, complete or approved.",
            CustomerStage="Stage of the quote from the customer's side, such as accepted or declined.",
            JobNo="Number of the job the quote converted into, if any.",
            LinkedJobID="ID of the job linked to the quote, if any.",
            Forecast="Sales forecast of the quote, such as the expected close date and the chance of winning.",
            Total="Total of the quote, excluding and including tax.",
            Status="Workflow status of the quote.",
        ),
    },
    "leads": {
        "description": "Leads: potential work for a customer before it becomes a quote.",
        "docs_url": f"{_DOCS}ae5361473c0038d7f8c4b4236c50b2da",
        "columns": _columns(
            LeadName="Name of the lead.",
            Customer="Customer of the lead.",
            Site="Site of the lead.",
            Stage="Lead stage.",
            FollowUpDate="Date to follow up on the lead, as YYYY-MM-DD.",
            Description="Description of the lead.",
            Salesperson="Salesperson of the lead.",
            Status="Workflow status of the lead.",
            Forecast="Sales forecast of the lead.",
            DateCreated="Time the lead was created, in RFC 3339 format.",
        ),
    },
    "invoices": {
        "description": "Customer invoices raised from jobs or recurring invoices.",
        "docs_url": f"{_DOCS}fce9a6a1bd2a2050eb86d33103f46fd3",
        "columns": _columns(
            ID="Invoice number.",
            Type="Type of the invoice.",
            Customer="Customer billed by the invoice.",
            Jobs="Jobs invoiced. Empty for an invoice made from a recurring invoice.",
            RecurringInvoice="Recurring invoice that made this invoice. Empty for an invoice made from jobs.",
            DateIssued="Issue date of the invoice, as YYYY-MM-DD.",
            PaymentTerms="Payment terms of the invoice.",
            ProgressClaimNumber="Number of the progress claim, in order of issue.",
            IsFinalClaim="Whether the invoice is a progress claim marked as the final claim.",
            Stage="Approval stage of the invoice.",
            ExchangeRate="Exchange rate used when the invoice currency differs from the default currency.",
            Status="Workflow status of the invoice.",
            Description="Description of the invoice.",
            Notes="Footnote of the invoice.",
            Total="Total of the invoice, excluding and including tax.",
            IsRetainage="Whether the invoice is a retainage claim.",
            Retainage="Retainage amounts per job, where retainage is turned on.",
            IsPaid="Whether the invoice is fully paid.",
            DatePaid="Date the invoice was fully paid.",
            Currency="Currency of the invoice.",
            CostCenters="Cost centres invoiced.",
            DateCreated="Time the invoice was created, in RFC 3339 format.",
        ),
    },
    "credit_notes": {
        "description": "Credit notes issued against customer invoices.",
        "docs_url": f"{_DOCS}bd16af1838f0dd73a528391790db0115",
        "columns": _columns(
            Customer="Customer of the credit note.",
            InvoiceNo="Number of the invoice the credit note applies to.",
            Jobs="Jobs the credit note applies to.",
            DateIssued="Issue date of the credit note, as YYYY-MM-DD.",
            Total="Total of the credit note, excluding and including tax.",
        ),
    },
    "customer_payments": {
        "description": "Payments received from customers.",
        "docs_url": f"{_DOCS}166bb94a7df2dd7995b3aca6254e02f0",
        "columns": {
            "CompanyID": _COMMON_COLUMNS["CompanyID"],
            "ID": "Unique identifier of the payment.",
            "Payment": "Payment details: payment method, status, deposit account, date, finance charge and check number.",
        },
    },
    "employees": {
        "description": "Employees of the business, with their position, cost centres and pay rates.",
        "docs_url": f"{_DOCS}eb626c94531ec554f93b2b78a77c8b1b",
        "columns": _columns(
            Name="Full name of the employee.",
            Position="Position of the employee.",
            DateOfHire="Date the employee was hired, as YYYY-MM-DD.",
            PrimaryContact="Work contact details of the employee.",
            Archived="Whether the employee is archived.",
            AssignedCostCenters="Cost centres the employee is assigned to.",
            PayRates="Pay rates of the employee.",
            DateCreated="Time the employee was created, in RFC 3339 format.",
        ),
    },
    "schedules": {
        "description": "Schedules: blocks of staff time booked against jobs, quotes or activities.",
        "docs_url": f"{_DOCS}ccdb7bf9d93e5652b57cabcc8c41e061",
        "columns": _columns(
            Type="Type of the schedule, such as job, quote or activity.",
            Reference="For an activity, the activity type ID. For a job or quote, the job or quote ID and cost centre ID.",
            TotalHours="Total hours of the schedule.",
            Staff="Staff member assigned to the schedule.",
            Date="Date of the schedule, as YYYY-MM-DD.",
            Blocks="Time blocks of the schedule, with start and end times.",
        ),
    },
    "catalog_items": {
        "description": "Catalog items: the materials and parts the business buys and sells.",
        "docs_url": f"{_DOCS}5408c752aea14ba352fc3dad16b268d8",
        "columns": _columns(
            PartNo="Part number of the item.",
            Name="Name of the item.",
            Archived="Whether the item is archived.",
        ),
    },
    "vendors": {
        "description": "Vendors: the suppliers the business buys from.",
        "docs_url": f"{_DOCS}be3439768cb74608cedb2e37a74820d7",
        "columns": _columns(
            Name="Name of the vendor.",
            Profile="Vendor profile settings.",
            Archived="Whether the vendor is archived.",
            DateCreated="Time the vendor was created, in RFC 3339 format.",
        ),
    },
    "vendor_orders": {
        "description": "Vendor orders: purchase orders sent to suppliers.",
        "docs_url": f"{_DOCS}1ce5d9607216ee37fb61fe793d38e2c3",
        "columns": _columns(
            Type="Type of the order.",
            Stage="Stage of the order.",
            Status="Workflow status of the order.",
            DateIssued="Issue date of the order, as YYYY-MM-DD.",
            Vendor="Vendor the order is sent to.",
            DueDate="Date the order is due, as YYYY-MM-DD.",
            Archived="Whether the order is archived.",
            Totals="Totals of the order.",
        ),
    },
    "cost_centers": {
        "description": "Cost centres: the accounting categories that job and quote costs and revenue are booked to.",
        "docs_url": f"{_DOCS}9b945efebb006547a94415eadaa12921",
        "columns": {
            "CompanyID": _COMMON_COLUMNS["CompanyID"],
            "ID": "Unique identifier of the cost centre.",
            "Name": "Name of the cost centre.",
            "IncomeAccountNo": "Income account number of the cost centre.",
            "ExpenseAccountNo": "Expense account number of the cost centre.",
            "Archived": "Whether the cost centre is archived.",
            "IsMembershipCostCenter": "Whether the cost centre is used for memberships.",
        },
    },
}
