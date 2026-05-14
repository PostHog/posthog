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
 * Planned user interview topics: who we want to target (cohort) and what we want to ask about.
 */
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
 * Planned user interview topics: who we want to target (cohort) and what we want to ask about.
 */
export const userInterviewTopicsUpdateBodyIntervieweeEmailsItemMax = 254

export const userInterviewTopicsUpdateBodyIntervieweeDistinctIdsItemMax = 400

export const UserInterviewTopicsUpdateBody = /* @__PURE__ */ zod.object({
    interviewee_cohort: zod
        .number()
        .nullish()
        .describe('Optional cohort ID identifying who to target. Not enforced as a foreign key.'),
    interviewee_emails: zod
        .array(zod.string().max(userInterviewTopicsUpdateBodyIntervieweeEmailsItemMax))
        .optional()
        .describe(
            'Email addresses of people to interview. May be combined with interviewee_cohort and interviewee_distinct_ids.'
        ),
    interviewee_distinct_ids: zod
        .array(zod.string().max(userInterviewTopicsUpdateBodyIntervieweeDistinctIdsItemMax))
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
 * Planned user interview topics: who we want to target (cohort) and what we want to ask about.
 */
export const userInterviewTopicsPartialUpdateBodyIntervieweeEmailsItemMax = 254

export const userInterviewTopicsPartialUpdateBodyIntervieweeDistinctIdsItemMax = 400

export const UserInterviewTopicsPartialUpdateBody = /* @__PURE__ */ zod.object({
    interviewee_cohort: zod
        .number()
        .nullish()
        .describe('Optional cohort ID identifying who to target. Not enforced as a foreign key.'),
    interviewee_emails: zod
        .array(zod.string().max(userInterviewTopicsPartialUpdateBodyIntervieweeEmailsItemMax))
        .optional()
        .describe(
            'Email addresses of people to interview. May be combined with interviewee_cohort and interviewee_distinct_ids.'
        ),
    interviewee_distinct_ids: zod
        .array(zod.string().max(userInterviewTopicsPartialUpdateBodyIntervieweeDistinctIdsItemMax))
        .optional()
        .describe(
            'PostHog distinct IDs of people to interview. May be combined with interviewee_cohort and interviewee_emails.'
        ),
    topic: zod.string().optional().describe('The product, feature, or idea you want to ask interviewees about.'),
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
 * Generate (if needed) and email a personalized public interview link to every targeted interviewee on this topic whose identifier is an email address. Distinct-ID-only interviewees are skipped and surfaced in the response. Each invite is keyed on the underlying SharingConfiguration so re-runs after token rotation produce a fresh send.
 */
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

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const userInterviewTopicsIntervieweesUpdateBodyIntervieweeIdentifierMax = 400

export const userInterviewTopicsIntervieweesUpdateBodyAgentContextMax = 10000

export const UserInterviewTopicsIntervieweesUpdateBody = /* @__PURE__ */ zod.object({
    interviewee_identifier: zod
        .string()
        .max(userInterviewTopicsIntervieweesUpdateBodyIntervieweeIdentifierMax)
        .describe(
            "Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids."
        ),
    agent_context: zod
        .string()
        .max(userInterviewTopicsIntervieweesUpdateBodyAgentContextMax)
        .describe(
            "Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'."
        ),
})

/**
 * Per-interviewee extra context for a user interview topic. At most one row per (topic, interviewee_identifier).
 */
export const userInterviewTopicsIntervieweesPartialUpdateBodyIntervieweeIdentifierMax = 400

export const userInterviewTopicsIntervieweesPartialUpdateBodyAgentContextMax = 10000

export const UserInterviewTopicsIntervieweesPartialUpdateBody = /* @__PURE__ */ zod.object({
    interviewee_identifier: zod
        .string()
        .max(userInterviewTopicsIntervieweesPartialUpdateBodyIntervieweeIdentifierMax)
        .optional()
        .describe(
            "Identifier for the interviewee — typically an email address or PostHog distinct ID. Must match a value in the parent topic's interviewee_emails or interviewee_distinct_ids."
        ),
    agent_context: zod
        .string()
        .max(userInterviewTopicsIntervieweesPartialUpdateBodyAgentContextMax)
        .optional()
        .describe(
            "Extra context the voice agent should know about this specific interviewee — e.g. 'uses the replay product but has never used summarization'."
        ),
})

export const userInterviewsCreateBodyIntervieweeEmailsItemMax = 254

export const UserInterviewsCreateBody = /* @__PURE__ */ zod.object({
    interviewee_emails: zod.array(zod.string().max(userInterviewsCreateBodyIntervieweeEmailsItemMax)).optional(),
    summary: zod.string().optional(),
    audio: zod.url(),
})

export const userInterviewsUpdateBodyIntervieweeEmailsItemMax = 254

export const UserInterviewsUpdateBody = /* @__PURE__ */ zod.object({
    interviewee_emails: zod.array(zod.string().max(userInterviewsUpdateBodyIntervieweeEmailsItemMax)).optional(),
    summary: zod.string().optional(),
    audio: zod.url(),
})

export const userInterviewsPartialUpdateBodyIntervieweeEmailsItemMax = 254

export const UserInterviewsPartialUpdateBody = /* @__PURE__ */ zod.object({
    interviewee_emails: zod.array(zod.string().max(userInterviewsPartialUpdateBodyIntervieweeEmailsItemMax)).optional(),
    summary: zod.string().optional(),
    audio: zod.url().optional(),
})
