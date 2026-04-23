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
