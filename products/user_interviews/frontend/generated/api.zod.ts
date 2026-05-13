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
