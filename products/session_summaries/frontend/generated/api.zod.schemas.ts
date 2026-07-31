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

export const sessionSummariesConfigApiProductContextMax = 10000

export const SessionSummariesConfigApi = zod.object({
    product_context: zod
        .string()
        .max(sessionSummariesConfigApiProductContextMax)
        .optional()
        .describe(
            "Free-form description of the team's product, used to tailor AI-generated single-session replay summaries. Injected into the system prompt of every summary generated for this team via the replay page."
        ),
    custom_tags: zod
        .record(zod.string(), zod.string())
        .optional()
        .describe(
            'Team-defined tags layered on top of the fixed taxonomy, as a {name: description} map. Names must be lowercase snake_case (max 60 chars), descriptions max 200 chars, max 15 entries.'
        ),
})

export type SessionSummariesConfigApi = zod.input<typeof SessionSummariesConfigApi>
export type SessionSummariesConfigApiOutput = zod.output<typeof SessionSummariesConfigApi>

export const patchedSessionSummariesConfigApiProductContextMax = 10000

export const PatchedSessionSummariesConfigApi = zod.object({
    product_context: zod
        .string()
        .max(patchedSessionSummariesConfigApiProductContextMax)
        .optional()
        .describe(
            "Free-form description of the team's product, used to tailor AI-generated single-session replay summaries. Injected into the system prompt of every summary generated for this team via the replay page."
        ),
    custom_tags: zod
        .record(zod.string(), zod.string())
        .optional()
        .describe(
            'Team-defined tags layered on top of the fixed taxonomy, as a {name: description} map. Names must be lowercase snake_case (max 60 chars), descriptions max 200 chars, max 15 entries.'
        ),
})

export type PatchedSessionSummariesConfigApi = zod.input<typeof PatchedSessionSummariesConfigApi>
export type PatchedSessionSummariesConfigApiOutput = zod.output<typeof PatchedSessionSummariesConfigApi>

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
