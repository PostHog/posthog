from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the PayFit Partner API reference (https://developers.payfit.io/reference).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "collaborators": {
        "description": "An employee (collaborator) of your company in PayFit, including admins.",
        "docs_url": "https://developers.payfit.io/reference",
        "columns": {
            "id": "The unique ID of the collaborator.",
            "matricule": "Custom ID that can be set on a collaborator to ease synchronization with external software.",
            "firstName": "First name of the collaborator.",
            "lastName": "Last name of the collaborator.",
            "birthName": "Birth name of the collaborator.",
            "birthDate": "Birth date of the collaborator (YYYY-MM-DD).",
            "terminationDate": "End date of the collaborator's last active or current contract (YYYY-MM-DD).",
            "gender": "The gender of the collaborator.",
            "nationality": "Nationality of the collaborator (requires the collaborators:legal-identity:read scope).",
            "countryOfBirth": "Country of birth of the collaborator (requires the collaborators:legal-identity:read scope).",
            "emails": "List of emails of the collaborator.",
            "phoneNumbers": "List of phone numbers of the collaborator.",
            "addresses": "List of addresses of the collaborator.",
            "managerId": "The collaborator ID of this collaborator's manager, or null if they have no manager.",
            "teamName": "The team name of the collaborator, or null if they do not belong to a team.",
            "contracts": "The list of contracts of the collaborator (requires the collaborators:contracts:read scope).",
        },
    },
    "contracts": {
        "description": "An employment contract in your company in PayFit.",
        "docs_url": "https://developers.payfit.io/reference",
        "columns": {
            "contractId": "The unique ID of the contract.",
            "companyId": "The ID of the contract's company.",
            "collaboratorId": "The ID of the collaborator linked to the contract.",
            "startDate": "Contract start date.",
            "endDate": "Contract end date.",
            "probationEndDate": "Contract probation end date.",
            "jobName": "Job name of the employee.",
            "status": "Status of the contract.",
            "contactEmail": "The contact email of the contract (not validated by PayFit).",
            "standardWeeklyHours": "Weekly hours defined in the contract (requires the contracts:time-information:read scope).",
            "fullTimeEquivalent": "Percentage of weekly hours in the contract (requires the contracts:time-information:read scope).",
            "isFullTime": "Whether the contract is full time (fullTimeEquivalent at 1).",
        },
    },
    "absences": {
        "description": "An absence (leave) registered against a contract in PayFit. All statuses are synced, including pending, declined, and cancelled absences.",
        "docs_url": "https://developers.payfit.io/reference",
        "columns": {
            "id": "The unique ID of the absence.",
            "contractId": "Contract ID of the absence owner.",
            "startDate": "Date and moment of the day when the absence starts.",
            "endDate": "Date and moment of the day when the absence ends.",
            "type": "Type of the absence. 'Other' is used when the type is not yet defined.",
            "status": "Status of the absence (approved, pending_approval, declined, cancelled, or pending_cancellation).",
        },
    },
    "payslips": {
        "description": "A payslip issued to a collaborator for a given month in PayFit.",
        "docs_url": "https://developers.payfit.io/reference",
        "columns": {
            "collaboratorId": "The ID of the collaborator the payslip belongs to.",
            "payslipId": "The unique ID of the payslip.",
            "contractId": "The contract the payslip is associated with.",
            "year": "The year of the payslip.",
            "month": "The month of the payslip ('01' being January and '12' December).",
            "payslipUrl": "URL on the PayFit API to retrieve the payslip file.",
        },
    },
}
