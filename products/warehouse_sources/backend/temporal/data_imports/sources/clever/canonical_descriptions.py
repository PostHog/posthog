"""Canonical, documentation-sourced descriptions for Clever endpoints and columns.

Sourced from the official Clever Data API v3 reference (https://dev.clever.com/docs). Keyed by
the resource names in `settings.py` `CLEVER_ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Clever table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_LINKS_COLUMN = "Related resource links Clever attaches to every object."

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Districts": {
        "description": "A school district that has authorized your Clever application.",
        "docs_url": "https://dev.clever.com/docs/districts",
        "columns": {
            "id": "Globally unique and stable id for the district, assigned by Clever.",
            "name": "District or CMO name.",
            "sis_type": "Student information system this district's data originates from.",
            "nces_id": "Federal NCES identifier for the district, when available.",
            "mdr_number": "MDR number used for external record matching, when available.",
            "launch_date": "Date the district launched with Clever (YYYY-MM-DD).",
            "portal_url": "URL of the district's Clever portal.",
            "state": "Current sync status of the district (running, pending, error, paused, success).",
            "last_sync": "Time of the district's most recent data sync, when available.",
            "links": _LINKS_COLUMN,
        },
    },
    "Schools": {
        "description": "A school within a district.",
        "docs_url": "https://dev.clever.com/docs/schools",
        "columns": {
            "id": "Globally unique and stable id for the school, assigned by Clever.",
            "district": "Id of the district the school belongs to.",
            "name": "School name.",
            "nces_id": "Federal NCES identifier for the school, when available.",
            "school_number": "School identifier assigned by the district or county, when available.",
            "high_grade": "Highest grade level served by the school, when available.",
            "low_grade": "Lowest grade level served by the school, when available.",
            "location": "Street address, city, state, and zip code of the school.",
            "created": "Time the school record was created in Clever.",
            "last_modified": "Time the school record was last modified in Clever.",
            "links": _LINKS_COLUMN,
        },
    },
    "Users": {
        "description": "A student, teacher, staff member, district admin, or contact in the district roster.",
        "docs_url": "https://dev.clever.com/docs/users",
        "columns": {
            "id": "Globally unique and stable id for the user, assigned by Clever.",
            "district": "Id of the user's district.",
            "name": "First, middle, and last name of the user.",
            "email": "Email address on file for the user, when available (not verified by Clever).",
            "roles": "Role-specific data for the user (student, teacher, staff, district_admin, contact).",
            "school": "Id of the user's primary school, for students and teachers.",
            "schools": "Ids of every school the user is associated with.",
            "sis_id": "Identifier for the user in the district's source system of record.",
            "created": "Time the user record was created in Clever.",
            "last_modified": "Time the user record was last modified in Clever.",
            "links": _LINKS_COLUMN,
        },
    },
    "Sections": {
        "description": "A class section: a group of students taught by a teacher for a course.",
        "docs_url": "https://dev.clever.com/docs/sections",
        "columns": {
            "id": "Globally unique and stable id for the section, assigned by Clever.",
            "district": "Id of the section's district.",
            "school": "Id of the section's school.",
            "name": "Section name, usually the course name, teacher's last name, and period.",
            "teacher": "Id of the section's primary teacher.",
            "students": "Ids of every student enrolled in the section.",
            "course": "Id of the course the section belongs to, when available.",
            "term_id": "Id of the term the section runs in, when available.",
            "subject": "Normalized subject of the section (e.g. math, science), when available.",
            "grade": "Grade level of the section, when available.",
            "period": "Bell schedule period the section meets in, when available.",
            "sis_id": "Identifier for the section in the district's source system of record.",
            "created": "Time the section record was created in Clever.",
            "last_modified": "Time the section record was last modified in Clever.",
            "links": _LINKS_COLUMN,
        },
    },
    "Courses": {
        "description": "A course offered by the district, made up of one or more sections.",
        "docs_url": "https://dev.clever.com/docs/courses",
        "columns": {
            "id": "Globally unique and stable id for the course, assigned by Clever.",
            "district": "Id of the course's district.",
            "name": "Course name provided by the district, when available.",
            "number": "Course number provided by the district, when available.",
            "links": _LINKS_COLUMN,
        },
    },
    "Terms": {
        "description": "An academic term (semester, quarter, or school year) defined by the district.",
        "docs_url": "https://dev.clever.com/docs/terms",
        "columns": {
            "id": "Globally unique and stable id for the term, assigned by Clever.",
            "district": "Id of the term's district.",
            "name": "Term name provided by the district, when available.",
            "start_date": "Start date of the term (YYYY-MM-DD), when available.",
            "end_date": "End date of the term (YYYY-MM-DD), when available.",
            "links": _LINKS_COLUMN,
        },
    },
    "Contacts": {
        "description": "A guardian or emergency contact, listed as a user with the `contact` role.",
        "docs_url": "https://dev.clever.com/docs/contacts-guardians",
        "columns": {
            "id": "Globally unique and stable id for the contact, assigned by Clever.",
            "district": "Id of the contact's district.",
            "name": "First, middle, and last name of the contact.",
            "email": "Email address on file for the contact, when available.",
            "phone": "Phone number on file for the contact, when available.",
            "phone_type": "Type of the contact's phone number (e.g. mobile, home), when available.",
            "student_relationships": "Students the contact is related to, with the relationship type.",
            "sis_id": "Identifier for the contact in the district's source system of record.",
            "created": "Time the contact record was created in Clever.",
            "last_modified": "Time the contact record was last modified in Clever.",
            "links": _LINKS_COLUMN,
        },
    },
    "Events": {
        "description": "A created, updated, or deleted change event for a record in the district, from Clever's delta feed. Retained for 30 days.",
        "docs_url": "https://dev.clever.com/docs/events-api",
        "columns": {
            "id": "Unique id of the event itself (distinct from the id of the affected record).",
            "type": "Event type, e.g. users.created, sections.updated, schools.deleted.",
            "created": "Time the event occurred.",
            "data": "The affected record's full object, plus `previous_attributes` for update events.",
            "uri": "Link to this event.",
        },
    },
}
