"""Canonical, documentation-sourced descriptions for Rippling endpoints and columns.

Sourced from the official Rippling REST API reference (https://developer.rippling.com/documentation/rest-api).
Keyed by the endpoint names in `settings.py` `RIPPLING_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Rippling table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by every Rippling REST object.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_at": "Time at which the object was created.",
    "updated_at": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workers": {
        "description": "A worker (employee or contractor) in the company, with employment details.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-workers",
        "columns": _columns(
            user_id="ID of the user record associated with the worker.",
            company_id="ID of the company the worker belongs to.",
            employment_type_id="ID of the worker's employment type.",
            department_id="ID of the department the worker belongs to.",
            team_id="ID of the team the worker belongs to.",
            level_id="ID of the worker's job level.",
            work_location_id="ID of the worker's work location.",
            title="The worker's job title.",
            status="Employment status of the worker (e.g. ACTIVE, TERMINATED).",
            start_date="The worker's employment start date.",
            end_date="The worker's employment end date, if applicable.",
            employment_type="The worker's employment type (e.g. FULL_TIME, CONTRACTOR).",
        ),
    },
    "users": {
        "description": "A user account in the company directory, with contact and identity details.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-users",
        "columns": _columns(
            company_id="ID of the company the user belongs to.",
            name="The user's full name structured into given and family names.",
            preferred_first_name="The user's preferred first name.",
            emails="The user's email addresses.",
            phone_numbers="The user's phone numbers.",
            status="Status of the user account (e.g. ACTIVE, INACTIVE).",
            username="The user's username.",
        ),
    },
    "companies": {
        "description": "A company (legal entity) in the Rippling account.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-companies",
        "columns": _columns(
            name="The company's legal name.",
            display_name="The company's display name.",
            legal_name="The company's registered legal name.",
            phone_number="The company's phone number.",
            primary_email="The company's primary contact email.",
            ein="The company's Employer Identification Number.",
            address="The company's address.",
        ),
    },
    "departments": {
        "description": "A department within the company used to organize workers.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-departments",
        "columns": _columns(
            company_id="ID of the company the department belongs to.",
            name="The department's name.",
            parent_id="ID of the parent department, if nested.",
        ),
    },
    "teams": {
        "description": "A team within the company used to group workers.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-teams",
        "columns": _columns(
            company_id="ID of the company the team belongs to.",
            name="The team's name.",
            parent_id="ID of the parent team, if nested.",
        ),
    },
    "levels": {
        "description": "A job level (seniority tier) used to classify workers.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-levels",
        "columns": _columns(
            company_id="ID of the company the level belongs to.",
            name="The level's name.",
            rank="Numeric rank ordering the level relative to others.",
            track_id="ID of the career track the level belongs to.",
        ),
    },
    "work_locations": {
        "description": "A physical work location (office or site) for the company.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-work-locations",
        "columns": _columns(
            company_id="ID of the company the work location belongs to.",
            name="The work location's name.",
            address="The work location's address.",
        ),
    },
    "employment_types": {
        "description": "An employment type classifying how workers are employed (e.g. full-time, contractor).",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-employment-types",
        "columns": _columns(
            company_id="ID of the company the employment type belongs to.",
            name="The employment type's name.",
            label="Display label for the employment type.",
            type="The category of employment (e.g. SALARIED, HOURLY, CONTRACTOR).",
            compensation_time_period="The time period over which compensation is measured.",
        ),
    },
    "compensations": {
        "description": "A worker's compensation record, including pay rate and structure.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/get-compensations",
        "columns": _columns(
            worker_id="ID of the worker this compensation applies to.",
            currency="Three-letter ISO currency code of the compensation.",
            payment_rate="The worker's pay rate.",
            payment_time_period="The time period the pay rate is measured over (e.g. HOUR, YEAR).",
            payment_type="The type of payment (e.g. SALARY, HOURLY).",
            annual_compensation="The worker's annualized compensation.",
            effective_date="Date the compensation took effect.",
        ),
    },
    "variable_compensation_payouts": {
        "description": "A variable compensation payout (bonus, commission or other one-off pay) scheduled for a worker.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/list-variable-compensation-payouts",
        "columns": _columns(
            payee_id="ID of the worker who receives the payout.",
            client="Client system that created the payout (e.g. VC_PLAN_CYCLE, MANUAL_PAYOUT).",
            external_id="External identifier, unique per company and client.",
            currency_type="Three-letter currency code of the payout.",
            value="Payout amount as a decimal string.",
            pay_classification="Payroll earning code resolved from the payout type.",
            payout_type="Key of the company payout type used for the payout.",
            scheduled_date="Date the payout is scheduled for.",
            effective_start_date="Start date of the covered pay period.",
            effective_end_date="End date of the covered pay period.",
            description="Optional payout description.",
            status="Current payout status (e.g. SCHEDULED, PAID, CANCELLED).",
            cancel_reason="Reason given when the payout was cancelled.",
            source_label_id="ID of the source label attached to the payout.",
            group_label_id="ID of the group label attached to the payout.",
            paystub_id="ID of the paystub once the payout has synced to payroll.",
        ),
    },
    "time_entries": {
        "description": "A time entry recording when a worker clocked in and out, with breaks, shifts and pay segments.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/list-time-entries",
        "columns": _columns(
            worker_id="ID of the worker associated with the time entry.",
            start_time="The start time of the time entry.",
            end_time="The end time of the time entry.",
            comments="The comments associated with the time entry.",
            job_shifts="The job shifts worked during the time entry.",
            breaks="The breaks taken during the time entry.",
            premiums="The premiums earned during the time entry.",
            piece_rate_premiums="The piece-rate premiums earned during the time entry.",
            segments="The pay rates for each segment of the time entry.",
            time_entry_summary="A summary of the time entry.",
            time_card_id="ID of the time card associated with the time entry.",
            tags="The tags associated with the time entry.",
            idempotency_key="The unique key of the time entry in an outside system.",
            create_extra_hours_run="Whether the time entry should create an extra hours run.",
            status="The status of the time entry.",
            pay_period="The pay period associated with the time card.",
            shift_input_values="Arbitrary shift inputs collected on the time entry.",
        ),
    },
    "leave_requests": {
        "description": "A request by a worker for time off, with its dates, status and review details.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/list-leave-requests",
        "columns": _columns(
            worker_id="ID of the worker associated with the leave request.",
            requester_id="ID of the worker who requested the leave.",
            status="The status of the leave request.",
            start_date="The start date of the leave request.",
            start_time="The start time of the leave request.",
            end_date="The end date of the leave request.",
            end_time="The end time of the leave request.",
            comments="The comments associated with the leave request.",
            number_of_minutes_requested="The number of minutes requested.",
            leave_policy_id="ID of the leave policy associated with the leave request.",
            leave_type_id="ID of the leave type associated with the leave request.",
            leave_event_id="ID of the leave event associated with the leave request, if any.",
            reason_for_leave="The reason for the leave request.",
            reviewer_id="ID of the worker who reviewed the leave request.",
            reviewed_at="Time at which the leave request was reviewed.",
            days_take_off="The specific dates taken off and the amount of time taken off on each one.",
            is_managed_by_external_system="Whether the leave request is managed by an external system.",
        ),
    },
    "payroll_runs": {
        "description": "A payroll run: one pay period's payroll for a company entity, with its dates and state.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/list-payroll-runs",
        "columns": {
            "id": "Unique identifier for the payroll run.",
            "run_state": "Current state of the run (e.g. DRAFT, APPROVED, PAID).",
            "run_type": "Type of the run (e.g. REGULAR, OFF_CYCLE, CORRECTION).",
            "check_date": "Date the paycheck is issued.",
            "debit_date": "Date funds are debited from the company's account.",
            "title": "Human-readable title of the payroll run.",
            "approval_deadline": "Deadline for approving the payroll run.",
            "approved_at": "Time at which the run was approved.",
            "paid_at": "Time at which the run was marked as paid.",
            "lock_deadline": "Deadline after which the run is locked for changes.",
            "pay_period": "Pay period details for the run.",
            "company_entity_id": "ID of the company legal entity the payroll run belongs to.",
            "country_code": "ISO country code where the payroll run applies.",
            "payment_type": "Payment method used (e.g. WIRE, ACH).",
        },
    },
    "worker_payroll_records": {
        "description": "A worker's payroll record within a payroll run: gross and net pay, earnings, taxes, deductions and garnishments.",
        "docs_url": "https://developer.rippling.com/documentation/rest-api/reference/list-worker-payroll-records",
        "columns": {
            "id": "Unique identifier for the payroll record.",
            "run_id": "ID of the payroll run the record belongs to.",
            "worker_id": "ID of the worker the record belongs to.",
            "currency": "ISO currency code for the monetary amounts in the record.",
            "country_code": "ISO country code where the payroll record applies.",
            "net_pay": "Net pay amount for the period.",
            "gross_pay": "Gross pay amount for the period.",
            "summary": "Aggregate totals for taxes, deductions and garnishments.",
            "earnings": "List of earning line items.",
            "taxes": "List of tax line items.",
            "deductions": "List of deduction line items.",
            "garnishments": "List of garnishment line items.",
        },
    },
}
