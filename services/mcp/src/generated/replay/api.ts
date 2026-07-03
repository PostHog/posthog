/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 9 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Override list to include synthetic playlists.
 *
 * Synthetics have no DB row, so we compute each one's position in the merged
 * sort and split the requested page between synthetics and a DB queryset slice.
 * The merge/rank/sort is all in-memory, so each phase is wrapped in a span and
 * the input sizes are recorded as span attributes — a slow response on a team
 * with many playlists then shows up as a wide span against a large db_count.
 */
export const SessionRecordingPlaylistsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SessionRecordingPlaylistsListQueryParams = /* @__PURE__ */ zod.object({
    created_by: zod.number().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    short_id: zod.string().optional(),
})

export const SessionRecordingPlaylistsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const sessionRecordingPlaylistsCreateBodyNameMax = 400

export const sessionRecordingPlaylistsCreateBodyDerivedNameMax = 400

export const SessionRecordingPlaylistsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(sessionRecordingPlaylistsCreateBodyNameMax)
        .nullish()
        .describe('Human-readable name for the playlist.'),
    derived_name: zod.string().max(sessionRecordingPlaylistsCreateBodyDerivedNameMax).nullish(),
    description: zod.string().optional().describe("Optional description of the playlist's purpose or contents."),
    pinned: zod.boolean().optional().describe('Whether this playlist is pinned to the top of the list.'),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the playlist.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            "JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them."
        ),
    type: zod
        .union([
            zod.enum(['collection', 'filters']).describe('* `collection` - Collection\n* `filters` - Filters'),
            zod.null(),
        ])
        .optional()
        .describe(
            "Playlist type: 'collection' for manually curated recordings, 'filters' for saved filter views. Required on create, cannot be changed after.\n\n* `collection` - Collection\n* `filters` - Filters"
        ),
})

export const SessionRecordingPlaylistsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    short_id: zod.string(),
})

export const SessionRecordingPlaylistsPartialUpdateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    short_id: zod.string(),
})

export const sessionRecordingPlaylistsPartialUpdateBodyNameMax = 400

export const sessionRecordingPlaylistsPartialUpdateBodyDerivedNameMax = 400

export const SessionRecordingPlaylistsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(sessionRecordingPlaylistsPartialUpdateBodyNameMax)
        .nullish()
        .describe('Human-readable name for the playlist.'),
    derived_name: zod.string().max(sessionRecordingPlaylistsPartialUpdateBodyDerivedNameMax).nullish(),
    description: zod.string().optional().describe("Optional description of the playlist's purpose or contents."),
    pinned: zod.boolean().optional().describe('Whether this playlist is pinned to the top of the list.'),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the playlist.'),
    filters: zod
        .unknown()
        .optional()
        .describe(
            "JSON object with recording filter criteria. Only used when type is 'filters'. Defines which recordings match this saved filter view. When updating a filters-type playlist, you must include the existing filters alongside any other changes — omitting filters will be treated as removing them."
        ),
})

export const SessionRecordingsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this session recording.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SessionRecordingsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this session recording.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Delete a batch of session recordings by session ID. Deletion is permanent and cannot be undone. IDs that don't match an existing recording are skipped and counted in `total_requested` but not `deleted_count`.
 */
export const SessionRecordingsBulkDeleteCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const sessionRecordingsBulkDeleteCreateBodySessionRecordingIdsMax = 100

export const SessionRecordingsBulkDeleteCreateBody = /* @__PURE__ */ zod.object({
    session_recording_ids: zod
        .array(zod.string())
        .min(1)
        .max(sessionRecordingsBulkDeleteCreateBodySessionRecordingIdsMax)
        .describe('Session IDs of the recordings to delete (max 100 per call).'),
    date_from: zod
        .string()
        .nullish()
        .describe(
            "Earliest start time of the recordings, as an ISO date or a relative offset like '-30d'. Providing this narrows the lookup and speeds up the request; defaults to the project's recording retention period."
        ),
})

/**
 * List stored AI-generated session summaries for the team, one row per session (latest summary kept). Use to discover which sessions have been summarized and to filter for sessions with specific problems — `has_exceptions=true`, `outcome=failure`, or a custom `session_ids` narrowing. Returns lightweight rows without the full summary JSON; use the retrieve endpoint for the per-segment / per-action detail.
 */
export const SingleSessionSummariesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SingleSessionSummariesListQueryParams = /* @__PURE__ */ zod.object({
    created_by: zod
        .string()
        .optional()
        .describe('Filter to summaries triggered by a specific user, identified by `User.uuid`.'),
    date_from: zod
        .string()
        .optional()
        .describe('Inclusive lower bound on `created_at`, accepts relative shorthand like `-7d`.'),
    date_to: zod
        .string()
        .optional()
        .describe('Inclusive upper bound on `created_at`, accepts relative shorthand like `-1d`.'),
    distinct_id: zod
        .string()
        .optional()
        .describe("Filter to summaries for a single user (the session's `distinct_id`)."),
    has_exceptions: zod
        .boolean()
        .optional()
        .describe(
            'When true, only summaries that surfaced one or more exception events; when false, only summaries without exceptions.'
        ),
    has_visual_confirmation: zod
        .boolean()
        .optional()
        .describe('When true, only summaries produced via the video-based visual-confirmation workflow.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order: zod
        .string()
        .optional()
        .describe(
            'Ordering field, defaults to `-created_at` (most recent first). Allowed: `created_at`, `session_start_time`, `session_duration` (prefix with `-` for descending).'
        ),
    outcome: zod
        .enum(['failure', 'success', 'unknown'])
        .optional()
        .describe(
            "Filter by the summary's recorded `session_outcome.success` field. `success` for true, `failure` for false, `unknown` for summaries without an outcome."
        ),
    session_ids: zod
        .string()
        .optional()
        .describe(
            'Comma-separated list of session IDs to restrict the result to (uses the `(team, session_id)` index).'
        ),
})

/**
 * Get the latest stored AI summary for a single session by `session_id`. Returns the full `summary` JSON (segments with named timeline, per-action `abandonment` / `confusion` / `exception` flags, segment outcomes, headline `session_outcome`, optional `sentiment`), the `exception_event_ids` array, the `extra_summary_context` (e.g. `focus_area`) used at generation time, and the `run_metadata` (LLM model used, whether visual confirmation was applied). 404 if no summary has been generated for this session yet — to trigger generation, use the existing `session-recording-summarize` flow rather than this endpoint.
 */
export const singleSessionSummariesRetrievePathSessionIdRegExp = new RegExp('^[^/]+$')

export const SingleSessionSummariesRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    session_id: zod.string().regex(singleSessionSummariesRetrievePathSessionIdRegExp),
})
