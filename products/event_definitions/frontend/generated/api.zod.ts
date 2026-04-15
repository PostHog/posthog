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

export const eventDefinitionsListResponseResultsItemNameMax = 400

export const eventDefinitionsListResponseResultsItemUpdatedByOneDistinctIdMax = 200

export const eventDefinitionsListResponseResultsItemUpdatedByOneFirstNameMax = 150

export const eventDefinitionsListResponseResultsItemUpdatedByOneLastNameMax = 150

export const eventDefinitionsListResponseResultsItemUpdatedByOneEmailMax = 254

export const eventDefinitionsListResponseResultsItemVerifiedByOneDistinctIdMax = 200

export const eventDefinitionsListResponseResultsItemVerifiedByOneFirstNameMax = 150

export const eventDefinitionsListResponseResultsItemVerifiedByOneLastNameMax = 150

export const eventDefinitionsListResponseResultsItemVerifiedByOneEmailMax = 254

export const eventDefinitionsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const eventDefinitionsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const eventDefinitionsListResponseResultsItemCreatedByOneLastNameMax = 150

export const eventDefinitionsListResponseResultsItemCreatedByOneEmailMax = 254

export const eventDefinitionsListResponseResultsItemPostToSlackDefault = false

export const EventDefinitionsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid(),
                name: zod.string().max(eventDefinitionsListResponseResultsItemNameMax),
                owner: zod.number().nullish(),
                description: zod.string().nullish(),
                tags: zod.array(zod.unknown()).optional(),
                created_at: zod.iso.datetime({}).nullable(),
                updated_at: zod.iso.datetime({}),
                updated_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(eventDefinitionsListResponseResultsItemUpdatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(eventDefinitionsListResponseResultsItemUpdatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(eventDefinitionsListResponseResultsItemUpdatedByOneLastNameMax)
                        .optional(),
                    email: zod.email().max(eventDefinitionsListResponseResultsItemUpdatedByOneEmailMax),
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
                last_seen_at: zod.iso.datetime({}).nullable(),
                last_updated_at: zod.iso.datetime({}),
                verified: zod.boolean().optional(),
                verified_at: zod.iso.datetime({}).nullable(),
                verified_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(eventDefinitionsListResponseResultsItemVerifiedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(eventDefinitionsListResponseResultsItemVerifiedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(eventDefinitionsListResponseResultsItemVerifiedByOneLastNameMax)
                        .optional(),
                    email: zod.email().max(eventDefinitionsListResponseResultsItemVerifiedByOneEmailMax),
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
                hidden: zod.boolean().nullish(),
                enforcement_mode: zod
                    .enum(['allow', 'reject'])
                    .optional()
                    .describe('* `allow` - Allow\n* `reject` - Reject'),
                is_action: zod.boolean(),
                action_id: zod.number(),
                is_calculating: zod.boolean(),
                last_calculated_at: zod.iso.datetime({}),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(eventDefinitionsListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(eventDefinitionsListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(eventDefinitionsListResponseResultsItemCreatedByOneLastNameMax)
                        .optional(),
                    email: zod.email().max(eventDefinitionsListResponseResultsItemCreatedByOneEmailMax),
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
                post_to_slack: zod.boolean().default(eventDefinitionsListResponseResultsItemPostToSlackDefault),
                default_columns: zod.array(zod.string()).optional(),
                media_preview_urls: zod.array(zod.string()),
            })
            .describe('Serializer mixin that handles tags for objects.')
    ),
})

export const eventDefinitionsCreateBodyNameMax = 400

export const eventDefinitionsCreateBodyPostToSlackDefault = false

export const EventDefinitionsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(eventDefinitionsCreateBodyNameMax),
        owner: zod.number().nullish(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
        enforcement_mode: zod.enum(['allow', 'reject']).optional().describe('* `allow` - Allow\n* `reject` - Reject'),
        post_to_slack: zod.boolean().default(eventDefinitionsCreateBodyPostToSlackDefault),
        default_columns: zod.array(zod.string()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const eventDefinitionsRetrieveResponseNameMax = 400

export const eventDefinitionsRetrieveResponseUpdatedByOneDistinctIdMax = 200

export const eventDefinitionsRetrieveResponseUpdatedByOneFirstNameMax = 150

export const eventDefinitionsRetrieveResponseUpdatedByOneLastNameMax = 150

export const eventDefinitionsRetrieveResponseUpdatedByOneEmailMax = 254

export const eventDefinitionsRetrieveResponseVerifiedByOneDistinctIdMax = 200

export const eventDefinitionsRetrieveResponseVerifiedByOneFirstNameMax = 150

export const eventDefinitionsRetrieveResponseVerifiedByOneLastNameMax = 150

export const eventDefinitionsRetrieveResponseVerifiedByOneEmailMax = 254

export const eventDefinitionsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const eventDefinitionsRetrieveResponseCreatedByOneFirstNameMax = 150

export const eventDefinitionsRetrieveResponseCreatedByOneLastNameMax = 150

export const eventDefinitionsRetrieveResponseCreatedByOneEmailMax = 254

export const eventDefinitionsRetrieveResponsePostToSlackDefault = false

export const EventDefinitionsRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(eventDefinitionsRetrieveResponseNameMax),
        owner: zod.number().nullish(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        created_at: zod.iso.datetime({}).nullable(),
        updated_at: zod.iso.datetime({}),
        updated_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(eventDefinitionsRetrieveResponseUpdatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(eventDefinitionsRetrieveResponseUpdatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(eventDefinitionsRetrieveResponseUpdatedByOneLastNameMax).optional(),
            email: zod.email().max(eventDefinitionsRetrieveResponseUpdatedByOneEmailMax),
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
        last_seen_at: zod.iso.datetime({}).nullable(),
        last_updated_at: zod.iso.datetime({}),
        verified: zod.boolean().optional(),
        verified_at: zod.iso.datetime({}).nullable(),
        verified_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(eventDefinitionsRetrieveResponseVerifiedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(eventDefinitionsRetrieveResponseVerifiedByOneFirstNameMax).optional(),
            last_name: zod.string().max(eventDefinitionsRetrieveResponseVerifiedByOneLastNameMax).optional(),
            email: zod.email().max(eventDefinitionsRetrieveResponseVerifiedByOneEmailMax),
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
        hidden: zod.boolean().nullish(),
        enforcement_mode: zod.enum(['allow', 'reject']).optional().describe('* `allow` - Allow\n* `reject` - Reject'),
        is_action: zod.boolean(),
        action_id: zod.number(),
        is_calculating: zod.boolean(),
        last_calculated_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(eventDefinitionsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(eventDefinitionsRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(eventDefinitionsRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(eventDefinitionsRetrieveResponseCreatedByOneEmailMax),
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
        post_to_slack: zod.boolean().default(eventDefinitionsRetrieveResponsePostToSlackDefault),
        default_columns: zod.array(zod.string()).optional(),
        media_preview_urls: zod.array(zod.string()),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const eventDefinitionsUpdateBodyNameMax = 400

export const eventDefinitionsUpdateBodyPostToSlackDefault = false

export const EventDefinitionsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(eventDefinitionsUpdateBodyNameMax),
        owner: zod.number().nullish(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
        enforcement_mode: zod.enum(['allow', 'reject']).optional().describe('* `allow` - Allow\n* `reject` - Reject'),
        post_to_slack: zod.boolean().default(eventDefinitionsUpdateBodyPostToSlackDefault),
        default_columns: zod.array(zod.string()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const eventDefinitionsUpdateResponseNameMax = 400

export const eventDefinitionsUpdateResponseUpdatedByOneDistinctIdMax = 200

export const eventDefinitionsUpdateResponseUpdatedByOneFirstNameMax = 150

export const eventDefinitionsUpdateResponseUpdatedByOneLastNameMax = 150

export const eventDefinitionsUpdateResponseUpdatedByOneEmailMax = 254

export const eventDefinitionsUpdateResponseVerifiedByOneDistinctIdMax = 200

export const eventDefinitionsUpdateResponseVerifiedByOneFirstNameMax = 150

export const eventDefinitionsUpdateResponseVerifiedByOneLastNameMax = 150

export const eventDefinitionsUpdateResponseVerifiedByOneEmailMax = 254

export const eventDefinitionsUpdateResponseCreatedByOneDistinctIdMax = 200

export const eventDefinitionsUpdateResponseCreatedByOneFirstNameMax = 150

export const eventDefinitionsUpdateResponseCreatedByOneLastNameMax = 150

export const eventDefinitionsUpdateResponseCreatedByOneEmailMax = 254

export const eventDefinitionsUpdateResponsePostToSlackDefault = false

export const EventDefinitionsUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(eventDefinitionsUpdateResponseNameMax),
        owner: zod.number().nullish(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        created_at: zod.iso.datetime({}).nullable(),
        updated_at: zod.iso.datetime({}),
        updated_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(eventDefinitionsUpdateResponseUpdatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(eventDefinitionsUpdateResponseUpdatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(eventDefinitionsUpdateResponseUpdatedByOneLastNameMax).optional(),
            email: zod.email().max(eventDefinitionsUpdateResponseUpdatedByOneEmailMax),
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
        last_seen_at: zod.iso.datetime({}).nullable(),
        last_updated_at: zod.iso.datetime({}),
        verified: zod.boolean().optional(),
        verified_at: zod.iso.datetime({}).nullable(),
        verified_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(eventDefinitionsUpdateResponseVerifiedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(eventDefinitionsUpdateResponseVerifiedByOneFirstNameMax).optional(),
            last_name: zod.string().max(eventDefinitionsUpdateResponseVerifiedByOneLastNameMax).optional(),
            email: zod.email().max(eventDefinitionsUpdateResponseVerifiedByOneEmailMax),
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
        hidden: zod.boolean().nullish(),
        enforcement_mode: zod.enum(['allow', 'reject']).optional().describe('* `allow` - Allow\n* `reject` - Reject'),
        is_action: zod.boolean(),
        action_id: zod.number(),
        is_calculating: zod.boolean(),
        last_calculated_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(eventDefinitionsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(eventDefinitionsUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(eventDefinitionsUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(eventDefinitionsUpdateResponseCreatedByOneEmailMax),
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
        post_to_slack: zod.boolean().default(eventDefinitionsUpdateResponsePostToSlackDefault),
        default_columns: zod.array(zod.string()).optional(),
        media_preview_urls: zod.array(zod.string()),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const eventDefinitionsPartialUpdateBodyNameMax = 400

export const eventDefinitionsPartialUpdateBodyPostToSlackDefault = false

export const EventDefinitionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(eventDefinitionsPartialUpdateBodyNameMax).optional(),
        owner: zod.number().nullish(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
        enforcement_mode: zod.enum(['allow', 'reject']).optional().describe('* `allow` - Allow\n* `reject` - Reject'),
        post_to_slack: zod.boolean().default(eventDefinitionsPartialUpdateBodyPostToSlackDefault),
        default_columns: zod.array(zod.string()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const eventDefinitionsPartialUpdateResponseNameMax = 400

export const eventDefinitionsPartialUpdateResponseUpdatedByOneDistinctIdMax = 200

export const eventDefinitionsPartialUpdateResponseUpdatedByOneFirstNameMax = 150

export const eventDefinitionsPartialUpdateResponseUpdatedByOneLastNameMax = 150

export const eventDefinitionsPartialUpdateResponseUpdatedByOneEmailMax = 254

export const eventDefinitionsPartialUpdateResponseVerifiedByOneDistinctIdMax = 200

export const eventDefinitionsPartialUpdateResponseVerifiedByOneFirstNameMax = 150

export const eventDefinitionsPartialUpdateResponseVerifiedByOneLastNameMax = 150

export const eventDefinitionsPartialUpdateResponseVerifiedByOneEmailMax = 254

export const eventDefinitionsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const eventDefinitionsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const eventDefinitionsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const eventDefinitionsPartialUpdateResponseCreatedByOneEmailMax = 254

export const eventDefinitionsPartialUpdateResponsePostToSlackDefault = false

export const EventDefinitionsPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(eventDefinitionsPartialUpdateResponseNameMax),
        owner: zod.number().nullish(),
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        created_at: zod.iso.datetime({}).nullable(),
        updated_at: zod.iso.datetime({}),
        updated_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(eventDefinitionsPartialUpdateResponseUpdatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(eventDefinitionsPartialUpdateResponseUpdatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(eventDefinitionsPartialUpdateResponseUpdatedByOneLastNameMax).optional(),
            email: zod.email().max(eventDefinitionsPartialUpdateResponseUpdatedByOneEmailMax),
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
        last_seen_at: zod.iso.datetime({}).nullable(),
        last_updated_at: zod.iso.datetime({}),
        verified: zod.boolean().optional(),
        verified_at: zod.iso.datetime({}).nullable(),
        verified_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(eventDefinitionsPartialUpdateResponseVerifiedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(eventDefinitionsPartialUpdateResponseVerifiedByOneFirstNameMax).optional(),
            last_name: zod.string().max(eventDefinitionsPartialUpdateResponseVerifiedByOneLastNameMax).optional(),
            email: zod.email().max(eventDefinitionsPartialUpdateResponseVerifiedByOneEmailMax),
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
        hidden: zod.boolean().nullish(),
        enforcement_mode: zod.enum(['allow', 'reject']).optional().describe('* `allow` - Allow\n* `reject` - Reject'),
        is_action: zod.boolean(),
        action_id: zod.number(),
        is_calculating: zod.boolean(),
        last_calculated_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(eventDefinitionsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(eventDefinitionsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(eventDefinitionsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(eventDefinitionsPartialUpdateResponseCreatedByOneEmailMax),
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
        post_to_slack: zod.boolean().default(eventDefinitionsPartialUpdateResponsePostToSlackDefault),
        default_columns: zod.array(zod.string()).optional(),
        media_preview_urls: zod.array(zod.string()),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Get event definition by exact name
 */
export const EventDefinitionsByNameRetrieveResponse = /* @__PURE__ */ zod.object({
    elements: zod.array(zod.unknown()),
    event: zod.string(),
    properties: zod.record(zod.string(), zod.unknown()),
})
