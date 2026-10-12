from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from the Workable SPI v3 docs (https://workable.readme.io/reference). Columns not
# covered here fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "jobs": {
        "description": "Jobs (open positions) in your Workable account.",
        "docs_url": "https://workable.readme.io/reference/jobs",
        "columns": {
            "id": "Unique identifier for the job.",
            "title": "Job title.",
            "full_title": "Job title including the job code suffix.",
            "shortcode": "System-generated short code for the job, used in public job URLs.",
            "code": "Job code as set by the account.",
            "state": "Current state of the job (draft, published, archived, closed).",
            "department": "Department the job belongs to.",
            "url": "URL of the job in Workable.",
            "application_url": "URL where candidates apply to the job.",
            "shortlink": "Public short link to the job posting.",
            "location": "Location details for the job.",
            "created_at": "Timestamp the job was created.",
            "updated_at": "Timestamp the job was last updated.",
        },
    },
    "candidates": {
        "description": "Candidates (applicants) across the account's jobs.",
        "docs_url": "https://workable.readme.io/reference/job-candidates-index",
        "columns": {
            "id": "Unique identifier for the candidate.",
            "name": "Candidate's full name.",
            "firstname": "Candidate's first name.",
            "lastname": "Candidate's last name.",
            "headline": "Candidate's professional headline.",
            "job": "The job the candidate applied to (shortcode and title).",
            "stage": "Current pipeline stage of the candidate.",
            "disqualified": "Whether the candidate has been disqualified.",
            "disqualification_reason": "Reason the candidate was disqualified, if any.",
            "sourced": "Whether the candidate was sourced rather than having applied.",
            "profile_url": "URL of the candidate's profile in Workable.",
            "email": "Candidate's email address.",
            "domain": "Source domain the candidate came from.",
            "created_at": "Timestamp the candidate was created.",
            "updated_at": "Timestamp the candidate was last updated.",
        },
    },
    "members": {
        "description": "Members (users) of your Workable account.",
        "docs_url": "https://workable.readme.io/reference/members",
        "columns": {
            "id": "Unique identifier for the member.",
            "name": "Member's full name.",
            "headline": "Member's headline.",
            "email": "Member's email address.",
            "role": "Member's recruiting role.",
            "active": "Whether the member is active.",
        },
    },
    "recruiters": {
        "description": "External recruiters associated with your Workable account.",
        "docs_url": "https://workable.readme.io/reference/recruiters",
        "columns": {
            "id": "Unique identifier for the recruiter.",
            "name": "Recruiter's full name.",
            "email": "Recruiter's email address.",
        },
    },
    "stages": {
        "description": "Stages of your account's recruitment pipeline.",
        "docs_url": "https://workable.readme.io/reference/stages",
        "columns": {
            "slug": "Unique token identifying the stage.",
            "name": "Stage name.",
            "kind": "Stage type (e.g. sourced, applied, interview, offer, hired).",
            "position": "Zero-based position of the stage in the pipeline.",
        },
    },
}
