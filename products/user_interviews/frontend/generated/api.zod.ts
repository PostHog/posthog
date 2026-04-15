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

export const userInterviewsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const userInterviewsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const userInterviewsListResponseResultsItemCreatedByOneLastNameMax = 150

export const userInterviewsListResponseResultsItemCreatedByOneEmailMax = 254

export const userInterviewsListResponseResultsItemIntervieweeEmailsItemMax = 254

export const UserInterviewsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(userInterviewsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(userInterviewsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(userInterviewsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(userInterviewsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.iso.datetime({}),
            interviewee_emails: zod
                .array(zod.string().max(userInterviewsListResponseResultsItemIntervieweeEmailsItemMax))
                .optional(),
            transcript: zod.string(),
            summary: zod.string().optional(),
            audio: zod.url(),
        })
    ),
})

export const userInterviewsCreateBodyIntervieweeEmailsItemMax = 254

export const UserInterviewsCreateBody = /* @__PURE__ */ zod.object({
    interviewee_emails: zod.array(zod.string().max(userInterviewsCreateBodyIntervieweeEmailsItemMax)).optional(),
    summary: zod.string().optional(),
    audio: zod.url(),
})

export const userInterviewsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const userInterviewsRetrieveResponseCreatedByOneFirstNameMax = 150

export const userInterviewsRetrieveResponseCreatedByOneLastNameMax = 150

export const userInterviewsRetrieveResponseCreatedByOneEmailMax = 254

export const userInterviewsRetrieveResponseIntervieweeEmailsItemMax = 254

export const UserInterviewsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(userInterviewsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(userInterviewsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(userInterviewsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(userInterviewsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}),
    interviewee_emails: zod.array(zod.string().max(userInterviewsRetrieveResponseIntervieweeEmailsItemMax)).optional(),
    transcript: zod.string(),
    summary: zod.string().optional(),
    audio: zod.url(),
})

export const userInterviewsUpdateBodyIntervieweeEmailsItemMax = 254

export const UserInterviewsUpdateBody = /* @__PURE__ */ zod.object({
    interviewee_emails: zod.array(zod.string().max(userInterviewsUpdateBodyIntervieweeEmailsItemMax)).optional(),
    summary: zod.string().optional(),
    audio: zod.url(),
})

export const userInterviewsUpdateResponseCreatedByOneDistinctIdMax = 200

export const userInterviewsUpdateResponseCreatedByOneFirstNameMax = 150

export const userInterviewsUpdateResponseCreatedByOneLastNameMax = 150

export const userInterviewsUpdateResponseCreatedByOneEmailMax = 254

export const userInterviewsUpdateResponseIntervieweeEmailsItemMax = 254

export const UserInterviewsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(userInterviewsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(userInterviewsUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(userInterviewsUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(userInterviewsUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}),
    interviewee_emails: zod.array(zod.string().max(userInterviewsUpdateResponseIntervieweeEmailsItemMax)).optional(),
    transcript: zod.string(),
    summary: zod.string().optional(),
    audio: zod.url(),
})

export const userInterviewsPartialUpdateBodyIntervieweeEmailsItemMax = 254

export const UserInterviewsPartialUpdateBody = /* @__PURE__ */ zod.object({
    interviewee_emails: zod.array(zod.string().max(userInterviewsPartialUpdateBodyIntervieweeEmailsItemMax)).optional(),
    summary: zod.string().optional(),
    audio: zod.url().optional(),
})

export const userInterviewsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const userInterviewsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const userInterviewsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const userInterviewsPartialUpdateResponseCreatedByOneEmailMax = 254

export const userInterviewsPartialUpdateResponseIntervieweeEmailsItemMax = 254

export const UserInterviewsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(userInterviewsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(userInterviewsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(userInterviewsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(userInterviewsPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}),
    interviewee_emails: zod
        .array(zod.string().max(userInterviewsPartialUpdateResponseIntervieweeEmailsItemMax))
        .optional(),
    transcript: zod.string(),
    summary: zod.string().optional(),
    audio: zod.url(),
})
