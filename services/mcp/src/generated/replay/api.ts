/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List and search session recordings. Filter by session IDs, person UUID, distinct IDs, date range, person/session/event properties, console log levels, and more. Returns recording metadata including duration, activity counts, start URL, and person info.
 */
export const SessionRecordingsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SessionRecordingsListQueryParams = /* @__PURE__ */ zod.object({
    actions: zod
        .string()
        .min(1)
        .optional()
        .describe('JSON array of action filters. Similar to events but references saved actions by ID.'),
    console_log_filters: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'JSON array of console log entry filters. Example: \'[{"key":"level","type":"log_entry","value":["error"],"operator":"exact"}]\''
        ),
    date_from: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Start date for the search range. Relative: '-3d', '-7d', '-24h'. Absolute: '2024-01-01'. Defaults to '-3d'."
        ),
    date_to: zod
        .string()
        .min(1)
        .optional()
        .describe("End date for the search range. Null means 'now'. Absolute: '2024-01-15'."),
    distinct_ids: zod
        .string()
        .min(1)
        .optional()
        .describe('JSON array of distinct IDs. Example: \'["user@example.com"]\''),
    events: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'JSON array of event filters. Matches recordings containing at least one matching event. Example: \'[{"id":"$pageview","type":"events","properties":[{"key":"$current_url","type":"event","value":"/pricing","operator":"icontains"}]}]\''
        ),
    filter_test_accounts: zod.boolean().optional().describe('Exclude internal/test users. Defaults to false.'),
    limit: zod.number().optional().describe('Maximum number of recordings to return per page.'),
    offset: zod.number().optional().describe('Number of recordings to skip for pagination.'),
    operand: zod
        .enum(['AND', 'OR'])
        .optional()
        .describe("Logical operator to combine property filters. Defaults to 'AND'.\n\n* `AND` - AND\n* `OR` - OR"),
    order: zod
        .enum([
            'start_time',
            'duration',
            'recording_duration',
            'console_error_count',
            'active_seconds',
            'inactive_seconds',
            'click_count',
            'keypress_count',
            'mouse_activity_count',
            'activity_score',
            'recording_ttl',
        ])
        .optional()
        .describe(
            "Field to order recordings by. Defaults to 'start_time'.\n\n* `start_time` - start_time\n* `duration` - duration\n* `recording_duration` - recording_duration\n* `console_error_count` - console_error_count\n* `active_seconds` - active_seconds\n* `inactive_seconds` - inactive_seconds\n* `click_count` - click_count\n* `keypress_count` - keypress_count\n* `mouse_activity_count` - mouse_activity_count\n* `activity_score` - activity_score\n* `recording_ttl` - recording_ttl"
        ),
    order_direction: zod
        .enum(['ASC', 'DESC'])
        .optional()
        .describe("Sort direction. Defaults to 'DESC'.\n\n* `ASC` - ASC\n* `DESC` - DESC"),
    person_uuid: zod.string().min(1).optional().describe('Filter recordings by a specific person UUID.'),
    properties: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'JSON array of property filters for person, session, event, recording, or cohort properties. Example: \'[{"key":"$browser","type":"person","value":["Chrome"],"operator":"exact"}]\'. Supported types: person, session, event, recording, cohort, group, hogql.'
        ),
    session_ids: zod
        .string()
        .min(1)
        .optional()
        .describe('JSON array of session IDs to filter by. Example: \'["session-abc","session-def"]\''),
})

export const SessionRecordingsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this session recording.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
