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
 * Update the team's session summaries configuration (product context used to tailor single-session replay summaries).
 */
export const updateSessionSummariesConfigBodyProductContextMax = 10000

export const UpdateSessionSummariesConfigBody = /* @__PURE__ */ zod.object({
    product_context: zod
        .string()
        .max(updateSessionSummariesConfigBodyProductContextMax)
        .optional()
        .describe(
            "Free-form description of the team's product, used to tailor AI-generated single-session replay summaries. Injected into the system prompt of every summary generated for this team via the replay page."
        ),
})

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
