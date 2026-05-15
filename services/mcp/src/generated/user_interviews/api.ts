/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 enabled ops
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

/**
 * Generate one public interview link per targeted interviewee. Materializes an IntervieweeContext row for every identifier on the topic (without overwriting existing per-person context), and an enabled SharingConfiguration with a unique access token. The URL resolves to the public interview viewer with no PostHog auth required.
 */
export const UserInterviewTopicsGenerateLinksCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this user interview topic.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Generate (if needed) and email a personalized public interview link to every targeted interviewee on this topic whose identifier is an email address. Distinct-ID-only interviewees are skipped and surfaced in the response. Each invite is keyed on the underlying SharingConfiguration so re-runs after token rotation produce a fresh send.
 */
export const UserInterviewTopicsSendInvitesCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this user interview topic.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const userInterviewTopicsSendInvitesCreateBodySubjectMax = 200

export const userInterviewTopicsSendInvitesCreateBodySendAsyncDefault = true

export const UserInterviewTopicsSendInvitesCreateBody = /* @__PURE__ */ zod.object({
    subject: zod
        .string()
        .max(userInterviewTopicsSendInvitesCreateBodySubjectMax)
        .optional()
        .describe('Override the default email subject line. Defaults to a friendly prompt referencing the topic.'),
    reply_to: zod
        .email()
        .optional()
        .describe("Email address replies should go to. Defaults to the topic creator's email if blank."),
    send_async: zod
        .boolean()
        .default(userInterviewTopicsSendInvitesCreateBodySendAsyncDefault)
        .describe(
            'If true (default), queue delivery via Celery. If false, send synchronously and surface errors immediately.'
        ),
})

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const UserInterviewTopicsIntervieweesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    topic_id: zod.string(),
})

export const UserInterviewTopicsIntervieweesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const UserInterviewTopicsIntervieweesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    topic_id: zod.string(),
})

export const userInterviewTopicsIntervieweesCreateBodyIntervieweeIdentifierMax = 400

export const userInterviewTopicsIntervieweesCreateBodyAgentContextMax = 10000

export const UserInterviewTopicsIntervieweesCreateBody = /* @__PURE__ */ zod.object({
    interviewee_identifier: zod
        .string()
        .max(userInterviewTopicsIntervieweesCreateBodyIntervieweeIdentifierMax)
        .describe(
            "Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids."
        ),
    agent_context: zod
        .string()
        .max(userInterviewTopicsIntervieweesCreateBodyAgentContextMax)
        .describe(
            "Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'."
        ),
})
