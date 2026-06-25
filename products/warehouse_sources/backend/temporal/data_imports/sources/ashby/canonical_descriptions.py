"""Canonical, documentation-sourced descriptions for Ashby endpoints and columns.

Sourced from the official Ashby API reference (https://developers.ashbyhq.com). Keyed by the
table names in `settings.py` `ASHBY_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Ashby table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Ashby objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "createdAt": "Time at which the object was created.",
    "updatedAt": "Time at which the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "candidates": {
        "description": "A person who has applied to or been sourced for a role in Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/candidatelist",
        "columns": _columns(
            name="The candidate's full name.",
            primaryEmailAddress="The candidate's primary email address.",
            emailAddresses="All email addresses associated with the candidate.",
            phoneNumbers="Phone numbers associated with the candidate.",
            socialLinks="Social and professional profile links for the candidate.",
            tags="Tags applied to the candidate.",
            position="The candidate's current job title.",
            company="The candidate's current company.",
            applicationIds="IDs of the applications associated with the candidate.",
            source="The source through which the candidate was added.",
        ),
    },
    "applications": {
        "description": "A candidate's application to a specific job in Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/applicationlist",
        "columns": _columns(
            candidateId="ID of the candidate who applied.",
            jobId="ID of the job applied to.",
            status="Status of the application (Active, Hired, Archived, Lead).",
            currentInterviewStage="The interview stage the application is currently in.",
            source="The source through which the application originated.",
            archiveReason="Reason the application was archived, if applicable.",
            creditedToUser="The user credited with the application.",
        ),
    },
    "jobs": {
        "description": "A job (requisition) being recruited for in Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/joblist",
        "columns": _columns(
            title="The job's title.",
            status="Status of the job (Draft, Open, Closed, Archived).",
            employmentType="Employment type for the job (FullTime, PartTime, Intern, Contract, Temporary).",
            locationId="ID of the location the job is based in.",
            departmentId="ID of the department the job belongs to.",
            jobPostingIds="IDs of the job postings published for this job.",
        ),
    },
    "job_postings": {
        "description": "A published, externally visible posting for a job in Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/jobpostinglist",
        "columns": _columns(
            title="The job posting's title.",
            jobId="ID of the job this posting belongs to.",
            locationName="Name of the location shown on the posting.",
            departmentName="Name of the department shown on the posting.",
            employmentType="Employment type shown on the posting.",
            isListed="Whether the posting is publicly listed.",
            externalLink="Public URL of the job posting.",
        ),
    },
    "offers": {
        "description": "An offer extended to a candidate for a job in Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/offerlist",
        "columns": _columns(
            applicationId="ID of the application the offer is associated with.",
            offerStatus="Status of the offer (e.g. Draft, WaitingOnApprovals, Approved, Accepted, Declined).",
            latestVersion="The most recent version of the offer's details.",
        ),
    },
    "interviews": {
        "description": "An interview type or definition configured in Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/interviewlist",
        "columns": _columns(
            title="Title of the interview.",
            isArchived="Whether the interview is archived.",
            isDebrief="Whether the interview is a debrief session.",
        ),
    },
    "interview_schedules": {
        "description": "A scheduled set of interviews for a candidate's application in Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/interviewschedulelist",
        "columns": _columns(
            applicationId="ID of the application the schedule is for.",
            interviewStageId="ID of the interview stage the schedule is associated with.",
            status="Status of the interview schedule.",
            interviewEvents="The individual interview events that make up the schedule.",
        ),
    },
    "users": {
        "description": "A user (recruiter, hiring manager, or admin) in the Ashby workspace.",
        "docs_url": "https://developers.ashbyhq.com/reference/userlist",
        "columns": _columns(
            firstName="The user's first name.",
            lastName="The user's last name.",
            email="The user's email address.",
            globalRole="The user's global role in the workspace.",
            isEnabled="Whether the user account is enabled.",
        ),
    },
    "departments": {
        "description": "A department that jobs and teams are organized under in Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/departmentlist",
        "columns": _columns(
            name="Name of the department.",
            isArchived="Whether the department is archived.",
            parentId="ID of the parent department, if nested.",
        ),
    },
    "locations": {
        "description": "A location that jobs can be based in within Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/locationlist",
        "columns": _columns(
            name="Name of the location.",
            isArchived="Whether the location is archived.",
            isRemote="Whether the location is remote.",
            address="Address details of the location.",
        ),
    },
    "sources": {
        "description": "A source channel through which candidates are added in Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/sourcelist",
        "columns": _columns(
            title="Title of the source.",
            isArchived="Whether the source is archived.",
            sourceType="The category of the source.",
        ),
    },
    "archive_reasons": {
        "description": "A reason an application can be archived in Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/archivereasonlist",
        "columns": _columns(
            text="The text of the archive reason.",
            isArchived="Whether the archive reason itself is archived.",
            reasonType="The category of the archive reason.",
        ),
    },
    "candidate_tags": {
        "description": "A tag that can be applied to candidates in Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/candidatetaglist",
        "columns": _columns(
            title="The text of the candidate tag.",
            isArchived="Whether the tag is archived.",
        ),
    },
    "custom_fields": {
        "description": "A custom field definition used to capture additional data on Ashby objects.",
        "docs_url": "https://developers.ashbyhq.com/reference/customfieldlist",
        "columns": _columns(
            title="Title of the custom field.",
            objectType="The type of object the custom field applies to.",
            fieldType="The data type of the custom field.",
            isArchived="Whether the custom field is archived.",
            isExposable="Whether the field's value can be exposed externally.",
        ),
    },
    "openings": {
        "description": "An opening (headcount slot) tied to one or more jobs in Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/openinglist",
        "columns": _columns(
            identifier="Human-readable identifier for the opening.",
            jobIds="IDs of the jobs associated with the opening.",
            openingState="State of the opening (e.g. Draft, Approved, Open, Closed).",
            isArchived="Whether the opening is archived.",
        ),
    },
    "projects": {
        "description": "A project used to organize sourcing and recruiting work in Ashby.",
        "docs_url": "https://developers.ashbyhq.com/reference/projectlist",
        "columns": _columns(
            title="Title of the project.",
            isArchived="Whether the project is archived.",
            authorId="ID of the user who created the project.",
        ),
    },
}
