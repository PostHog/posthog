/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 29 ops
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
            id: zod.string().optional(),
            key: zod.string().max(messagingCategoriesListResponseResultsItemKeyMax),
            name: zod.string().max(messagingCategoriesListResponseResultsItemNameMax),
            description: zod.string().optional(),
            public_description: zod.string().optional(),
            category_type: zod
                .enum(['marketing', 'transactional'])
                .optional()
                .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
            created_at: zod.string().datetime({}).optional(),
            updated_at: zod.string().datetime({}).optional(),
            created_by: zod.number().nullish(),
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
    id: zod.string().optional(),
    key: zod.string().max(messagingCategoriesImportFromCustomerioCreateResponseKeyMax),
    name: zod.string().max(messagingCategoriesImportFromCustomerioCreateResponseNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
    created_at: zod.string().datetime({}).optional(),
    updated_at: zod.string().datetime({}).optional(),
    created_by: zod.number().nullish(),
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
    id: zod.string().optional(),
    key: zod.string().max(messagingCategoriesImportPreferencesCsvCreateResponseKeyMax),
    name: zod.string().max(messagingCategoriesImportPreferencesCsvCreateResponseNameMax),
    description: zod.string().optional(),
    public_description: zod.string().optional(),
    category_type: zod
        .enum(['marketing', 'transactional'])
        .optional()
        .describe('* `marketing` - Marketing\n* `transactional` - Transactional'),
    created_at: zod.string().datetime({}).optional(),
    updated_at: zod.string().datetime({}).optional(),
    created_by: zod.number().nullish(),
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
            id: zod.string().optional(),
            name: zod.string().max(messagingTemplatesListResponseResultsItemNameMax),
            description: zod.string().optional(),
            created_at: zod.string().datetime({}).optional(),
            updated_at: zod.string().datetime({}).optional(),
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
            created_by: zod
                .object({
                    id: zod.number().optional(),
                    uuid: zod.string().optional(),
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
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
                })
                .optional(),
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

/**
 * Override list to include global templates from files alongside team templates from DB.
 */
export const HogFlowTemplatesListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowTemplatesListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const hogFlowTemplatesListResponseResultsItemNameMax = 400

export const hogFlowTemplatesListResponseResultsItemImageUrlMax = 8201

export const hogFlowTemplatesListResponseResultsItemTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesListResponseResultsItemTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesListResponseResultsItemActionsItemNameMax = 400

export const hogFlowTemplatesListResponseResultsItemActionsItemDescriptionDefault = ``
export const hogFlowTemplatesListResponseResultsItemActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesListResponseResultsItemActionsItemTypeMax = 100

export const hogFlowTemplatesListResponseResultsItemAbortActionMax = 400

export const HogFlowTemplatesListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.string().optional(),
                name: zod.string().max(hogFlowTemplatesListResponseResultsItemNameMax),
                description: zod.string().optional(),
                image_url: zod.string().max(hogFlowTemplatesListResponseResultsItemImageUrlMax).nullish(),
                tags: zod.array(zod.string()).optional(),
                scope: zod
                    .enum(['team', 'organization', 'global'])
                    .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
                created_at: zod.string().datetime({}).optional(),
                created_by: zod.string().optional(),
                updated_at: zod.string().datetime({}).optional(),
                trigger: zod.unknown().optional(),
                trigger_masking: zod
                    .object({
                        ttl: zod
                            .number()
                            .min(hogFlowTemplatesListResponseResultsItemTriggerMaskingOneTtlMin)
                            .max(hogFlowTemplatesListResponseResultsItemTriggerMaskingOneTtlMax)
                            .nullish(),
                        threshold: zod.number().nullish(),
                        hash: zod.string(),
                        bytecode: zod.unknown().nullish(),
                    })
                    .nullish(),
                conversion: zod.unknown().nullish(),
                exit_condition: zod
                    .enum([
                        'exit_on_conversion',
                        'exit_on_trigger_not_matched',
                        'exit_on_trigger_not_matched_or_conversion',
                        'exit_only_at_end',
                    ])
                    .optional()
                    .describe(
                        '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
                    ),
                edges: zod.unknown().optional(),
                actions: zod.array(
                    zod
                        .object({
                            id: zod.string(),
                            name: zod.string().max(hogFlowTemplatesListResponseResultsItemActionsItemNameMax),
                            description: zod
                                .string()
                                .default(hogFlowTemplatesListResponseResultsItemActionsItemDescriptionDefault),
                            on_error: zod
                                .union([
                                    zod
                                        .enum(['continue', 'abort', 'complete', 'branch'])
                                        .describe(
                                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                                        ),
                                    zod.literal(null),
                                ])
                                .nullish(),
                            created_at: zod.number().optional(),
                            updated_at: zod.number().optional(),
                            filters: zod
                                .object({
                                    source: zod
                                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                                        .describe(
                                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                        )
                                        .default(
                                            hogFlowTemplatesListResponseResultsItemActionsItemFiltersOneSourceDefault
                                        ),
                                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                    bytecode: zod.unknown().nullish(),
                                    transpiled: zod.unknown().optional(),
                                    filter_test_accounts: zod.boolean().optional(),
                                    bytecode_error: zod.string().optional(),
                                })
                                .nullish(),
                            type: zod.string().max(hogFlowTemplatesListResponseResultsItemActionsItemTypeMax),
                            config: zod.unknown(),
                            output_variable: zod.unknown().nullish(),
                        })
                        .describe(
                            'Custom action serializer for templates that skips input validation\n(since templates should have default/empty values).'
                        )
                ),
                abort_action: zod.string().max(hogFlowTemplatesListResponseResultsItemAbortActionMax).nullish(),
                variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
            })
            .describe(
                'Serializer for creating hog flow templates.\nValidates and sanitizes the workflow before creating it as a template.'
            )
    ),
})

export const HogFlowTemplatesCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowTemplatesCreateBodyNameMax = 400

export const hogFlowTemplatesCreateBodyImageUrlMax = 8201

export const hogFlowTemplatesCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesCreateBodyActionsItemNameMax = 400

export const hogFlowTemplatesCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowTemplatesCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesCreateBodyActionsItemTypeMax = 100

export const hogFlowTemplatesCreateBodyAbortActionMax = 400

export const HogFlowTemplatesCreateBody = zod
    .object({
        name: zod.string().max(hogFlowTemplatesCreateBodyNameMax),
        description: zod.string().optional(),
        image_url: zod.string().max(hogFlowTemplatesCreateBodyImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: zod
            .enum(['team', 'organization', 'global'])
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesCreateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesCreateBodyTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().nullish(),
            })
            .nullish(),
        conversion: zod.unknown().nullish(),
        exit_condition: zod
            .enum([
                'exit_on_conversion',
                'exit_on_trigger_not_matched',
                'exit_on_trigger_not_matched_or_conversion',
                'exit_only_at_end',
            ])
            .optional()
            .describe(
                '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
            ),
        edges: zod.unknown().optional(),
        actions: zod.array(
            zod
                .object({
                    id: zod.string(),
                    name: zod.string().max(hogFlowTemplatesCreateBodyActionsItemNameMax),
                    description: zod.string().default(hogFlowTemplatesCreateBodyActionsItemDescriptionDefault),
                    on_error: zod
                        .union([
                            zod
                                .enum(['continue', 'abort', 'complete', 'branch'])
                                .describe(
                                    '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                                ),
                            zod.literal(null),
                        ])
                        .nullish(),
                    created_at: zod.number().optional(),
                    updated_at: zod.number().optional(),
                    filters: zod
                        .object({
                            source: zod
                                .enum(['events', 'person-updates', 'data-warehouse-table'])
                                .describe(
                                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                )
                                .default(hogFlowTemplatesCreateBodyActionsItemFiltersOneSourceDefault),
                            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            bytecode: zod.unknown().nullish(),
                            transpiled: zod.unknown().optional(),
                            filter_test_accounts: zod.boolean().optional(),
                            bytecode_error: zod.string().optional(),
                        })
                        .nullish(),
                    type: zod.string().max(hogFlowTemplatesCreateBodyActionsItemTypeMax),
                    config: zod.unknown(),
                    output_variable: zod.unknown().nullish(),
                })
                .describe(
                    'Custom action serializer for templates that skips input validation\n(since templates should have default/empty values).'
                )
        ),
        abort_action: zod.string().max(hogFlowTemplatesCreateBodyAbortActionMax).nullish(),
        variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    })
    .describe(
        'Serializer for creating hog flow templates.\nValidates and sanitizes the workflow before creating it as a template.'
    )

/**
 * Check file-based global templates first, then DB team templates.
The queryset excludes all global templates from DB, so this only returns team templates from DB.
 */
export const HogFlowTemplatesRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowTemplatesRetrieveResponseNameMax = 400

export const hogFlowTemplatesRetrieveResponseImageUrlMax = 8201

export const hogFlowTemplatesRetrieveResponseTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesRetrieveResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesRetrieveResponseActionsItemNameMax = 400

export const hogFlowTemplatesRetrieveResponseActionsItemDescriptionDefault = ``
export const hogFlowTemplatesRetrieveResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesRetrieveResponseActionsItemTypeMax = 100

export const hogFlowTemplatesRetrieveResponseAbortActionMax = 400

export const HogFlowTemplatesRetrieveResponse = zod
    .object({
        id: zod.string().optional(),
        name: zod.string().max(hogFlowTemplatesRetrieveResponseNameMax),
        description: zod.string().optional(),
        image_url: zod.string().max(hogFlowTemplatesRetrieveResponseImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: zod
            .enum(['team', 'organization', 'global'])
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        created_at: zod.string().datetime({}).optional(),
        created_by: zod.string().optional(),
        updated_at: zod.string().datetime({}).optional(),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesRetrieveResponseTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesRetrieveResponseTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().nullish(),
            })
            .nullish(),
        conversion: zod.unknown().nullish(),
        exit_condition: zod
            .enum([
                'exit_on_conversion',
                'exit_on_trigger_not_matched',
                'exit_on_trigger_not_matched_or_conversion',
                'exit_only_at_end',
            ])
            .optional()
            .describe(
                '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
            ),
        edges: zod.unknown().optional(),
        actions: zod.array(
            zod
                .object({
                    id: zod.string(),
                    name: zod.string().max(hogFlowTemplatesRetrieveResponseActionsItemNameMax),
                    description: zod.string().default(hogFlowTemplatesRetrieveResponseActionsItemDescriptionDefault),
                    on_error: zod
                        .union([
                            zod
                                .enum(['continue', 'abort', 'complete', 'branch'])
                                .describe(
                                    '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                                ),
                            zod.literal(null),
                        ])
                        .nullish(),
                    created_at: zod.number().optional(),
                    updated_at: zod.number().optional(),
                    filters: zod
                        .object({
                            source: zod
                                .enum(['events', 'person-updates', 'data-warehouse-table'])
                                .describe(
                                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                )
                                .default(hogFlowTemplatesRetrieveResponseActionsItemFiltersOneSourceDefault),
                            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            bytecode: zod.unknown().nullish(),
                            transpiled: zod.unknown().optional(),
                            filter_test_accounts: zod.boolean().optional(),
                            bytecode_error: zod.string().optional(),
                        })
                        .nullish(),
                    type: zod.string().max(hogFlowTemplatesRetrieveResponseActionsItemTypeMax),
                    config: zod.unknown(),
                    output_variable: zod.unknown().nullish(),
                })
                .describe(
                    'Custom action serializer for templates that skips input validation\n(since templates should have default/empty values).'
                )
        ),
        abort_action: zod.string().max(hogFlowTemplatesRetrieveResponseAbortActionMax).nullish(),
        variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    })
    .describe(
        'Serializer for creating hog flow templates.\nValidates and sanitizes the workflow before creating it as a template.'
    )

export const HogFlowTemplatesUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowTemplatesUpdateBodyNameMax = 400

export const hogFlowTemplatesUpdateBodyImageUrlMax = 8201

export const hogFlowTemplatesUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesUpdateBodyActionsItemNameMax = 400

export const hogFlowTemplatesUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowTemplatesUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesUpdateBodyActionsItemTypeMax = 100

export const hogFlowTemplatesUpdateBodyAbortActionMax = 400

export const HogFlowTemplatesUpdateBody = zod
    .object({
        name: zod.string().max(hogFlowTemplatesUpdateBodyNameMax),
        description: zod.string().optional(),
        image_url: zod.string().max(hogFlowTemplatesUpdateBodyImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: zod
            .enum(['team', 'organization', 'global'])
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesUpdateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesUpdateBodyTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().nullish(),
            })
            .nullish(),
        conversion: zod.unknown().nullish(),
        exit_condition: zod
            .enum([
                'exit_on_conversion',
                'exit_on_trigger_not_matched',
                'exit_on_trigger_not_matched_or_conversion',
                'exit_only_at_end',
            ])
            .optional()
            .describe(
                '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
            ),
        edges: zod.unknown().optional(),
        actions: zod.array(
            zod
                .object({
                    id: zod.string(),
                    name: zod.string().max(hogFlowTemplatesUpdateBodyActionsItemNameMax),
                    description: zod.string().default(hogFlowTemplatesUpdateBodyActionsItemDescriptionDefault),
                    on_error: zod
                        .union([
                            zod
                                .enum(['continue', 'abort', 'complete', 'branch'])
                                .describe(
                                    '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                                ),
                            zod.literal(null),
                        ])
                        .nullish(),
                    created_at: zod.number().optional(),
                    updated_at: zod.number().optional(),
                    filters: zod
                        .object({
                            source: zod
                                .enum(['events', 'person-updates', 'data-warehouse-table'])
                                .describe(
                                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                )
                                .default(hogFlowTemplatesUpdateBodyActionsItemFiltersOneSourceDefault),
                            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            bytecode: zod.unknown().nullish(),
                            transpiled: zod.unknown().optional(),
                            filter_test_accounts: zod.boolean().optional(),
                            bytecode_error: zod.string().optional(),
                        })
                        .nullish(),
                    type: zod.string().max(hogFlowTemplatesUpdateBodyActionsItemTypeMax),
                    config: zod.unknown(),
                    output_variable: zod.unknown().nullish(),
                })
                .describe(
                    'Custom action serializer for templates that skips input validation\n(since templates should have default/empty values).'
                )
        ),
        abort_action: zod.string().max(hogFlowTemplatesUpdateBodyAbortActionMax).nullish(),
        variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    })
    .describe(
        'Serializer for creating hog flow templates.\nValidates and sanitizes the workflow before creating it as a template.'
    )

export const hogFlowTemplatesUpdateResponseNameMax = 400

export const hogFlowTemplatesUpdateResponseImageUrlMax = 8201

export const hogFlowTemplatesUpdateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesUpdateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesUpdateResponseActionsItemNameMax = 400

export const hogFlowTemplatesUpdateResponseActionsItemDescriptionDefault = ``
export const hogFlowTemplatesUpdateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesUpdateResponseActionsItemTypeMax = 100

export const hogFlowTemplatesUpdateResponseAbortActionMax = 400

export const HogFlowTemplatesUpdateResponse = zod
    .object({
        id: zod.string().optional(),
        name: zod.string().max(hogFlowTemplatesUpdateResponseNameMax),
        description: zod.string().optional(),
        image_url: zod.string().max(hogFlowTemplatesUpdateResponseImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: zod
            .enum(['team', 'organization', 'global'])
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        created_at: zod.string().datetime({}).optional(),
        created_by: zod.string().optional(),
        updated_at: zod.string().datetime({}).optional(),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesUpdateResponseTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesUpdateResponseTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().nullish(),
            })
            .nullish(),
        conversion: zod.unknown().nullish(),
        exit_condition: zod
            .enum([
                'exit_on_conversion',
                'exit_on_trigger_not_matched',
                'exit_on_trigger_not_matched_or_conversion',
                'exit_only_at_end',
            ])
            .optional()
            .describe(
                '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
            ),
        edges: zod.unknown().optional(),
        actions: zod.array(
            zod
                .object({
                    id: zod.string(),
                    name: zod.string().max(hogFlowTemplatesUpdateResponseActionsItemNameMax),
                    description: zod.string().default(hogFlowTemplatesUpdateResponseActionsItemDescriptionDefault),
                    on_error: zod
                        .union([
                            zod
                                .enum(['continue', 'abort', 'complete', 'branch'])
                                .describe(
                                    '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                                ),
                            zod.literal(null),
                        ])
                        .nullish(),
                    created_at: zod.number().optional(),
                    updated_at: zod.number().optional(),
                    filters: zod
                        .object({
                            source: zod
                                .enum(['events', 'person-updates', 'data-warehouse-table'])
                                .describe(
                                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                )
                                .default(hogFlowTemplatesUpdateResponseActionsItemFiltersOneSourceDefault),
                            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            bytecode: zod.unknown().nullish(),
                            transpiled: zod.unknown().optional(),
                            filter_test_accounts: zod.boolean().optional(),
                            bytecode_error: zod.string().optional(),
                        })
                        .nullish(),
                    type: zod.string().max(hogFlowTemplatesUpdateResponseActionsItemTypeMax),
                    config: zod.unknown(),
                    output_variable: zod.unknown().nullish(),
                })
                .describe(
                    'Custom action serializer for templates that skips input validation\n(since templates should have default/empty values).'
                )
        ),
        abort_action: zod.string().max(hogFlowTemplatesUpdateResponseAbortActionMax).nullish(),
        variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    })
    .describe(
        'Serializer for creating hog flow templates.\nValidates and sanitizes the workflow before creating it as a template.'
    )

export const HogFlowTemplatesPartialUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowTemplatesPartialUpdateBodyNameMax = 400

export const hogFlowTemplatesPartialUpdateBodyImageUrlMax = 8201

export const hogFlowTemplatesPartialUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesPartialUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesPartialUpdateBodyActionsItemNameMax = 400

export const hogFlowTemplatesPartialUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowTemplatesPartialUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesPartialUpdateBodyActionsItemTypeMax = 100

export const hogFlowTemplatesPartialUpdateBodyAbortActionMax = 400

export const HogFlowTemplatesPartialUpdateBody = zod
    .object({
        name: zod.string().max(hogFlowTemplatesPartialUpdateBodyNameMax).optional(),
        description: zod.string().optional(),
        image_url: zod.string().max(hogFlowTemplatesPartialUpdateBodyImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: zod
            .enum(['team', 'organization', 'global'])
            .optional()
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesPartialUpdateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesPartialUpdateBodyTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().nullish(),
            })
            .nullish(),
        conversion: zod.unknown().nullish(),
        exit_condition: zod
            .enum([
                'exit_on_conversion',
                'exit_on_trigger_not_matched',
                'exit_on_trigger_not_matched_or_conversion',
                'exit_only_at_end',
            ])
            .optional()
            .describe(
                '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
            ),
        edges: zod.unknown().optional(),
        actions: zod
            .array(
                zod
                    .object({
                        id: zod.string(),
                        name: zod.string().max(hogFlowTemplatesPartialUpdateBodyActionsItemNameMax),
                        description: zod
                            .string()
                            .default(hogFlowTemplatesPartialUpdateBodyActionsItemDescriptionDefault),
                        on_error: zod
                            .union([
                                zod
                                    .enum(['continue', 'abort', 'complete', 'branch'])
                                    .describe(
                                        '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                                    ),
                                zod.literal(null),
                            ])
                            .nullish(),
                        created_at: zod.number().optional(),
                        updated_at: zod.number().optional(),
                        filters: zod
                            .object({
                                source: zod
                                    .enum(['events', 'person-updates', 'data-warehouse-table'])
                                    .describe(
                                        '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                    )
                                    .default(hogFlowTemplatesPartialUpdateBodyActionsItemFiltersOneSourceDefault),
                                actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                bytecode: zod.unknown().nullish(),
                                transpiled: zod.unknown().optional(),
                                filter_test_accounts: zod.boolean().optional(),
                                bytecode_error: zod.string().optional(),
                            })
                            .nullish(),
                        type: zod.string().max(hogFlowTemplatesPartialUpdateBodyActionsItemTypeMax),
                        config: zod.unknown(),
                        output_variable: zod.unknown().nullish(),
                    })
                    .describe(
                        'Custom action serializer for templates that skips input validation\n(since templates should have default/empty values).'
                    )
            )
            .optional(),
        abort_action: zod.string().max(hogFlowTemplatesPartialUpdateBodyAbortActionMax).nullish(),
        variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    })
    .describe(
        'Serializer for creating hog flow templates.\nValidates and sanitizes the workflow before creating it as a template.'
    )

export const hogFlowTemplatesPartialUpdateResponseNameMax = 400

export const hogFlowTemplatesPartialUpdateResponseImageUrlMax = 8201

export const hogFlowTemplatesPartialUpdateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesPartialUpdateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesPartialUpdateResponseActionsItemNameMax = 400

export const hogFlowTemplatesPartialUpdateResponseActionsItemDescriptionDefault = ``
export const hogFlowTemplatesPartialUpdateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesPartialUpdateResponseActionsItemTypeMax = 100

export const hogFlowTemplatesPartialUpdateResponseAbortActionMax = 400

export const HogFlowTemplatesPartialUpdateResponse = zod
    .object({
        id: zod.string().optional(),
        name: zod.string().max(hogFlowTemplatesPartialUpdateResponseNameMax),
        description: zod.string().optional(),
        image_url: zod.string().max(hogFlowTemplatesPartialUpdateResponseImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: zod
            .enum(['team', 'organization', 'global'])
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        created_at: zod.string().datetime({}).optional(),
        created_by: zod.string().optional(),
        updated_at: zod.string().datetime({}).optional(),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesPartialUpdateResponseTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesPartialUpdateResponseTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().nullish(),
            })
            .nullish(),
        conversion: zod.unknown().nullish(),
        exit_condition: zod
            .enum([
                'exit_on_conversion',
                'exit_on_trigger_not_matched',
                'exit_on_trigger_not_matched_or_conversion',
                'exit_only_at_end',
            ])
            .optional()
            .describe(
                '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
            ),
        edges: zod.unknown().optional(),
        actions: zod.array(
            zod
                .object({
                    id: zod.string(),
                    name: zod.string().max(hogFlowTemplatesPartialUpdateResponseActionsItemNameMax),
                    description: zod
                        .string()
                        .default(hogFlowTemplatesPartialUpdateResponseActionsItemDescriptionDefault),
                    on_error: zod
                        .union([
                            zod
                                .enum(['continue', 'abort', 'complete', 'branch'])
                                .describe(
                                    '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                                ),
                            zod.literal(null),
                        ])
                        .nullish(),
                    created_at: zod.number().optional(),
                    updated_at: zod.number().optional(),
                    filters: zod
                        .object({
                            source: zod
                                .enum(['events', 'person-updates', 'data-warehouse-table'])
                                .describe(
                                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                )
                                .default(hogFlowTemplatesPartialUpdateResponseActionsItemFiltersOneSourceDefault),
                            actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                            bytecode: zod.unknown().nullish(),
                            transpiled: zod.unknown().optional(),
                            filter_test_accounts: zod.boolean().optional(),
                            bytecode_error: zod.string().optional(),
                        })
                        .nullish(),
                    type: zod.string().max(hogFlowTemplatesPartialUpdateResponseActionsItemTypeMax),
                    config: zod.unknown(),
                    output_variable: zod.unknown().nullish(),
                })
                .describe(
                    'Custom action serializer for templates that skips input validation\n(since templates should have default/empty values).'
                )
        ),
        abort_action: zod.string().max(hogFlowTemplatesPartialUpdateResponseAbortActionMax).nullish(),
        variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    })
    .describe(
        'Serializer for creating hog flow templates.\nValidates and sanitizes the workflow before creating it as a template.'
    )

export const HogFlowTemplatesDestroyParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowTemplatesLogsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow template.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowsListQueryParams = zod.object({
    created_at: zod.string().datetime({}).optional(),
    created_by: zod.number().optional(),
    id: zod.string().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    updated_at: zod.string().datetime({}).optional(),
})

export const hogFlowsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const hogFlowsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const hogFlowsListResponseResultsItemCreatedByOneLastNameMax = 150

export const hogFlowsListResponseResultsItemCreatedByOneEmailMax = 254

export const HogFlowsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().optional(),
            name: zod.string().nullish(),
            description: zod.string().optional(),
            version: zod.number().optional(),
            status: zod
                .enum(['draft', 'active', 'archived'])
                .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived')
                .optional(),
            created_at: zod.string().datetime({}).optional(),
            created_by: zod
                .object({
                    id: zod.number().optional(),
                    uuid: zod.string().optional(),
                    distinct_id: zod.string().max(hogFlowsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                    first_name: zod.string().max(hogFlowsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                    last_name: zod.string().max(hogFlowsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                    email: zod.string().email().max(hogFlowsListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
                })
                .optional(),
            updated_at: zod.string().datetime({}).optional(),
            trigger: zod.unknown().optional(),
            trigger_masking: zod.unknown().nullish(),
            conversion: zod.unknown().nullish(),
            exit_condition: zod
                .enum([
                    'exit_on_conversion',
                    'exit_on_trigger_not_matched',
                    'exit_on_trigger_not_matched_or_conversion',
                    'exit_only_at_end',
                ])
                .describe(
                    '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
                )
                .optional(),
            edges: zod.unknown().optional(),
            actions: zod.unknown().optional(),
            abort_action: zod.string().nullish(),
            variables: zod.unknown().nullish(),
            billable_action_types: zod.unknown().nullish(),
        })
    ),
})

export const HogFlowsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsCreateBodyNameMax = 400

export const hogFlowsCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsCreateBodyActionsItemNameMax = 400

export const hogFlowsCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsCreateBodyActionsItemTypeMax = 100

export const HogFlowsCreateBody = zod.object({
    name: zod.string().max(hogFlowsCreateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsCreateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsCreateBodyActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsCreateBodyActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const HogFlowsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsRetrieveResponseNameMax = 400

export const hogFlowsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsRetrieveResponseCreatedByOneFirstNameMax = 150

export const hogFlowsRetrieveResponseCreatedByOneLastNameMax = 150

export const hogFlowsRetrieveResponseCreatedByOneEmailMax = 254

export const hogFlowsRetrieveResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsRetrieveResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsRetrieveResponseActionsItemNameMax = 400

export const hogFlowsRetrieveResponseActionsItemDescriptionDefault = ``
export const hogFlowsRetrieveResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsRetrieveResponseActionsItemTypeMax = 100

export const HogFlowsRetrieveResponse = zod.object({
    id: zod.string().optional(),
    name: zod.string().max(hogFlowsRetrieveResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(hogFlowsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(hogFlowsRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(hogFlowsRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(hogFlowsRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
        })
        .optional(),
    updated_at: zod.string().datetime({}).optional(),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsRetrieveResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsRetrieveResponseTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsRetrieveResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsRetrieveResponseActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsRetrieveResponseActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsRetrieveResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullish(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullish(),
})

export const HogFlowsUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsUpdateBodyNameMax = 400

export const hogFlowsUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsUpdateBodyActionsItemNameMax = 400

export const hogFlowsUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowsUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsUpdateBodyActionsItemTypeMax = 100

export const HogFlowsUpdateBody = zod.object({
    name: zod.string().max(hogFlowsUpdateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsUpdateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsUpdateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsUpdateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsUpdateBodyActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsUpdateBodyActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsUpdateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const hogFlowsUpdateResponseNameMax = 400

export const hogFlowsUpdateResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsUpdateResponseCreatedByOneFirstNameMax = 150

export const hogFlowsUpdateResponseCreatedByOneLastNameMax = 150

export const hogFlowsUpdateResponseCreatedByOneEmailMax = 254

export const hogFlowsUpdateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsUpdateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsUpdateResponseActionsItemNameMax = 400

export const hogFlowsUpdateResponseActionsItemDescriptionDefault = ``
export const hogFlowsUpdateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsUpdateResponseActionsItemTypeMax = 100

export const HogFlowsUpdateResponse = zod.object({
    id: zod.string().optional(),
    name: zod.string().max(hogFlowsUpdateResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(hogFlowsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(hogFlowsUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(hogFlowsUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(hogFlowsUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
        })
        .optional(),
    updated_at: zod.string().datetime({}).optional(),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsUpdateResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsUpdateResponseTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsUpdateResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsUpdateResponseActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsUpdateResponseActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsUpdateResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullish(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullish(),
})

export const HogFlowsPartialUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsPartialUpdateBodyNameMax = 400

export const hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsPartialUpdateBodyActionsItemNameMax = 400

export const hogFlowsPartialUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowsPartialUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsPartialUpdateBodyActionsItemTypeMax = 100

export const HogFlowsPartialUpdateBody = zod.object({
    name: zod.string().max(hogFlowsPartialUpdateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod
        .array(
            zod.object({
                id: zod.string(),
                name: zod.string().max(hogFlowsPartialUpdateBodyActionsItemNameMax),
                description: zod.string().default(hogFlowsPartialUpdateBodyActionsItemDescriptionDefault),
                on_error: zod
                    .union([
                        zod
                            .enum(['continue', 'abort', 'complete', 'branch'])
                            .describe(
                                '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                            ),
                        zod.literal(null),
                    ])
                    .nullish(),
                created_at: zod.number().optional(),
                updated_at: zod.number().optional(),
                filters: zod
                    .object({
                        source: zod
                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                            .describe(
                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                            )
                            .default(hogFlowsPartialUpdateBodyActionsItemFiltersOneSourceDefault),
                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                        bytecode: zod.unknown().nullish(),
                        transpiled: zod.unknown().optional(),
                        filter_test_accounts: zod.boolean().optional(),
                        bytecode_error: zod.string().optional(),
                    })
                    .nullish(),
                type: zod.string().max(hogFlowsPartialUpdateBodyActionsItemTypeMax),
                config: zod.unknown(),
                output_variable: zod.unknown().nullish(),
            })
        )
        .optional(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const hogFlowsPartialUpdateResponseNameMax = 400

export const hogFlowsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const hogFlowsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const hogFlowsPartialUpdateResponseCreatedByOneEmailMax = 254

export const hogFlowsPartialUpdateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsPartialUpdateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsPartialUpdateResponseActionsItemNameMax = 400

export const hogFlowsPartialUpdateResponseActionsItemDescriptionDefault = ``
export const hogFlowsPartialUpdateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsPartialUpdateResponseActionsItemTypeMax = 100

export const HogFlowsPartialUpdateResponse = zod.object({
    id: zod.string().optional(),
    name: zod.string().max(hogFlowsPartialUpdateResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(hogFlowsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(hogFlowsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(hogFlowsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(hogFlowsPartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
        })
        .optional(),
    updated_at: zod.string().datetime({}).optional(),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsPartialUpdateResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsPartialUpdateResponseTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsPartialUpdateResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsPartialUpdateResponseActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsPartialUpdateResponseActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsPartialUpdateResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullish(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullish(),
})

export const HogFlowsDestroyParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowsBatchJobsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsBatchJobsRetrieveResponseNameMax = 400

export const hogFlowsBatchJobsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsBatchJobsRetrieveResponseCreatedByOneFirstNameMax = 150

export const hogFlowsBatchJobsRetrieveResponseCreatedByOneLastNameMax = 150

export const hogFlowsBatchJobsRetrieveResponseCreatedByOneEmailMax = 254

export const hogFlowsBatchJobsRetrieveResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsBatchJobsRetrieveResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsBatchJobsRetrieveResponseActionsItemNameMax = 400

export const hogFlowsBatchJobsRetrieveResponseActionsItemDescriptionDefault = ``
export const hogFlowsBatchJobsRetrieveResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsBatchJobsRetrieveResponseActionsItemTypeMax = 100

export const HogFlowsBatchJobsRetrieveResponse = zod.object({
    id: zod.string().optional(),
    name: zod.string().max(hogFlowsBatchJobsRetrieveResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(hogFlowsBatchJobsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(hogFlowsBatchJobsRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(hogFlowsBatchJobsRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(hogFlowsBatchJobsRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
        })
        .optional(),
    updated_at: zod.string().datetime({}).optional(),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsBatchJobsRetrieveResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsBatchJobsRetrieveResponseTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsBatchJobsRetrieveResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsBatchJobsRetrieveResponseActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsBatchJobsRetrieveResponseActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsBatchJobsRetrieveResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullish(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullish(),
})

export const HogFlowsBatchJobsCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsBatchJobsCreateBodyNameMax = 400

export const hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsBatchJobsCreateBodyActionsItemNameMax = 400

export const hogFlowsBatchJobsCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsBatchJobsCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsBatchJobsCreateBodyActionsItemTypeMax = 100

export const HogFlowsBatchJobsCreateBody = zod.object({
    name: zod.string().max(hogFlowsBatchJobsCreateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsBatchJobsCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsBatchJobsCreateBodyActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsBatchJobsCreateBodyActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsBatchJobsCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const hogFlowsBatchJobsCreateResponseNameMax = 400

export const hogFlowsBatchJobsCreateResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsBatchJobsCreateResponseCreatedByOneFirstNameMax = 150

export const hogFlowsBatchJobsCreateResponseCreatedByOneLastNameMax = 150

export const hogFlowsBatchJobsCreateResponseCreatedByOneEmailMax = 254

export const hogFlowsBatchJobsCreateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsBatchJobsCreateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsBatchJobsCreateResponseActionsItemNameMax = 400

export const hogFlowsBatchJobsCreateResponseActionsItemDescriptionDefault = ``
export const hogFlowsBatchJobsCreateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsBatchJobsCreateResponseActionsItemTypeMax = 100

export const HogFlowsBatchJobsCreateResponse = zod.object({
    id: zod.string().optional(),
    name: zod.string().max(hogFlowsBatchJobsCreateResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(hogFlowsBatchJobsCreateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(hogFlowsBatchJobsCreateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(hogFlowsBatchJobsCreateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(hogFlowsBatchJobsCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
        })
        .optional(),
    updated_at: zod.string().datetime({}).optional(),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsBatchJobsCreateResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsBatchJobsCreateResponseTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsBatchJobsCreateResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsBatchJobsCreateResponseActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsBatchJobsCreateResponseActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsBatchJobsCreateResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullish(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullish(),
})

export const HogFlowsInvocationsCreateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsInvocationsCreateBodyNameMax = 400

export const hogFlowsInvocationsCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsInvocationsCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsInvocationsCreateBodyActionsItemNameMax = 400

export const hogFlowsInvocationsCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsInvocationsCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsInvocationsCreateBodyActionsItemTypeMax = 100

export const HogFlowsInvocationsCreateBody = zod.object({
    name: zod.string().max(hogFlowsInvocationsCreateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsInvocationsCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsInvocationsCreateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsInvocationsCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsInvocationsCreateBodyActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsInvocationsCreateBodyActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsInvocationsCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const hogFlowsInvocationsCreateResponseNameMax = 400

export const hogFlowsInvocationsCreateResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsInvocationsCreateResponseCreatedByOneFirstNameMax = 150

export const hogFlowsInvocationsCreateResponseCreatedByOneLastNameMax = 150

export const hogFlowsInvocationsCreateResponseCreatedByOneEmailMax = 254

export const hogFlowsInvocationsCreateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsInvocationsCreateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsInvocationsCreateResponseActionsItemNameMax = 400

export const hogFlowsInvocationsCreateResponseActionsItemDescriptionDefault = ``
export const hogFlowsInvocationsCreateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsInvocationsCreateResponseActionsItemTypeMax = 100

export const HogFlowsInvocationsCreateResponse = zod.object({
    id: zod.string().optional(),
    name: zod.string().max(hogFlowsInvocationsCreateResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(hogFlowsInvocationsCreateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(hogFlowsInvocationsCreateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(hogFlowsInvocationsCreateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(hogFlowsInvocationsCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
        })
        .optional(),
    updated_at: zod.string().datetime({}).optional(),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsInvocationsCreateResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsInvocationsCreateResponseTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsInvocationsCreateResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsInvocationsCreateResponseActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsInvocationsCreateResponseActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsInvocationsCreateResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullish(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullish(),
})

export const HogFlowsLogsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowsMetricsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowsMetricsTotalsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowsBulkDeleteCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsBulkDeleteCreateBodyNameMax = 400

export const hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsBulkDeleteCreateBodyActionsItemNameMax = 400

export const hogFlowsBulkDeleteCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsBulkDeleteCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsBulkDeleteCreateBodyActionsItemTypeMax = 100

export const HogFlowsBulkDeleteCreateBody = zod.object({
    name: zod.string().max(hogFlowsBulkDeleteCreateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsBulkDeleteCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsBulkDeleteCreateBodyActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsBulkDeleteCreateBodyActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsBulkDeleteCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const hogFlowsBulkDeleteCreateResponseNameMax = 400

export const hogFlowsBulkDeleteCreateResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsBulkDeleteCreateResponseCreatedByOneFirstNameMax = 150

export const hogFlowsBulkDeleteCreateResponseCreatedByOneLastNameMax = 150

export const hogFlowsBulkDeleteCreateResponseCreatedByOneEmailMax = 254

export const hogFlowsBulkDeleteCreateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsBulkDeleteCreateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsBulkDeleteCreateResponseActionsItemNameMax = 400

export const hogFlowsBulkDeleteCreateResponseActionsItemDescriptionDefault = ``
export const hogFlowsBulkDeleteCreateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsBulkDeleteCreateResponseActionsItemTypeMax = 100

export const HogFlowsBulkDeleteCreateResponse = zod.object({
    id: zod.string().optional(),
    name: zod.string().max(hogFlowsBulkDeleteCreateResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(hogFlowsBulkDeleteCreateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(hogFlowsBulkDeleteCreateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(hogFlowsBulkDeleteCreateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(hogFlowsBulkDeleteCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
        })
        .optional(),
    updated_at: zod.string().datetime({}).optional(),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsBulkDeleteCreateResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsBulkDeleteCreateResponseTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsBulkDeleteCreateResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsBulkDeleteCreateResponseActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsBulkDeleteCreateResponseActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsBulkDeleteCreateResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullish(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullish(),
})

export const HogFlowsUserBlastRadiusCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsUserBlastRadiusCreateBodyNameMax = 400

export const hogFlowsUserBlastRadiusCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsUserBlastRadiusCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsUserBlastRadiusCreateBodyActionsItemNameMax = 400

export const hogFlowsUserBlastRadiusCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsUserBlastRadiusCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsUserBlastRadiusCreateBodyActionsItemTypeMax = 100

export const HogFlowsUserBlastRadiusCreateBody = zod.object({
    name: zod.string().max(hogFlowsUserBlastRadiusCreateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsUserBlastRadiusCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsUserBlastRadiusCreateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsUserBlastRadiusCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsUserBlastRadiusCreateBodyActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsUserBlastRadiusCreateBodyActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsUserBlastRadiusCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const hogFlowsUserBlastRadiusCreateResponseNameMax = 400

export const hogFlowsUserBlastRadiusCreateResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsUserBlastRadiusCreateResponseCreatedByOneFirstNameMax = 150

export const hogFlowsUserBlastRadiusCreateResponseCreatedByOneLastNameMax = 150

export const hogFlowsUserBlastRadiusCreateResponseCreatedByOneEmailMax = 254

export const hogFlowsUserBlastRadiusCreateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsUserBlastRadiusCreateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsUserBlastRadiusCreateResponseActionsItemNameMax = 400

export const hogFlowsUserBlastRadiusCreateResponseActionsItemDescriptionDefault = ``
export const hogFlowsUserBlastRadiusCreateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsUserBlastRadiusCreateResponseActionsItemTypeMax = 100

export const HogFlowsUserBlastRadiusCreateResponse = zod.object({
    id: zod.string().optional(),
    name: zod.string().max(hogFlowsUserBlastRadiusCreateResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.string().datetime({}).optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(hogFlowsUserBlastRadiusCreateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(hogFlowsUserBlastRadiusCreateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(hogFlowsUserBlastRadiusCreateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(hogFlowsUserBlastRadiusCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
        })
        .optional(),
    updated_at: zod.string().datetime({}).optional(),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsUserBlastRadiusCreateResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsUserBlastRadiusCreateResponseTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
        })
        .nullish(),
    conversion: zod.unknown().nullish(),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .optional()
        .describe(
            '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod.unknown().optional(),
    actions: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsUserBlastRadiusCreateResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsUserBlastRadiusCreateResponseActionsItemDescriptionDefault),
            on_error: zod
                .union([
                    zod
                        .enum(['continue', 'abort', 'complete', 'branch'])
                        .describe(
                            '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                        ),
                    zod.literal(null),
                ])
                .nullish(),
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
            filters: zod
                .object({
                    source: zod
                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                        .describe(
                            '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                        )
                        .default(hogFlowsUserBlastRadiusCreateResponseActionsItemFiltersOneSourceDefault),
                    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                    bytecode: zod.unknown().nullish(),
                    transpiled: zod.unknown().optional(),
                    filter_test_accounts: zod.boolean().optional(),
                    bytecode_error: zod.string().optional(),
                })
                .nullish(),
            type: zod.string().max(hogFlowsUserBlastRadiusCreateResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullish(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullish(),
})
