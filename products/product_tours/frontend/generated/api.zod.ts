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

export const productToursListResponseResultsItemNameMax = 400

export const productToursListResponseResultsItemInternalTargetingFlagOneKeyMax = 400

export const productToursListResponseResultsItemInternalTargetingFlagOneVersionMin = -2147483648
export const productToursListResponseResultsItemInternalTargetingFlagOneVersionMax = 2147483647

export const productToursListResponseResultsItemLinkedFlagOneKeyMax = 400

export const productToursListResponseResultsItemLinkedFlagOneVersionMin = -2147483648
export const productToursListResponseResultsItemLinkedFlagOneVersionMax = 2147483647

export const productToursListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const productToursListResponseResultsItemCreatedByOneFirstNameMax = 150

export const productToursListResponseResultsItemCreatedByOneLastNameMax = 150

export const productToursListResponseResultsItemCreatedByOneEmailMax = 254

export const ProductToursListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid(),
                name: zod.string().max(productToursListResponseResultsItemNameMax),
                description: zod.string().optional(),
                internal_targeting_flag: zod.object({
                    id: zod.number(),
                    team_id: zod.number(),
                    name: zod.string().optional(),
                    key: zod.string().max(productToursListResponseResultsItemInternalTargetingFlagOneKeyMax),
                    filters: zod.record(zod.string(), zod.unknown()).optional(),
                    deleted: zod.boolean().optional(),
                    active: zod.boolean().optional(),
                    ensure_experience_continuity: zod.boolean().nullish(),
                    has_encrypted_payloads: zod.boolean().nullish(),
                    version: zod
                        .number()
                        .min(productToursListResponseResultsItemInternalTargetingFlagOneVersionMin)
                        .max(productToursListResponseResultsItemInternalTargetingFlagOneVersionMax)
                        .nullish(),
                    evaluation_runtime: zod
                        .union([
                            zod
                                .enum(['server', 'client', 'all'])
                                .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                        ),
                    bucketing_identifier: zod
                        .union([
                            zod
                                .enum(['distinct_id', 'device_id'])
                                .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                        ),
                    evaluation_contexts: zod.array(zod.string()),
                }),
                linked_flag: zod.object({
                    id: zod.number(),
                    team_id: zod.number(),
                    name: zod.string().optional(),
                    key: zod.string().max(productToursListResponseResultsItemLinkedFlagOneKeyMax),
                    filters: zod.record(zod.string(), zod.unknown()).optional(),
                    deleted: zod.boolean().optional(),
                    active: zod.boolean().optional(),
                    ensure_experience_continuity: zod.boolean().nullish(),
                    has_encrypted_payloads: zod.boolean().nullish(),
                    version: zod
                        .number()
                        .min(productToursListResponseResultsItemLinkedFlagOneVersionMin)
                        .max(productToursListResponseResultsItemLinkedFlagOneVersionMax)
                        .nullish(),
                    evaluation_runtime: zod
                        .union([
                            zod
                                .enum(['server', 'client', 'all'])
                                .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                        ),
                    bucketing_identifier: zod
                        .union([
                            zod
                                .enum(['distinct_id', 'device_id'])
                                .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish()
                        .describe(
                            'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                        ),
                    evaluation_contexts: zod.array(zod.string()),
                }),
                targeting_flag_filters: zod
                    .record(zod.string(), zod.unknown())
                    .nullable()
                    .describe('Return the targeting flag filters, excluding the base exclusion properties.'),
                content: zod.unknown().optional(),
                draft_content: zod.unknown().nullable(),
                has_draft: zod.boolean(),
                auto_launch: zod.boolean().optional(),
                start_date: zod.iso.datetime({}).nullish(),
                end_date: zod.iso.datetime({}).nullish(),
                created_at: zod.iso.datetime({}),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(productToursListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(productToursListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod.string().max(productToursListResponseResultsItemCreatedByOneLastNameMax).optional(),
                    email: zod.email().max(productToursListResponseResultsItemCreatedByOneEmailMax),
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
                updated_at: zod.iso.datetime({}),
                archived: zod.boolean().optional(),
            })
            .describe('Read-only serializer for ProductTour.')
    ),
})

export const productToursCreateBodyNameMax = 400

export const productToursCreateBodyCreationContextDefault = `app`

export const ProductToursCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(productToursCreateBodyNameMax),
        description: zod.string().optional(),
        linked_flag_id: zod.number().nullish(),
        targeting_flag_filters: zod.unknown().nullish(),
        content: zod.unknown().optional(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        archived: zod.boolean().optional(),
        creation_context: zod
            .enum(['app', 'toolbar'])
            .describe('* `app` - app\n* `toolbar` - toolbar')
            .default(productToursCreateBodyCreationContextDefault)
            .describe('Where the tour was created/updated from\n\n* `app` - app\n* `toolbar` - toolbar'),
    })
    .describe('Serializer for creating and updating ProductTour.')

export const productToursRetrieveResponseNameMax = 400

export const productToursRetrieveResponseInternalTargetingFlagOneKeyMax = 400

export const productToursRetrieveResponseInternalTargetingFlagOneVersionMin = -2147483648
export const productToursRetrieveResponseInternalTargetingFlagOneVersionMax = 2147483647

export const productToursRetrieveResponseLinkedFlagOneKeyMax = 400

export const productToursRetrieveResponseLinkedFlagOneVersionMin = -2147483648
export const productToursRetrieveResponseLinkedFlagOneVersionMax = 2147483647

export const productToursRetrieveResponseCreatedByOneDistinctIdMax = 200

export const productToursRetrieveResponseCreatedByOneFirstNameMax = 150

export const productToursRetrieveResponseCreatedByOneLastNameMax = 150

export const productToursRetrieveResponseCreatedByOneEmailMax = 254

export const ProductToursRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(productToursRetrieveResponseNameMax),
        description: zod.string().optional(),
        internal_targeting_flag: zod.object({
            id: zod.number(),
            team_id: zod.number(),
            name: zod.string().optional(),
            key: zod.string().max(productToursRetrieveResponseInternalTargetingFlagOneKeyMax),
            filters: zod.record(zod.string(), zod.unknown()).optional(),
            deleted: zod.boolean().optional(),
            active: zod.boolean().optional(),
            ensure_experience_continuity: zod.boolean().nullish(),
            has_encrypted_payloads: zod.boolean().nullish(),
            version: zod
                .number()
                .min(productToursRetrieveResponseInternalTargetingFlagOneVersionMin)
                .max(productToursRetrieveResponseInternalTargetingFlagOneVersionMax)
                .nullish(),
            evaluation_runtime: zod
                .union([
                    zod
                        .enum(['server', 'client', 'all'])
                        .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                ),
            bucketing_identifier: zod
                .union([
                    zod
                        .enum(['distinct_id', 'device_id'])
                        .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                ),
            evaluation_contexts: zod.array(zod.string()),
        }),
        linked_flag: zod.object({
            id: zod.number(),
            team_id: zod.number(),
            name: zod.string().optional(),
            key: zod.string().max(productToursRetrieveResponseLinkedFlagOneKeyMax),
            filters: zod.record(zod.string(), zod.unknown()).optional(),
            deleted: zod.boolean().optional(),
            active: zod.boolean().optional(),
            ensure_experience_continuity: zod.boolean().nullish(),
            has_encrypted_payloads: zod.boolean().nullish(),
            version: zod
                .number()
                .min(productToursRetrieveResponseLinkedFlagOneVersionMin)
                .max(productToursRetrieveResponseLinkedFlagOneVersionMax)
                .nullish(),
            evaluation_runtime: zod
                .union([
                    zod
                        .enum(['server', 'client', 'all'])
                        .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                ),
            bucketing_identifier: zod
                .union([
                    zod
                        .enum(['distinct_id', 'device_id'])
                        .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                ),
            evaluation_contexts: zod.array(zod.string()),
        }),
        targeting_flag_filters: zod
            .record(zod.string(), zod.unknown())
            .nullable()
            .describe('Return the targeting flag filters, excluding the base exclusion properties.'),
        content: zod.unknown().optional(),
        draft_content: zod.unknown().nullable(),
        has_draft: zod.boolean(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(productToursRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(productToursRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(productToursRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(productToursRetrieveResponseCreatedByOneEmailMax),
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
        updated_at: zod.iso.datetime({}),
        archived: zod.boolean().optional(),
    })
    .describe('Read-only serializer for ProductTour.')

export const productToursUpdateBodyNameMax = 400

export const ProductToursUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(productToursUpdateBodyNameMax),
        description: zod.string().optional(),
        content: zod.unknown().optional(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        archived: zod.boolean().optional(),
    })
    .describe('Read-only serializer for ProductTour.')

export const productToursUpdateResponseNameMax = 400

export const productToursUpdateResponseInternalTargetingFlagOneKeyMax = 400

export const productToursUpdateResponseInternalTargetingFlagOneVersionMin = -2147483648
export const productToursUpdateResponseInternalTargetingFlagOneVersionMax = 2147483647

export const productToursUpdateResponseLinkedFlagOneKeyMax = 400

export const productToursUpdateResponseLinkedFlagOneVersionMin = -2147483648
export const productToursUpdateResponseLinkedFlagOneVersionMax = 2147483647

export const productToursUpdateResponseCreatedByOneDistinctIdMax = 200

export const productToursUpdateResponseCreatedByOneFirstNameMax = 150

export const productToursUpdateResponseCreatedByOneLastNameMax = 150

export const productToursUpdateResponseCreatedByOneEmailMax = 254

export const ProductToursUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(productToursUpdateResponseNameMax),
        description: zod.string().optional(),
        internal_targeting_flag: zod.object({
            id: zod.number(),
            team_id: zod.number(),
            name: zod.string().optional(),
            key: zod.string().max(productToursUpdateResponseInternalTargetingFlagOneKeyMax),
            filters: zod.record(zod.string(), zod.unknown()).optional(),
            deleted: zod.boolean().optional(),
            active: zod.boolean().optional(),
            ensure_experience_continuity: zod.boolean().nullish(),
            has_encrypted_payloads: zod.boolean().nullish(),
            version: zod
                .number()
                .min(productToursUpdateResponseInternalTargetingFlagOneVersionMin)
                .max(productToursUpdateResponseInternalTargetingFlagOneVersionMax)
                .nullish(),
            evaluation_runtime: zod
                .union([
                    zod
                        .enum(['server', 'client', 'all'])
                        .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                ),
            bucketing_identifier: zod
                .union([
                    zod
                        .enum(['distinct_id', 'device_id'])
                        .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                ),
            evaluation_contexts: zod.array(zod.string()),
        }),
        linked_flag: zod.object({
            id: zod.number(),
            team_id: zod.number(),
            name: zod.string().optional(),
            key: zod.string().max(productToursUpdateResponseLinkedFlagOneKeyMax),
            filters: zod.record(zod.string(), zod.unknown()).optional(),
            deleted: zod.boolean().optional(),
            active: zod.boolean().optional(),
            ensure_experience_continuity: zod.boolean().nullish(),
            has_encrypted_payloads: zod.boolean().nullish(),
            version: zod
                .number()
                .min(productToursUpdateResponseLinkedFlagOneVersionMin)
                .max(productToursUpdateResponseLinkedFlagOneVersionMax)
                .nullish(),
            evaluation_runtime: zod
                .union([
                    zod
                        .enum(['server', 'client', 'all'])
                        .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                ),
            bucketing_identifier: zod
                .union([
                    zod
                        .enum(['distinct_id', 'device_id'])
                        .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                ),
            evaluation_contexts: zod.array(zod.string()),
        }),
        targeting_flag_filters: zod
            .record(zod.string(), zod.unknown())
            .nullable()
            .describe('Return the targeting flag filters, excluding the base exclusion properties.'),
        content: zod.unknown().optional(),
        draft_content: zod.unknown().nullable(),
        has_draft: zod.boolean(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(productToursUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(productToursUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(productToursUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(productToursUpdateResponseCreatedByOneEmailMax),
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
        updated_at: zod.iso.datetime({}),
        archived: zod.boolean().optional(),
    })
    .describe('Read-only serializer for ProductTour.')

export const productToursPartialUpdateBodyNameMax = 400

export const productToursPartialUpdateBodyCreationContextDefault = `app`

export const ProductToursPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(productToursPartialUpdateBodyNameMax).optional(),
        description: zod.string().optional(),
        linked_flag_id: zod.number().nullish(),
        targeting_flag_filters: zod.unknown().nullish(),
        content: zod.unknown().optional(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        archived: zod.boolean().optional(),
        creation_context: zod
            .enum(['app', 'toolbar'])
            .describe('* `app` - app\n* `toolbar` - toolbar')
            .default(productToursPartialUpdateBodyCreationContextDefault)
            .describe('Where the tour was created/updated from\n\n* `app` - app\n* `toolbar` - toolbar'),
    })
    .describe('Serializer for creating and updating ProductTour.')

export const productToursPartialUpdateResponseNameMax = 400

export const productToursPartialUpdateResponseInternalTargetingFlagOneKeyMax = 400

export const productToursPartialUpdateResponseInternalTargetingFlagOneVersionMin = -2147483648
export const productToursPartialUpdateResponseInternalTargetingFlagOneVersionMax = 2147483647

export const productToursPartialUpdateResponseLinkedFlagOneKeyMax = 400

export const productToursPartialUpdateResponseLinkedFlagOneVersionMin = -2147483648
export const productToursPartialUpdateResponseLinkedFlagOneVersionMax = 2147483647

export const productToursPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const productToursPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const productToursPartialUpdateResponseCreatedByOneLastNameMax = 150

export const productToursPartialUpdateResponseCreatedByOneEmailMax = 254

export const productToursPartialUpdateResponseCreationContextDefault = `app`

export const ProductToursPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(productToursPartialUpdateResponseNameMax),
        description: zod.string().optional(),
        internal_targeting_flag: zod.object({
            id: zod.number(),
            team_id: zod.number(),
            name: zod.string().optional(),
            key: zod.string().max(productToursPartialUpdateResponseInternalTargetingFlagOneKeyMax),
            filters: zod.record(zod.string(), zod.unknown()).optional(),
            deleted: zod.boolean().optional(),
            active: zod.boolean().optional(),
            ensure_experience_continuity: zod.boolean().nullish(),
            has_encrypted_payloads: zod.boolean().nullish(),
            version: zod
                .number()
                .min(productToursPartialUpdateResponseInternalTargetingFlagOneVersionMin)
                .max(productToursPartialUpdateResponseInternalTargetingFlagOneVersionMax)
                .nullish(),
            evaluation_runtime: zod
                .union([
                    zod
                        .enum(['server', 'client', 'all'])
                        .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                ),
            bucketing_identifier: zod
                .union([
                    zod
                        .enum(['distinct_id', 'device_id'])
                        .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                ),
            evaluation_contexts: zod.array(zod.string()),
        }),
        linked_flag: zod.object({
            id: zod.number(),
            team_id: zod.number(),
            name: zod.string().optional(),
            key: zod.string().max(productToursPartialUpdateResponseLinkedFlagOneKeyMax),
            filters: zod.record(zod.string(), zod.unknown()).optional(),
            deleted: zod.boolean().optional(),
            active: zod.boolean().optional(),
            ensure_experience_continuity: zod.boolean().nullish(),
            has_encrypted_payloads: zod.boolean().nullish(),
            version: zod
                .number()
                .min(productToursPartialUpdateResponseLinkedFlagOneVersionMin)
                .max(productToursPartialUpdateResponseLinkedFlagOneVersionMax)
                .nullish(),
            evaluation_runtime: zod
                .union([
                    zod
                        .enum(['server', 'client', 'all'])
                        .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                ),
            bucketing_identifier: zod
                .union([
                    zod
                        .enum(['distinct_id', 'device_id'])
                        .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                ),
            evaluation_contexts: zod.array(zod.string()),
        }),
        linked_flag_id: zod.number().nullish(),
        targeting_flag_filters: zod.unknown().nullish(),
        content: zod.unknown().optional(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(productToursPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(productToursPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(productToursPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(productToursPartialUpdateResponseCreatedByOneEmailMax),
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
        updated_at: zod.iso.datetime({}),
        archived: zod.boolean().optional(),
        creation_context: zod
            .enum(['app', 'toolbar'])
            .describe('* `app` - app\n* `toolbar` - toolbar')
            .default(productToursPartialUpdateResponseCreationContextDefault)
            .describe('Where the tour was created/updated from\n\n* `app` - app\n* `toolbar` - toolbar'),
    })
    .describe('Serializer for creating and updating ProductTour.')

/**
 * Discard draft content.
 */
export const productToursDiscardDraftDestroyResponseNameMax = 400

export const productToursDiscardDraftDestroyResponseInternalTargetingFlagOneKeyMax = 400

export const productToursDiscardDraftDestroyResponseInternalTargetingFlagOneVersionMin = -2147483648
export const productToursDiscardDraftDestroyResponseInternalTargetingFlagOneVersionMax = 2147483647

export const productToursDiscardDraftDestroyResponseLinkedFlagOneKeyMax = 400

export const productToursDiscardDraftDestroyResponseLinkedFlagOneVersionMin = -2147483648
export const productToursDiscardDraftDestroyResponseLinkedFlagOneVersionMax = 2147483647

export const productToursDiscardDraftDestroyResponseCreatedByOneDistinctIdMax = 200

export const productToursDiscardDraftDestroyResponseCreatedByOneFirstNameMax = 150

export const productToursDiscardDraftDestroyResponseCreatedByOneLastNameMax = 150

export const productToursDiscardDraftDestroyResponseCreatedByOneEmailMax = 254

export const ProductToursDiscardDraftDestroyResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(productToursDiscardDraftDestroyResponseNameMax),
        description: zod.string().optional(),
        internal_targeting_flag: zod.object({
            id: zod.number(),
            team_id: zod.number(),
            name: zod.string().optional(),
            key: zod.string().max(productToursDiscardDraftDestroyResponseInternalTargetingFlagOneKeyMax),
            filters: zod.record(zod.string(), zod.unknown()).optional(),
            deleted: zod.boolean().optional(),
            active: zod.boolean().optional(),
            ensure_experience_continuity: zod.boolean().nullish(),
            has_encrypted_payloads: zod.boolean().nullish(),
            version: zod
                .number()
                .min(productToursDiscardDraftDestroyResponseInternalTargetingFlagOneVersionMin)
                .max(productToursDiscardDraftDestroyResponseInternalTargetingFlagOneVersionMax)
                .nullish(),
            evaluation_runtime: zod
                .union([
                    zod
                        .enum(['server', 'client', 'all'])
                        .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                ),
            bucketing_identifier: zod
                .union([
                    zod
                        .enum(['distinct_id', 'device_id'])
                        .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                ),
            evaluation_contexts: zod.array(zod.string()),
        }),
        linked_flag: zod.object({
            id: zod.number(),
            team_id: zod.number(),
            name: zod.string().optional(),
            key: zod.string().max(productToursDiscardDraftDestroyResponseLinkedFlagOneKeyMax),
            filters: zod.record(zod.string(), zod.unknown()).optional(),
            deleted: zod.boolean().optional(),
            active: zod.boolean().optional(),
            ensure_experience_continuity: zod.boolean().nullish(),
            has_encrypted_payloads: zod.boolean().nullish(),
            version: zod
                .number()
                .min(productToursDiscardDraftDestroyResponseLinkedFlagOneVersionMin)
                .max(productToursDiscardDraftDestroyResponseLinkedFlagOneVersionMax)
                .nullish(),
            evaluation_runtime: zod
                .union([
                    zod
                        .enum(['server', 'client', 'all'])
                        .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                ),
            bucketing_identifier: zod
                .union([
                    zod
                        .enum(['distinct_id', 'device_id'])
                        .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                ),
            evaluation_contexts: zod.array(zod.string()),
        }),
        targeting_flag_filters: zod
            .record(zod.string(), zod.unknown())
            .nullable()
            .describe('Return the targeting flag filters, excluding the base exclusion properties.'),
        content: zod.unknown().optional(),
        draft_content: zod.unknown().nullable(),
        has_draft: zod.boolean(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(productToursDiscardDraftDestroyResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(productToursDiscardDraftDestroyResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(productToursDiscardDraftDestroyResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(productToursDiscardDraftDestroyResponseCreatedByOneEmailMax),
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
        updated_at: zod.iso.datetime({}),
        archived: zod.boolean().optional(),
    })
    .describe('Read-only serializer for ProductTour.')

/**
 * Save draft content (server-side merge). No side effects triggered.
 */
export const productToursDraftPartialUpdateBodyNameMax = 400

export const productToursDraftPartialUpdateBodyCreationContextDefault = `app`

export const ProductToursDraftPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(productToursDraftPartialUpdateBodyNameMax).optional(),
        description: zod.string().optional(),
        linked_flag_id: zod.number().nullish(),
        targeting_flag_filters: zod.unknown().nullish(),
        content: zod.unknown().optional(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        archived: zod.boolean().optional(),
        creation_context: zod
            .enum(['app', 'toolbar'])
            .describe('* `app` - app\n* `toolbar` - toolbar')
            .default(productToursDraftPartialUpdateBodyCreationContextDefault)
            .describe('Where the tour was created/updated from\n\n* `app` - app\n* `toolbar` - toolbar'),
    })
    .describe('Serializer for creating and updating ProductTour.')

export const productToursDraftPartialUpdateResponseNameMax = 400

export const productToursDraftPartialUpdateResponseInternalTargetingFlagOneKeyMax = 400

export const productToursDraftPartialUpdateResponseInternalTargetingFlagOneVersionMin = -2147483648
export const productToursDraftPartialUpdateResponseInternalTargetingFlagOneVersionMax = 2147483647

export const productToursDraftPartialUpdateResponseLinkedFlagOneKeyMax = 400

export const productToursDraftPartialUpdateResponseLinkedFlagOneVersionMin = -2147483648
export const productToursDraftPartialUpdateResponseLinkedFlagOneVersionMax = 2147483647

export const productToursDraftPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const productToursDraftPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const productToursDraftPartialUpdateResponseCreatedByOneLastNameMax = 150

export const productToursDraftPartialUpdateResponseCreatedByOneEmailMax = 254

export const ProductToursDraftPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(productToursDraftPartialUpdateResponseNameMax),
        description: zod.string().optional(),
        internal_targeting_flag: zod.object({
            id: zod.number(),
            team_id: zod.number(),
            name: zod.string().optional(),
            key: zod.string().max(productToursDraftPartialUpdateResponseInternalTargetingFlagOneKeyMax),
            filters: zod.record(zod.string(), zod.unknown()).optional(),
            deleted: zod.boolean().optional(),
            active: zod.boolean().optional(),
            ensure_experience_continuity: zod.boolean().nullish(),
            has_encrypted_payloads: zod.boolean().nullish(),
            version: zod
                .number()
                .min(productToursDraftPartialUpdateResponseInternalTargetingFlagOneVersionMin)
                .max(productToursDraftPartialUpdateResponseInternalTargetingFlagOneVersionMax)
                .nullish(),
            evaluation_runtime: zod
                .union([
                    zod
                        .enum(['server', 'client', 'all'])
                        .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                ),
            bucketing_identifier: zod
                .union([
                    zod
                        .enum(['distinct_id', 'device_id'])
                        .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                ),
            evaluation_contexts: zod.array(zod.string()),
        }),
        linked_flag: zod.object({
            id: zod.number(),
            team_id: zod.number(),
            name: zod.string().optional(),
            key: zod.string().max(productToursDraftPartialUpdateResponseLinkedFlagOneKeyMax),
            filters: zod.record(zod.string(), zod.unknown()).optional(),
            deleted: zod.boolean().optional(),
            active: zod.boolean().optional(),
            ensure_experience_continuity: zod.boolean().nullish(),
            has_encrypted_payloads: zod.boolean().nullish(),
            version: zod
                .number()
                .min(productToursDraftPartialUpdateResponseLinkedFlagOneVersionMin)
                .max(productToursDraftPartialUpdateResponseLinkedFlagOneVersionMax)
                .nullish(),
            evaluation_runtime: zod
                .union([
                    zod
                        .enum(['server', 'client', 'all'])
                        .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                ),
            bucketing_identifier: zod
                .union([
                    zod
                        .enum(['distinct_id', 'device_id'])
                        .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                ),
            evaluation_contexts: zod.array(zod.string()),
        }),
        targeting_flag_filters: zod
            .record(zod.string(), zod.unknown())
            .nullable()
            .describe('Return the targeting flag filters, excluding the base exclusion properties.'),
        content: zod.unknown().optional(),
        draft_content: zod.unknown().nullable(),
        has_draft: zod.boolean(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(productToursDraftPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(productToursDraftPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(productToursDraftPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(productToursDraftPartialUpdateResponseCreatedByOneEmailMax),
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
        updated_at: zod.iso.datetime({}),
        archived: zod.boolean().optional(),
    })
    .describe('Read-only serializer for ProductTour.')

/**
 * Lightweight polling endpoint for draft change detection.
 */
export const ProductToursDraftStatusRetrieveResponse = /* @__PURE__ */ zod.object({
    updated_at: zod.iso.datetime({}),
    has_draft: zod.boolean(),
})

/**
 * Generate tour step content using AI.
 */
export const productToursGenerateCreateBodyTitleDefault = ``
export const productToursGenerateCreateBodyGoalDefault = ``

export const ProductToursGenerateCreateBody = /* @__PURE__ */ zod.object({
    title: zod.string().default(productToursGenerateCreateBodyTitleDefault),
    goal: zod.string().default(productToursGenerateCreateBodyGoalDefault),
    steps: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
})

export const ProductToursGenerateCreateResponse = /* @__PURE__ */ zod.object({
    steps: zod.array(
        zod.object({
            step_id: zod.string(),
            title: zod.string(),
            description: zod.string(),
        })
    ),
})

/**
 * Commit draft to live tour. Runs full validation and triggers side effects.

Accepts an optional body payload. If provided, merges it into the draft
before publishing so the caller can save + publish in a single request.
 */
export const productToursPublishDraftCreateBodyNameMax = 400

export const productToursPublishDraftCreateBodyCreationContextDefault = `app`

export const ProductToursPublishDraftCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(productToursPublishDraftCreateBodyNameMax),
        description: zod.string().optional(),
        linked_flag_id: zod.number().nullish(),
        targeting_flag_filters: zod.unknown().nullish(),
        content: zod.unknown().optional(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        archived: zod.boolean().optional(),
        creation_context: zod
            .enum(['app', 'toolbar'])
            .describe('* `app` - app\n* `toolbar` - toolbar')
            .default(productToursPublishDraftCreateBodyCreationContextDefault)
            .describe('Where the tour was created/updated from\n\n* `app` - app\n* `toolbar` - toolbar'),
    })
    .describe('Serializer for creating and updating ProductTour.')

export const productToursPublishDraftCreateResponseNameMax = 400

export const productToursPublishDraftCreateResponseInternalTargetingFlagOneKeyMax = 400

export const productToursPublishDraftCreateResponseInternalTargetingFlagOneVersionMin = -2147483648
export const productToursPublishDraftCreateResponseInternalTargetingFlagOneVersionMax = 2147483647

export const productToursPublishDraftCreateResponseLinkedFlagOneKeyMax = 400

export const productToursPublishDraftCreateResponseLinkedFlagOneVersionMin = -2147483648
export const productToursPublishDraftCreateResponseLinkedFlagOneVersionMax = 2147483647

export const productToursPublishDraftCreateResponseCreatedByOneDistinctIdMax = 200

export const productToursPublishDraftCreateResponseCreatedByOneFirstNameMax = 150

export const productToursPublishDraftCreateResponseCreatedByOneLastNameMax = 150

export const productToursPublishDraftCreateResponseCreatedByOneEmailMax = 254

export const ProductToursPublishDraftCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(productToursPublishDraftCreateResponseNameMax),
        description: zod.string().optional(),
        internal_targeting_flag: zod.object({
            id: zod.number(),
            team_id: zod.number(),
            name: zod.string().optional(),
            key: zod.string().max(productToursPublishDraftCreateResponseInternalTargetingFlagOneKeyMax),
            filters: zod.record(zod.string(), zod.unknown()).optional(),
            deleted: zod.boolean().optional(),
            active: zod.boolean().optional(),
            ensure_experience_continuity: zod.boolean().nullish(),
            has_encrypted_payloads: zod.boolean().nullish(),
            version: zod
                .number()
                .min(productToursPublishDraftCreateResponseInternalTargetingFlagOneVersionMin)
                .max(productToursPublishDraftCreateResponseInternalTargetingFlagOneVersionMax)
                .nullish(),
            evaluation_runtime: zod
                .union([
                    zod
                        .enum(['server', 'client', 'all'])
                        .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                ),
            bucketing_identifier: zod
                .union([
                    zod
                        .enum(['distinct_id', 'device_id'])
                        .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                ),
            evaluation_contexts: zod.array(zod.string()),
        }),
        linked_flag: zod.object({
            id: zod.number(),
            team_id: zod.number(),
            name: zod.string().optional(),
            key: zod.string().max(productToursPublishDraftCreateResponseLinkedFlagOneKeyMax),
            filters: zod.record(zod.string(), zod.unknown()).optional(),
            deleted: zod.boolean().optional(),
            active: zod.boolean().optional(),
            ensure_experience_continuity: zod.boolean().nullish(),
            has_encrypted_payloads: zod.boolean().nullish(),
            version: zod
                .number()
                .min(productToursPublishDraftCreateResponseLinkedFlagOneVersionMin)
                .max(productToursPublishDraftCreateResponseLinkedFlagOneVersionMax)
                .nullish(),
            evaluation_runtime: zod
                .union([
                    zod
                        .enum(['server', 'client', 'all'])
                        .describe('* `server` - Server\n* `client` - Client\n* `all` - All'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Specifies where this feature flag should be evaluated\n\n* `server` - Server\n* `client` - Client\n* `all` - All'
                ),
            bucketing_identifier: zod
                .union([
                    zod
                        .enum(['distinct_id', 'device_id'])
                        .describe('* `distinct_id` - User ID (default)\n* `device_id` - Device ID'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Identifier used for bucketing users into rollout and variants\n\n* `distinct_id` - User ID (default)\n* `device_id` - Device ID'
                ),
            evaluation_contexts: zod.array(zod.string()),
        }),
        targeting_flag_filters: zod
            .record(zod.string(), zod.unknown())
            .nullable()
            .describe('Return the targeting flag filters, excluding the base exclusion properties.'),
        content: zod.unknown().optional(),
        draft_content: zod.unknown().nullable(),
        has_draft: zod.boolean(),
        auto_launch: zod.boolean().optional(),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(productToursPublishDraftCreateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(productToursPublishDraftCreateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(productToursPublishDraftCreateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(productToursPublishDraftCreateResponseCreatedByOneEmailMax),
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
        updated_at: zod.iso.datetime({}),
        archived: zod.boolean().optional(),
    })
    .describe('Read-only serializer for ProductTour.')
