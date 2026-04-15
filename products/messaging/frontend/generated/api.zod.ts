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

export const messagingCategoriesListResponseResultsItemKeyMax = 64

export const messagingCategoriesListResponseResultsItemNameMax = 128

export const MessagingCategoriesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            key: zod.string().max(messagingCategoriesListResponseResultsItemKeyMax),
            name: zod.string().max(messagingCategoriesListResponseResultsItemNameMax),
            description: zod.string().optional(),
            public_description: zod.string().optional(),
            category_type: zod
                .enum(['marketing', 'transactional'])
                .optional()
                .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
            created_by: zod.number().nullable(),
            deleted: zod.boolean().optional(),
        })
    ),
})

export const messagingCategoriesCreateBodyKeyMax = 64

export const messagingCategoriesCreateBodyNameMax = 128

export const MessagingCategoriesCreateBody = /* @__PURE__ */ zod.object({
    key: zod.string().max(messagingCategoriesCreateBodyKeyMax),
    name: zod.string().max(messagingCategoriesCreateBodyNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
    deleted: zod.boolean().optional(),
})

/**
 * Import subscription topics and globally unsubscribed users from Customer.io API
 */
export const messagingCategoriesImportFromCustomerioCreateBodyKeyMax = 64

export const messagingCategoriesImportFromCustomerioCreateBodyNameMax = 128

export const MessagingCategoriesImportFromCustomerioCreateBody = /* @__PURE__ */ zod.object({
    key: zod.string().max(messagingCategoriesImportFromCustomerioCreateBodyKeyMax),
    name: zod.string().max(messagingCategoriesImportFromCustomerioCreateBodyNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
    deleted: zod.boolean().optional(),
})

export const messagingCategoriesImportFromCustomerioCreateResponseKeyMax = 64

export const messagingCategoriesImportFromCustomerioCreateResponseNameMax = 128

export const MessagingCategoriesImportFromCustomerioCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    key: zod.string().max(messagingCategoriesImportFromCustomerioCreateResponseKeyMax),
    name: zod.string().max(messagingCategoriesImportFromCustomerioCreateResponseNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    created_by: zod.number().nullable(),
    deleted: zod.boolean().optional(),
})

/**
 * Import customer preferences from CSV file
Expected CSV columns: id, email, cio_subscription_preferences
 */
export const messagingCategoriesImportPreferencesCsvCreateBodyKeyMax = 64

export const messagingCategoriesImportPreferencesCsvCreateBodyNameMax = 128

export const MessagingCategoriesImportPreferencesCsvCreateBody = /* @__PURE__ */ zod.object({
    key: zod.string().max(messagingCategoriesImportPreferencesCsvCreateBodyKeyMax),
    name: zod.string().max(messagingCategoriesImportPreferencesCsvCreateBodyNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
    deleted: zod.boolean().optional(),
})

export const messagingCategoriesImportPreferencesCsvCreateResponseKeyMax = 64

export const messagingCategoriesImportPreferencesCsvCreateResponseNameMax = 128

export const MessagingCategoriesImportPreferencesCsvCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    key: zod.string().max(messagingCategoriesImportPreferencesCsvCreateResponseKeyMax),
    name: zod.string().max(messagingCategoriesImportPreferencesCsvCreateResponseNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    created_by: zod.number().nullable(),
    deleted: zod.boolean().optional(),
})

export const messagingTemplatesListResponseResultsItemNameMax = 400

export const messagingTemplatesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const messagingTemplatesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const messagingTemplatesListResponseResultsItemCreatedByOneLastNameMax = 150

export const messagingTemplatesListResponseResultsItemCreatedByOneEmailMax = 254

export const messagingTemplatesListResponseResultsItemTypeMax = 24

export const MessagingTemplatesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string().max(messagingTemplatesListResponseResultsItemNameMax),
            description: zod.string().optional(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
            content: zod
                .object({
                    templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
                    email: zod
                        .object({
                            subject: zod.string().optional(),
                            text: zod.string().optional(),
                            html: zod.string().optional(),
                            design: zod.unknown().optional(),
                        })
                        .nullish(),
                })
                .optional(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(messagingTemplatesListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(messagingTemplatesListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(messagingTemplatesListResponseResultsItemCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(messagingTemplatesListResponseResultsItemCreatedByOneEmailMax),
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
            type: zod.string().max(messagingTemplatesListResponseResultsItemTypeMax).optional(),
            message_category: zod.uuid().nullish(),
            deleted: zod.boolean().optional(),
        })
    ),
})

export const messagingTemplatesCreateBodyNameMax = 400

export const messagingTemplatesCreateBodyTypeMax = 24

export const MessagingTemplatesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(messagingTemplatesCreateBodyNameMax),
    description: zod.string().optional(),
    content: zod
        .object({
            templating: zod.enum(['hog', 'liquid']).optional().describe('* `hog` - hog\n* `liquid` - liquid'),
            email: zod
                .object({
                    subject: zod.string().optional(),
                    text: zod.string().optional(),
                    html: zod.string().optional(),
                    design: zod.unknown().optional(),
                })
                .nullish(),
        })
        .optional(),
    type: zod.string().max(messagingTemplatesCreateBodyTypeMax).optional(),
    message_category: zod.uuid().nullish(),
    deleted: zod.boolean().optional(),
})
