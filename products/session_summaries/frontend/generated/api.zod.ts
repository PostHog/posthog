/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Generate AI summary for a group of session recordings to find patterns and generate a notebook.
 */
export const createSessionSummariesBodySessionIdsMax = 300

export const createSessionSummariesBodyFocusAreaMax = 500

export const CreateSessionSummariesBody = /* @__PURE__ */ zod.object({
    session_ids: zod
        .array(zod.string())
        .min(1)
        .max(createSessionSummariesBodySessionIdsMax)
        .describe('List of session IDs to summarize (max 300)'),
    focus_area: zod
        .string()
        .max(createSessionSummariesBodyFocusAreaMax)
        .optional()
        .describe('Optional focus area for the summarization'),
})

/**
 * Generate AI individual summary for each session, without grouping.
 */
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
