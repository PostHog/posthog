/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 8 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Generate AI individual summary for each session, without grouping.
 */
export const CreateSessionSummariesIndividuallyParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const createSessionSummariesIndividuallyBodySessionIdsMax = 300

export const createSessionSummariesIndividuallyBodyFocusAreaMax = 500

export const CreateSessionSummariesIndividuallyBody = /* @__PURE__ */ zod.object({
    session_ids: zod
        .array(zod.string())
        .min(1)
        .max(createSessionSummariesIndividuallyBodySessionIdsMax)
        .describe('List of session IDs to summarize (max 300)'),
    focus_area: zod
        .string()
        .max(createSessionSummariesIndividuallyBodyFocusAreaMax)
        .optional()
        .describe('Optional focus area for the summarization'),
})

/**
 * Override list to include synthetic playlists
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
            zod.literal(null),
        ])
        .nullish()
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
 * Convenience action: subscribe a Slack channel to a daily/weekly AI-summarized digest of session summaries. Idempotently finds or creates the team's 'Session summary digest' insight and creates a subscription against it. The customer-supplied prompt_guide steers what the AI calls out in each delivery.
 * @summary Subscribe to session summary digest
 */
export const SubscriptionsSessionSummaryDigestCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const subscriptionsSessionSummaryDigestCreateBodySlackChannelIdMax = 255

export const subscriptionsSessionSummaryDigestCreateBodyFrequencyDefault = `daily`
export const subscriptionsSessionSummaryDigestCreateBodyPromptGuideMax = 500

export const SubscriptionsSessionSummaryDigestCreateBody = /* @__PURE__ */ zod
    .object({
        slack_integration_id: zod.number().describe("ID of the team's connected Slack integration."),
        slack_channel_id: zod
            .string()
            .max(subscriptionsSessionSummaryDigestCreateBodySlackChannelIdMax)
            .describe('Slack channel ID (or name) where the digest should be posted.'),
        frequency: zod
            .enum(['daily', 'weekly'])
            .describe('* `daily` - daily\n* `weekly` - weekly')
            .default(subscriptionsSessionSummaryDigestCreateBodyFrequencyDefault)
            .describe(
                "Delivery cadence — 'daily' (every morning) or 'weekly' (Mondays).\n\n* `daily` - daily\n* `weekly` - weekly"
            ),
        prompt_guide: zod
            .string()
            .max(subscriptionsSessionSummaryDigestCreateBodyPromptGuideMax)
            .describe(
                "Required. What counts as 'notable' for this team's product. The AI uses this to filter and frame each digest. Example: 'Highlight failed checkouts and any session where a paying customer hit friction on pricing.'"
            ),
        start_date: zod.iso.datetime({}).optional().describe('When to begin delivering. Defaults to the next 9am UTC.'),
    })
    .describe(
        "Inputs for the session summary digest convenience action.\n\n`prompt_guide` is required (not defaulted) — what counts as 'notable' is customer-specific\nand the prompt is the customer's lever for tuning the digest to their product."
    )
