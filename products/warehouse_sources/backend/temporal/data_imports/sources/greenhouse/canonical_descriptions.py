"""Canonical, documentation-sourced descriptions for Greenhouse Harvest endpoints and columns.

Sourced from the official Greenhouse Harvest API reference (https://developers.greenhouse.io/harvest.html).
Keyed by the endpoint names in `settings.py` `GREENHOUSE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Greenhouse table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Greenhouse objects.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_at": "Time at which the object was created.",
    "updated_at": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "candidates": {
        "description": "A person who has applied to or been sourced for a job in Greenhouse.",
        "docs_url": "https://developers.greenhouse.io/harvest.html#the-candidate-object",
        "columns": _columns(
            first_name="Candidate's first name.",
            last_name="Candidate's last name.",
            company="Candidate's current company.",
            title="Candidate's current job title.",
            is_private="Whether the candidate record is private.",
            email_addresses="The candidate's email addresses.",
            phone_numbers="The candidate's phone numbers.",
            social_media_addresses="The candidate's social media handles.",
            recruiter="The recruiter assigned to the candidate.",
            coordinator="The coordinator assigned to the candidate.",
            tags="Tags applied to the candidate.",
            applications="Applications associated with the candidate.",
            last_activity="Time of the candidate's most recent activity.",
        ),
    },
    "applications": {
        "description": "A candidate's application to a specific job in Greenhouse.",
        "docs_url": "https://developers.greenhouse.io/harvest.html#the-application-object",
        "columns": _columns(
            candidate_id="ID of the candidate who applied.",
            jobs="Jobs the application is for.",
            status="Status of the application (active, rejected, hired, or converted).",
            applied_at="Time at which the candidate applied.",
            rejected_at="Time at which the application was rejected, if applicable.",
            last_activity_at="Time of the most recent activity on the application.",
            source="The source the application came from.",
            current_stage="The interview stage the application is currently in.",
            rejection_reason="Reason the application was rejected, if applicable.",
            credited_to="The user credited with the application source.",
        ),
    },
    "jobs": {
        "description": "A job (role) being recruited for in Greenhouse.",
        "docs_url": "https://developers.greenhouse.io/harvest.html#the-job-object",
        "columns": _columns(
            name="Title of the job.",
            status="Status of the job (open, closed, or draft).",
            confidential="Whether the job is confidential.",
            requisition_id="External requisition ID for the job.",
            departments="Departments the job belongs to.",
            offices="Offices the job is located in.",
            hiring_team="Users on the job's hiring team.",
            openings="Open headcount for the job.",
            opened_at="Time at which the job was opened.",
            closed_at="Time at which the job was closed.",
        ),
    },
    "job_posts": {
        "description": "A public posting of a job to a job board or career site.",
        "docs_url": "https://developers.greenhouse.io/harvest.html#the-job-post-object",
        "columns": _columns(
            job_id="ID of the job this post is for.",
            title="Title of the job post.",
            location="Location shown on the job post.",
            internal="Whether the post is internal-only.",
            external="Whether the post is published externally.",
            active="Whether the post is currently active.",
            live="Whether the post is currently live.",
            content="Body content of the job post.",
        ),
    },
    "offers": {
        "description": "An offer extended to a candidate for a job in Greenhouse.",
        "docs_url": "https://developers.greenhouse.io/harvest.html#the-offer-object",
        "columns": _columns(
            application_id="ID of the application the offer is tied to.",
            job_id="ID of the job the offer is for.",
            candidate_id="ID of the candidate receiving the offer.",
            version="Version number of the offer.",
            status="Status of the offer (e.g. draft, approved, sent, accepted).",
            sent_at="Time at which the offer was sent.",
            resolved_at="Time at which the offer was resolved.",
            starts_at="Proposed start date in the offer.",
        ),
    },
    "scorecards": {
        "description": "An interviewer's evaluation of a candidate for an interview.",
        "docs_url": "https://developers.greenhouse.io/harvest.html#the-scorecard-object",
        "columns": _columns(
            application_id="ID of the application being evaluated.",
            candidate_id="ID of the candidate being evaluated.",
            interview="Name of the interview the scorecard is for.",
            interview_step="The interview step the scorecard belongs to.",
            interviewer="The interviewer who submitted the scorecard.",
            submitted_by="The user who submitted the scorecard.",
            submitted_at="Time at which the scorecard was submitted.",
            overall_recommendation="The interviewer's overall recommendation (e.g. yes, no, strong yes).",
            attributes="Per-attribute ratings on the scorecard.",
        ),
    },
    "scheduled_interviews": {
        "description": "A scheduled interview event for a candidate's application.",
        "docs_url": "https://developers.greenhouse.io/harvest.html#the-scheduled-interview-object",
        "columns": _columns(
            application_id="ID of the application the interview is for.",
            interview="Name of the interview.",
            organizer="The user who organized the interview.",
            interviewers="The users conducting the interview.",
            status="Status of the scheduled interview.",
            location="Location of the interview.",
            start="Scheduled start time of the interview.",
            end="Scheduled end time of the interview.",
        ),
    },
    "users": {
        "description": "A Greenhouse user account (recruiter, hiring manager, or admin).",
        "docs_url": "https://developers.greenhouse.io/harvest.html#the-user-object",
        "columns": _columns(
            name="Full name of the user.",
            first_name="First name of the user.",
            last_name="Last name of the user.",
            primary_email_address="Primary email address of the user.",
            emails="Email addresses associated with the user.",
            employee_id="External employee ID of the user.",
            disabled="Whether the user account is disabled.",
            site_admin="Whether the user is a site admin.",
        ),
    },
    "departments": {
        "description": "A department that jobs can be assigned to in Greenhouse.",
        "docs_url": "https://developers.greenhouse.io/harvest.html#the-department-object",
        "columns": {
            "id": "Unique identifier for the department.",
            "name": "Name of the department.",
            "parent_id": "ID of the parent department, if nested.",
            "child_ids": "IDs of child departments.",
            "external_id": "External identifier for the department.",
        },
    },
    "offices": {
        "description": "An office location that jobs can be assigned to in Greenhouse.",
        "docs_url": "https://developers.greenhouse.io/harvest.html#the-office-object",
        "columns": {
            "id": "Unique identifier for the office.",
            "name": "Name of the office.",
            "location": "Location details of the office.",
            "parent_id": "ID of the parent office, if nested.",
            "child_ids": "IDs of child offices.",
            "external_id": "External identifier for the office.",
        },
    },
    "sources": {
        "description": "A source that candidates can be attributed to (e.g. a job board or referral).",
        "docs_url": "https://developers.greenhouse.io/harvest.html#the-source-object",
        "columns": {
            "id": "Unique identifier for the source.",
            "name": "Name of the source.",
            "type": "Type of the source.",
        },
    },
    "rejection_reasons": {
        "description": "A configurable reason an application can be rejected for.",
        "docs_url": "https://developers.greenhouse.io/harvest.html#the-rejection-reason-object",
        "columns": {
            "id": "Unique identifier for the rejection reason.",
            "name": "Name of the rejection reason.",
            "type": "Category of the rejection reason.",
        },
    },
    "close_reasons": {
        "description": "A configurable reason a job opening can be closed for.",
        "docs_url": "https://developers.greenhouse.io/harvest.html#the-close-reason-object",
        "columns": {
            "id": "Unique identifier for the close reason.",
            "name": "Name of the close reason.",
        },
    },
}
