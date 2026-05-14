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
 * Planned user interview topics: who we want to target (cohort) and what we want to ask about.
 */
export const UserInterviewTopicsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const UserInterviewTopicsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('A search term.'),
})

/**
 * Planned user interview topics: who we want to target (cohort) and what we want to ask about.
 */
export const UserInterviewTopicsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const userInterviewTopicsCreateBodyIntervieweeEmailsItemMax = 254

export const userInterviewTopicsCreateBodyIntervieweeDistinctIdsItemMax = 400

export const UserInterviewTopicsCreateBody = /* @__PURE__ */ zod.object({
    interviewee_cohort: zod
        .number()
        .nullish()
        .describe('Optional cohort ID identifying who to target. Not enforced as a foreign key.'),
    interviewee_emails: zod
        .array(zod.string().max(userInterviewTopicsCreateBodyIntervieweeEmailsItemMax))
        .optional()
        .describe(
            'Email addresses of people to interview. May be combined with interviewee_cohort and interviewee_distinct_ids.'
        ),
    interviewee_distinct_ids: zod
        .array(zod.string().max(userInterviewTopicsCreateBodyIntervieweeDistinctIdsItemMax))
        .optional()
        .describe(
            'PostHog distinct IDs of people to interview. May be combined with interviewee_cohort and interviewee_emails.'
        ),
    topic: zod.string().describe('The product, feature, or idea you want to ask interviewees about.'),
    agent_context: zod
        .string()
        .optional()
        .describe('Optional additional system prompt for the voice agent — extra background, tone, or constraints.'),
    questions: zod
        .array(zod.string())
        .optional()
        .describe('Ordered list of questions the voice agent should work through during the interview.'),
})
