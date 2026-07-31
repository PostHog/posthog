/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const SessionRecordingPlaylistTypeEnumApi = zod
    .enum(['collection', 'filters'])
    .describe('\* `collection` - Collection\n\* `filters` - Filters')

export type SessionRecordingPlaylistTypeEnumApi = zod.input<typeof SessionRecordingPlaylistTypeEnumApi>
export type SessionRecordingPlaylistTypeEnumApiOutput = zod.output<typeof SessionRecordingPlaylistTypeEnumApi>

export const sessionRecordingPlaylistApiNameMax = 400

export const sessionRecordingPlaylistApiDerivedNameMax = 400

export const SessionRecordingPlaylistApi = zod.object({
    id: zod.number(),
    short_id: zod.string(),
    name: zod
        .string()
        .max(sessionRecordingPlaylistApiNameMax)
        .nullish()
        .describe('Human-readable name for the playlist.'),
    derived_name: zod.string().max(sessionRecordingPlaylistApiDerivedNameMax).nullish(),
    description: zod.string().optional().describe("Optional description of the playlist's purpose or contents."),
    pinned: zod.boolean().optional().describe('Whether this playlist is pinned to the top of the list.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the playlist.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            "JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them."
        ),
    last_modified_at: zod.iso.datetime({ offset: true }),
    last_modified_by: UserBasicApi,
    recordings_counts: zod.record(
        zod.string(),
        zod.record(zod.string(), zod.union([zod.number(), zod.boolean(), zod.null()]))
    ),
    type: zod
        .union([SessionRecordingPlaylistTypeEnumApi, zod.null()])
        .optional()
        .describe(
            "Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.\n\n\* `collection` - Collection\n\* `filters` - Filters"
        ),
    is_synthetic: zod.boolean().describe('Return whether this is a synthetic playlist'),
    _create_in_folder: zod.string().optional(),
})

export type SessionRecordingPlaylistApi = zod.input<typeof SessionRecordingPlaylistApi>
export type SessionRecordingPlaylistApiOutput = zod.output<typeof SessionRecordingPlaylistApi>

export const PaginatedSessionRecordingPlaylistListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(SessionRecordingPlaylistApi),
})

export type PaginatedSessionRecordingPlaylistListApi = zod.input<typeof PaginatedSessionRecordingPlaylistListApi>
export type PaginatedSessionRecordingPlaylistListApiOutput = zod.output<typeof PaginatedSessionRecordingPlaylistListApi>

export const patchedSessionRecordingPlaylistApiNameMax = 400

export const patchedSessionRecordingPlaylistApiDerivedNameMax = 400

export const PatchedSessionRecordingPlaylistApi = zod.object({
    id: zod.number().optional(),
    short_id: zod.string().optional(),
    name: zod
        .string()
        .max(patchedSessionRecordingPlaylistApiNameMax)
        .nullish()
        .describe('Human-readable name for the playlist.'),
    derived_name: zod.string().max(patchedSessionRecordingPlaylistApiDerivedNameMax).nullish(),
    description: zod.string().optional().describe("Optional description of the playlist's purpose or contents."),
    pinned: zod.boolean().optional().describe('Whether this playlist is pinned to the top of the list.'),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: UserBasicApi.optional(),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the playlist.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            "JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them."
        ),
    last_modified_at: zod.iso.datetime({ offset: true }).optional(),
    last_modified_by: UserBasicApi.optional(),
    recordings_counts: zod
        .record(zod.string(), zod.record(zod.string(), zod.union([zod.number(), zod.boolean(), zod.null()])))
        .optional(),
    type: zod
        .union([SessionRecordingPlaylistTypeEnumApi, zod.null()])
        .optional()
        .describe(
            "Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.\n\n\* `collection` - Collection\n\* `filters` - Filters"
        ),
    is_synthetic: zod.boolean().optional().describe('Return whether this is a synthetic playlist'),
    _create_in_folder: zod.string().optional(),
})

export type PatchedSessionRecordingPlaylistApi = zod.input<typeof PatchedSessionRecordingPlaylistApi>
export type PatchedSessionRecordingPlaylistApiOutput = zod.output<typeof PatchedSessionRecordingPlaylistApi>

export const MinimalPersonApi = zod.object({
    id: zod.number().describe('Numeric person ID.'),
    name: zod.string().describe('Display name derived from person properties (email, name, or username).'),
    distinct_ids: zod.array(zod.string()),
    properties: zod
        .unknown()
        .optional()
        .describe('Key-value map of person properties set via $set and $set_once operations.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When this person was first seen (ISO 8601).'),
    uuid: zod.uuid().describe('Unique identifier (UUID) for this person.'),
    last_seen_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('Timestamp of the last event from this person, or null.'),
})

export type MinimalPersonApi = zod.input<typeof MinimalPersonApi>
export type MinimalPersonApiOutput = zod.output<typeof MinimalPersonApi>

export const outcomeApiDescriptionMax = 10000

export const OutcomeApi = zod
    .object({
        description: zod.string().min(1).max(outcomeApiDescriptionMax).nullish(),
        success: zod.boolean().nullish(),
    })
    .describe('Initial goal and session outcome coming from LLM.')

export type OutcomeApi = zod.input<typeof OutcomeApi>
export type OutcomeApiOutput = zod.output<typeof OutcomeApi>

export const SessionRecordingApi = zod.object({
    id: zod.string(),
    distinct_id: zod.string().nullable(),
    viewed: zod.boolean(),
    viewers: zod.array(zod.string()),
    recording_duration: zod.number(),
    active_seconds: zod.number().nullable(),
    inactive_seconds: zod.number().nullable(),
    start_time: zod.iso.datetime({ offset: true }).nullable(),
    end_time: zod.iso.datetime({ offset: true }).nullable(),
    click_count: zod.number().nullable(),
    keypress_count: zod.number().nullable(),
    mouse_activity_count: zod.number().nullable(),
    console_log_count: zod.number().nullable(),
    console_warn_count: zod.number().nullable(),
    console_error_count: zod.number().nullable(),
    start_url: zod.string().nullable(),
    person: MinimalPersonApi.optional(),
    retention_period_days: zod.number().nullable(),
    expiry_time: zod.iso.datetime({ offset: true }).nullable(),
    recording_ttl: zod.number().nullable(),
    snapshot_source: zod.string().nullable(),
    snapshot_library: zod.string().nullable(),
    ongoing: zod.boolean(),
    activity_score: zod.number().nullable(),
    has_summary: zod.boolean(),
    summary_outcome: zod.union([OutcomeApi, zod.null()]),
    external_references: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe('Load external references (linked issues) for this recording'),
    matches_filters: zod
        .boolean()
        .describe(
            'Whether this recording matched the filters of the listing query that returned it. False only when a recording requested via session_recording_id was included despite not matching the filters.'
        ),
})

export type SessionRecordingApi = zod.input<typeof SessionRecordingApi>
export type SessionRecordingApiOutput = zod.output<typeof SessionRecordingApi>

export const PaginatedSessionRecordingListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(SessionRecordingApi),
})

export type PaginatedSessionRecordingListApi = zod.input<typeof PaginatedSessionRecordingListApi>
export type PaginatedSessionRecordingListApiOutput = zod.output<typeof PaginatedSessionRecordingListApi>

export const PatchedSessionRecordingApi = zod.object({
    id: zod.string().optional(),
    distinct_id: zod.string().nullish(),
    viewed: zod.boolean().optional(),
    viewers: zod.array(zod.string()).optional(),
    recording_duration: zod.number().optional(),
    active_seconds: zod.number().nullish(),
    inactive_seconds: zod.number().nullish(),
    start_time: zod.iso.datetime({ offset: true }).nullish(),
    end_time: zod.iso.datetime({ offset: true }).nullish(),
    click_count: zod.number().nullish(),
    keypress_count: zod.number().nullish(),
    mouse_activity_count: zod.number().nullish(),
    console_log_count: zod.number().nullish(),
    console_warn_count: zod.number().nullish(),
    console_error_count: zod.number().nullish(),
    start_url: zod.string().nullish(),
    person: MinimalPersonApi.optional(),
    retention_period_days: zod.number().nullish(),
    expiry_time: zod.iso.datetime({ offset: true }).nullish(),
    recording_ttl: zod.number().nullish(),
    snapshot_source: zod.string().nullish(),
    snapshot_library: zod.string().nullish(),
    ongoing: zod.boolean().optional(),
    activity_score: zod.number().nullish(),
    has_summary: zod.boolean().optional(),
    summary_outcome: zod.union([OutcomeApi, zod.null()]).optional(),
    external_references: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .optional()
        .describe('Load external references (linked issues) for this recording'),
    matches_filters: zod
        .boolean()
        .optional()
        .describe(
            'Whether this recording matched the filters of the listing query that returned it. False only when a recording requested via session_recording_id was included despite not matching the filters.'
        ),
})

export type PatchedSessionRecordingApi = zod.input<typeof PatchedSessionRecordingApi>
export type PatchedSessionRecordingApiOutput = zod.output<typeof PatchedSessionRecordingApi>

export const sessionRecordingBulkDeleteRequestApiSessionRecordingIdsMax = 100

export const SessionRecordingBulkDeleteRequestApi = zod.object({
    session_recording_ids: zod
        .array(zod.string())
        .min(1)
        .max(sessionRecordingBulkDeleteRequestApiSessionRecordingIdsMax)
        .describe('Session IDs of the recordings to delete (max 100 per call).'),
    date_from: zod
        .string()
        .nullish()
        .describe(
            "Earliest start time of the recordings, as an ISO date or a relative offset like '-30d'. Providing this narrows the lookup and speeds up the request; defaults to the project's recording retention period."
        ),
})

export type SessionRecordingBulkDeleteRequestApi = zod.input<typeof SessionRecordingBulkDeleteRequestApi>
export type SessionRecordingBulkDeleteRequestApiOutput = zod.output<typeof SessionRecordingBulkDeleteRequestApi>

export const SessionRecordingBulkDeleteResponseApi = zod.object({
    success: zod
        .boolean()
        .describe(
            'True when no deletion attempt failed. IDs that were not found, or that the caller lacks edit access to, are skipped rather than failed — compare deleted_count to total_requested to detect skips.'
        ),
    deleted_count: zod.number().describe('Number of recordings that were deleted.'),
    total_requested: zod.number().describe('Number of session recording IDs in the request.'),
    failed_ids: zod
        .array(zod.string())
        .describe('Session IDs that were found but could not be deleted. These can be retried.'),
})

export type SessionRecordingBulkDeleteResponseApi = zod.input<typeof SessionRecordingBulkDeleteResponseApi>
export type SessionRecordingBulkDeleteResponseApiOutput = zod.output<typeof SessionRecordingBulkDeleteResponseApi>

export const sessionSummariesApiSessionIdsMax = 300

export const sessionSummariesApiFocusAreaMax = 500

export const SessionSummariesApi = zod.object({
    session_ids: zod
        .array(zod.string())
        .min(1)
        .max(sessionSummariesApiSessionIdsMax)
        .describe('List of session IDs to summarize (max 300)'),
    focus_area: zod
        .string()
        .max(sessionSummariesApiFocusAreaMax)
        .optional()
        .describe('Optional focus area for the summarization'),
})

export type SessionSummariesApi = zod.input<typeof SessionSummariesApi>
export type SessionSummariesApiOutput = zod.output<typeof SessionSummariesApi>

export const SingleSessionSummaryMinimalApi = zod
    .object({
        id: zod.uuid(),
        session_id: zod.string().describe('Session replay ID'),
        distinct_id: zod.string().nullable().describe("Distinct ID of the session's user"),
        session_start_time: zod.iso.datetime({ offset: true }).nullable().describe('Session start time'),
        session_duration: zod.number().nullable().describe('Session duration in seconds'),
        session_outcome: zod
            .object({
                success: zod.boolean().optional(),
                description: zod.string().optional(),
            })
            .nullable()
            .describe(
                'Headline outcome from the summary: `{success: bool, description: string}` or null if the summary did not record one. Useful for quickly classifying a session as success\/failure.'
            ),
        exception_count: zod
            .number()
            .describe('Number of exception event IDs surfaced by this summary (capped at 100).'),
        has_exceptions: zod.boolean().describe('True if the summary surfaced any exception events.'),
        model_used: zod
            .string()
            .nullable()
            .describe('LLM model identifier that generated this summary, if recorded in run metadata.'),
        visual_confirmation: zod
            .boolean()
            .describe(
                'True if the summary was produced with video-based visual confirmation (the rasterized-recording path).'
            ),
        extra_summary_context: zod
            .object({
                focus_area: zod.string().optional(),
            })
            .nullable()
            .describe('Optional context passed to the summary at generation time (e.g. `focus_area`).'),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: zod.union([UserBasicApi, zod.null()]),
    })
    .describe('Lightweight projection for list endpoints — omits the full `summary` JSON (~50 KB per row).')

export type SingleSessionSummaryMinimalApi = zod.input<typeof SingleSessionSummaryMinimalApi>
export type SingleSessionSummaryMinimalApiOutput = zod.output<typeof SingleSessionSummaryMinimalApi>

export const PaginatedSingleSessionSummaryMinimalListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(SingleSessionSummaryMinimalApi),
})

export type PaginatedSingleSessionSummaryMinimalListApi = zod.input<typeof PaginatedSingleSessionSummaryMinimalListApi>
export type PaginatedSingleSessionSummaryMinimalListApiOutput = zod.output<
    typeof PaginatedSingleSessionSummaryMinimalListApi
>

export const SingleSessionSummaryApi = zod
    .object({
        id: zod.uuid(),
        session_id: zod.string().describe('Session replay ID'),
        distinct_id: zod.string().nullable().describe("Distinct ID of the session's user"),
        session_start_time: zod.iso.datetime({ offset: true }).nullable().describe('Session start time'),
        session_duration: zod.number().nullable().describe('Session duration in seconds'),
        summary: zod
            .record(zod.string(), zod.unknown())
            .describe(
                'Full LLM-generated summary JSON. Contains `segments` (chronological journey segments), `key_actions` (per-segment events with `abandonment` \/ `confusion` \/ `exception` flags — the structured source of session-level problems), `segment_outcomes`, and `session_outcome`. Video-based runs additionally include a `sentiment` block.'
            ),
        exception_event_ids: zod
            .array(zod.string())
            .describe(
                'Event IDs (capped at 100) where exceptions occurred during the session — extracted from the summary for searchability.'
            ),
        extra_summary_context: zod
            .object({
                focus_area: zod.string().optional(),
            })
            .nullable()
            .describe('Optional context passed to the summary at generation time (e.g. `focus_area`).'),
        run_metadata: zod
            .looseObject({})
            .nullable()
            .describe(
                '`SessionSummaryRunMeta` — model used, whether video-based visual confirmation was applied, and visual-confirmation event-to-asset mappings.'
            ),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: zod.union([UserBasicApi, zod.null()]),
    })
    .describe('Full session summary, including the generated `summary` JSON content.')

export type SingleSessionSummaryApi = zod.input<typeof SingleSessionSummaryApi>
export type SingleSessionSummaryApiOutput = zod.output<typeof SingleSessionSummaryApi>
