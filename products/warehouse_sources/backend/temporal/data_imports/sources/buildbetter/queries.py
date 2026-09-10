# Nested relation that some BuildBetter accounts' schema (role-dependent) does not expose. Kept
# separate so it can be dropped from the query when the API reports the field is unknown.
INTERVIEW_MONOLOGUES_FIELD = """
        monologues(order_by: {start_sec: asc}) {
            id
            speaker
            text
            start_sec
            end_sec
        }"""

INTERVIEWS_QUERY = (
    """
query PaginatedInterviews($limit: Int!, $offset: Int!, $where: interview_bool_exp) {
    interview(limit: $limit, offset: $offset, order_by: {updated_at: asc}, where: $where) {
        id
        external_id
        name
        original_name
        short_summary
        summary
        transcript_summary
        source
        interaction
        permission
        asset_url
        asset_duration_seconds
        asset_is_audio
        meeting_url
        started_at
        completed_at
        recorded_at
        created_at
        updated_at
        deleted_at
        display_ts
        transcript_status
        summary_state
        attendees {
            id
            speaker
            person {
                id
                first_name
                last_name
                email
                title
                avatar_url
            }
        }
        tags {
            tag {
                id
                name
                color
            }
        }
        summaries {
            title
            content
            created_at
        }"""
    + INTERVIEW_MONOLOGUES_FIELD
    + """
    }
}"""
)

EXTRACTIONS_QUERY = """
query PaginatedExtractions($limit: Int!, $offset: Int!, $where: extraction_bool_exp) {
    extraction(limit: $limit, offset: $offset, order_by: {created_at: asc}, where: $where) {
        id
        interview_id
        summary
        context
        sentiment
        severity
        bias
        start_sec
        end_sec
        created_at
        display_ts
        speaker
        attendee {
            id
            person {
                id
                first_name
                last_name
                email
            }
        }
        call {
            id
            name
            external_id
        }
        types {
            type {
                id
                name
            }
        }
        topics {
            topic {
                id
                text
            }
        }
        keywords {
            keyword {
                id
                text
            }
        }
        emotions {
            emotion {
                id
                name
            }
        }
        impacts {
            impact {
                id
                name
            }
        }
        exact_quote {
            id
            text
        }
    }
}"""

PERSONS_QUERY = """
query PaginatedPersons($limit: Int!, $offset: Int!, $where: person_bool_exp) {
    person(limit: $limit, offset: $offset, order_by: {updated_at: asc}, where: $where) {
        id
        external_id
        first_name
        last_name
        email
        title
        department
        avatar_url
        source
        source_identifier
        company_id
        company {
            id
            name
            domain
        }
        persona_id
        persona {
            id
            name
        }
        created_at
        updated_at
    }
}"""

COMPANIES_QUERY = """
query PaginatedCompanies($limit: Int!, $offset: Int!, $where: company_bool_exp) {
    company(limit: $limit, offset: $offset, order_by: {updated_at: asc}, where: $where) {
        id
        name
        domain
        photo_url
        created_at
        updated_at
    }
}"""

VIEWER_QUERY = "{ interview(limit: 1) { id } }"

QUERIES: dict[str, str] = {
    "interviews": INTERVIEWS_QUERY,
    "extractions": EXTRACTIONS_QUERY,
    "persons": PERSONS_QUERY,
    "companies": COMPANIES_QUERY,
}

# endpoint -> {field name -> exact query block to drop when the account's schema lacks the field}
OPTIONAL_QUERY_FIELDS: dict[str, dict[str, str]] = {
    "interviews": {"monologues": INTERVIEW_MONOLOGUES_FIELD},
}
