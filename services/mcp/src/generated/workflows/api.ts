/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 8 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const MessagingCategoriesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const MessagingCategoriesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const messagingCategoriesListResponseResultsItemKeyMax = 64

export const messagingCategoriesListResponseResultsItemNameMax = 128

export const MessagingCategoriesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            key: zod.string().max(messagingCategoriesListResponseResultsItemKeyMax),
            name: zod.string().max(messagingCategoriesListResponseResultsItemNameMax),
            description: zod.string().optional(),
            public_description: zod.string().optional(),
            category_type: zod
                .enum(['marketing', 'transactional'])
                .optional()
                .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
            created_at: zod.string().datetime({}),
            updated_at: zod.string().datetime({}),
            created_by: zod.number().nullable(),
            deleted: zod.boolean().optional(),
        })
    ),
})

export const MessagingCategoriesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const messagingCategoriesCreateBodyKeyMax = 64

export const messagingCategoriesCreateBodyNameMax = 128

export const MessagingCategoriesCreateBody = zod.object({
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
export const MessagingCategoriesImportFromCustomerioCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const messagingCategoriesImportFromCustomerioCreateBodyKeyMax = 64

export const messagingCategoriesImportFromCustomerioCreateBodyNameMax = 128

export const MessagingCategoriesImportFromCustomerioCreateBody = zod.object({
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

export const MessagingCategoriesImportFromCustomerioCreateResponse = zod.object({
    id: zod.string(),
    key: zod.string().max(messagingCategoriesImportFromCustomerioCreateResponseKeyMax),
    name: zod.string().max(messagingCategoriesImportFromCustomerioCreateResponseNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
    created_at: zod.string().datetime({}),
    updated_at: zod.string().datetime({}),
    created_by: zod.number().nullable(),
    deleted: zod.boolean().optional(),
})

/**
 * Import customer preferences from CSV file
Expected CSV columns: id, email, cio_subscription_preferences
 */
export const MessagingCategoriesImportPreferencesCsvCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const messagingCategoriesImportPreferencesCsvCreateBodyKeyMax = 64

export const messagingCategoriesImportPreferencesCsvCreateBodyNameMax = 128

export const MessagingCategoriesImportPreferencesCsvCreateBody = zod.object({
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

export const MessagingCategoriesImportPreferencesCsvCreateResponse = zod.object({
    id: zod.string(),
    key: zod.string().max(messagingCategoriesImportPreferencesCsvCreateResponseKeyMax),
    name: zod.string().max(messagingCategoriesImportPreferencesCsvCreateResponseNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
    created_at: zod.string().datetime({}),
    updated_at: zod.string().datetime({}),
    created_by: zod.number().nullable(),
    deleted: zod.boolean().optional(),
})

/**
 * Generate an unsubscribe link for the current user's email address
 */
export const MessagingPreferencesGenerateLinkCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Get opt-outs filtered by category or overall opt-outs if no category specified
 */
export const MessagingPreferencesOptOutsRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const MessagingTemplatesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const MessagingTemplatesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const messagingTemplatesListResponseResultsItemNameMax = 400

export const messagingTemplatesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const messagingTemplatesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const messagingTemplatesListResponseResultsItemCreatedByOneLastNameMax = 150

export const messagingTemplatesListResponseResultsItemCreatedByOneEmailMax = 254

export const messagingTemplatesListResponseResultsItemTypeMax = 24

export const MessagingTemplatesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(messagingTemplatesListResponseResultsItemNameMax),
            description: zod.string().optional(),
            created_at: zod.string().datetime({}),
            updated_at: zod.string().datetime({}),
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
                uuid: zod.string(),
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
                email: zod.string().email().max(messagingTemplatesListResponseResultsItemCreatedByOneEmailMax),
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
            message_category: zod.string().nullish(),
            deleted: zod.boolean().optional(),
        })
    ),
})

export const MessagingTemplatesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const messagingTemplatesCreateBodyNameMax = 400

export const messagingTemplatesCreateBodyTypeMax = 24

export const MessagingTemplatesCreateBody = zod.object({
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
    message_category: zod.string().nullish(),
    deleted: zod.boolean().optional(),
})
