from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "jobs": {
        "description": "Jobs and leads, with their current milestone, contact, location, and lead source.",
        "docs_url": "https://apidocs.acculynx.com/reference/getjobs",
        "columns": {
            "id": "Unique job identifier.",
            "createdDate": "Date and time the job was created.",
            "modifiedDate": "Date and time the job was last modified.",
            "currentMilestone": "Current stage of the job's workflow.",
            "milestoneDate": "Date and time the job last changed milestone.",
        },
    },
    "contacts": {
        "description": "Contacts with their email addresses, phone numbers, mailing address, and billing address.",
        "docs_url": "https://apidocs.acculynx.com/reference/getcontacts",
        "columns": {"id": "Unique contact identifier.", "createdDate": "Date and time the contact was created."},
    },
    "estimates": {
        "description": "Detailed job estimates, including financial totals, profit, and section references.",
        "docs_url": "https://apidocs.acculynx.com/reference/getestimatebyid",
        "columns": {
            "id": "Unique estimate identifier.",
            "estimate_id": "Identifier from the parent estimate listing.",
            "createdDate": "Date and time the estimate was created, in UTC.",
            "isPrimary": "Whether this is the primary estimate for the job.",
        },
    },
    "invoices": {
        "description": "Invoices for each job, including totals, balance due, invoice state, and sections.",
        "docs_url": "https://apidocs.acculynx.com/reference/getinvoicesforjob",
        "columns": {
            "id": "Unique invoice identifier.",
            "job_id": "Identifier of the job whose invoices were requested.",
            "createdDate": "Date and time the invoice was created.",
        },
    },
    "financials": {
        "description": "Job financial summaries with approved job value, balance due, and worksheet section totals.",
        "docs_url": "https://apidocs.acculynx.com/reference/getfinancialsforjob",
        "columns": {
            "id": "Unique financial record identifier.",
            "job_id": "Identifier of the job whose financials were requested.",
        },
    },
    "payments": {
        "description": "Received payments, paid payments, and additional expenses for each job.",
        "docs_url": "https://apidocs.acculynx.com/reference/getpayments",
        "columns": {
            "id": "Unique payment or expense identifier within its job and category.",
            "job_id": "Identifier of the job whose payments were requested.",
            "payment_category": "Payment group: receivedPayments, paidPayments, or additionalExpenses.",
            "parentId": "Identifier of the parent payment for a sub-payment.",
            "amount": "Amount of the payment or expense.",
        },
    },
    "job_milestone_history": {
        "description": "Milestones each job has moved through, with the date it entered each one.",
        "docs_url": "https://apidocs.acculynx.com/reference/getmilestonesforjob",
        "columns": {
            "job_id": "Identifier of the job whose milestone history was requested.",
            "name": "Name of the milestone.",
            "date": "Date and time the job was set to this milestone, in UTC.",
        },
    },
    "job_history": {
        "description": "Actions performed on each job, with the action type and the user who performed it.",
        "docs_url": "https://apidocs.acculynx.com/reference/getjobhistory",
        "columns": {
            "job_id": "Identifier of the job whose history was requested.",
            "action": "Description of the action performed on the job.",
            "type": "Type of action, such as Job, Estimate, Payments, or Appointment.",
            "date": "Date and time the action happened, in UTC.",
            "createdBy": "User who performed the action.",
        },
    },
    "financial_amendments": {
        "description": "Amendments to job financials, with their state, title, total price, and worksheet sections.",
        "docs_url": "https://apidocs.acculynx.com/reference/getworksheetamendmentsbyid",
        "columns": {
            "id": "Unique amendment identifier.",
            "financials_id": "Identifier of the financial record whose amendments were requested.",
            "jobId": "Identifier of the job the amendment belongs to.",
            "currentState": "Current state of the amendment.",
            "totalPrice": "Total price of the amendment.",
            "createdDate": "Date and time the amendment was created, in UTC.",
            "modifiedDate": "Date and time the amendment was last modified, in UTC.",
        },
    },
    "estimate_section_items": {
        "description": "Line items in each estimate section, with quantities, units, material and labor costs, and prices.",
        "docs_url": "https://apidocs.acculynx.com/reference/getestimatesectionitems",
        "columns": {
            "id": "Unique estimate item identifier.",
            "estimate_id": "Identifier of the estimate that contains the section.",
            "estimate_section_id": "Identifier of the estimate section that contains the item.",
            "materialCost": "Material cost of the item.",
            "laborCost": "Labor cost of the item.",
            "quantity": "Quantity of the item.",
            "price": "Price of the item.",
            "totalPrice": "Total price of the item.",
        },
    },
    "job_representatives": {
        "description": "Users assigned to each job as company representative, sales owner, A/R owner, or additional representative.",
        "docs_url": "https://apidocs.acculynx.com/reference/getrepresentativesforjob",
        "columns": {
            "job_id": "Identifier of the job whose representatives were requested.",
            "type": "Representative role: CompanyRepresentative, SalesOwner, AROwner, or Additional.",
            "user": "AccuLynx user assigned to the role.",
        },
    },
    "job_contacts": {
        "description": "Contacts linked to each job, including the primary contact and how others relate to them.",
        "docs_url": "https://apidocs.acculynx.com/reference/getjobcontacts",
        "columns": {
            "job_id": "Identifier of the job whose contacts were requested.",
            "isPrimary": "Whether this is the primary contact for the job.",
            "relationToPrimary": "How this contact is related to the primary contact.",
            "contact": "Reference to the contact.",
        },
    },
    "job_custom_fields": {
        "description": "Custom field values set on each job.",
        "docs_url": "https://apidocs.acculynx.com/reference/getjobcustomfields",
        "columns": {
            "job_id": "Identifier of the job whose custom fields were requested.",
            "customFieldDefinition": "Reference to the custom field definition.",
            "label": "Custom field label.",
            "fieldType": "Data type of the custom field: Text, Number, Date, or Boolean.",
            "values": "Values set for the custom field.",
            "modifiedDate": "Date and time the custom field was modified, in UTC.",
        },
    },
    "custom_field_definitions": {
        "description": "Active custom field definitions for jobs and contacts, with their active options.",
        "docs_url": "https://apidocs.acculynx.com/reference/getcompanysettingscustomfields",
        "columns": {
            "id": "Unique custom field definition identifier.",
            "label": "Custom field label.",
            "entityType": "Record type the field applies to: job or contact.",
            "fieldType": "Data type of the custom field: Text, Number, Date, or Boolean.",
            "options": "Options available for the custom field.",
        },
    },
    "supplements": {
        "description": "Insurance supplements for jobs, with their state, assigned supplementer, and claim totals.",
        "docs_url": "https://apidocs.acculynx.com/reference/getfinancialssupplementsforcompany",
        "columns": {
            "id": "Unique supplement identifier.",
            "job": "Reference to the job the supplement belongs to.",
            "state": "Current state of the supplement.",
            "itemsToSupplement": "Original claim, requested, approved, and applied totals.",
            "createdDate": "Date and time the supplement was created.",
        },
    },
    "supplement_items": {
        "description": "Line items of each supplement, with original claim, requested, approved, and applied amounts.",
        "docs_url": "https://apidocs.acculynx.com/reference/getfinancialssupplementitemcollection",
        "columns": {
            "id": "Unique supplement item identifier.",
            "supplement_id": "Identifier of the supplement that contains the item.",
            "originalClaimAmount": "Amount in the original insurance claim.",
            "requestedAmount": "Amount requested in the supplement.",
            "approvedAmount": "Amount approved by the insurer.",
            "appliedAmount": "Amount applied to the job.",
        },
    },
    "supplement_notations": {
        "description": "Notes recorded on each supplement, with who was contacted, the supplement status, and the author.",
        "docs_url": "https://apidocs.acculynx.com/reference/getfinancialssupplementnotationcollection",
        "columns": {
            "id": "Unique notation identifier.",
            "supplement_id": "Identifier of the supplement whose notations were requested.",
            "status": "Reference to the supplement status recorded with the notation.",
            "spokeWith": "Person contacted for the notation.",
            "notes": "Text of the notation.",
            "createdBy": "User who created the notation.",
            "createdDate": "Date and time the notation was created.",
            "emailRecipients": "Users who received the notation by email.",
        },
    },
    "job_insurance": {
        "description": "Insurance claim details for each job, with the insurance company, date of loss, and claim number.",
        "docs_url": "https://apidocs.acculynx.com/reference/getinsuranceforjob",
        "columns": {
            "job_id": "Identifier of the job whose insurance was requested.",
            "insuranceCompany": "Insurance company from the list managed in account settings.",
            "customInsuranceCompanyName": "Insurance company name when it is not in the managed list.",
            "dateOfLoss": "Date the damage occurred, in UTC.",
            "claimFiled": "Whether the claim has been filed.",
            "claimFiledDate": "Date the claim was filed, in UTC.",
            "claimNumber": "Claim identifier given by the insurance company.",
            "hasPaperwork": "Whether the paperwork for the job is collected.",
        },
    },
    "insurance_companies": {
        "description": "Insurance companies defined for the connected location.",
        "docs_url": "https://apidocs.acculynx.com/reference/getinsurancecompanies",
        "columns": {
            "id": "Unique insurance company identifier.",
            "name": "Insurance company name.",
            "isActive": "Whether the insurance company is active.",
        },
    },
    "workflow_milestones": {
        "description": "Job workflow milestones defined for the company.",
        "docs_url": "https://apidocs.acculynx.com/reference/getmilestones",
        "columns": {"id": "Unique milestone identifier.", "name": "Milestone name."},
    },
    "calendars": {
        "description": "Calendars available for the connected AccuLynx location.",
        "docs_url": "https://apidocs.acculynx.com/reference/getcalendars",
        "columns": {"id": "Unique calendar identifier.", "name": "Calendar name."},
    },
    "calendar_appointments": {
        "description": "Calendar appointments within the configured date range, including attendees and job references.",
        "docs_url": "https://apidocs.acculynx.com/reference/getappointments",
        "columns": {
            "id": "Appointment identifier.",
            "calendar_id": "Identifier of the calendar whose appointments were requested.",
            "start": "Appointment start date and time.",
            "end": "Appointment end date and time.",
        },
    },
    "lead_sources": {
        "description": "Active lead sources for the connected location, including child lead sources.",
        "docs_url": "https://apidocs.acculynx.com/reference/getactiveleadsources",
        "columns": {"id": "Unique lead source identifier.", "name": "Lead source name."},
    },
    "users": {
        "description": "Company users across active, inactive, archived, and deleted statuses.",
        "docs_url": "https://apidocs.acculynx.com/reference/getusers",
        "columns": {"id": "Unique user identifier.", "status": "Current user status.", "role": "User role."},
    },
}
