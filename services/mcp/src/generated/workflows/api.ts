/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 2 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

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
    id: zod.string().uuid().optional(),
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
            id: zod.string().uuid(),
            name: zod.string().nullable(),
            description: zod.string(),
            version: zod.number(),
            status: zod
                .enum(['draft', 'active', 'archived'])
                .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
            created_at: zod.string().datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.string().uuid(),
                distinct_id: zod.string().max(hogFlowsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(hogFlowsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(hogFlowsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(hogFlowsListResponseResultsItemCreatedByOneEmailMax),
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
            updated_at: zod.string().datetime({}),
            trigger: zod.unknown(),
            trigger_masking: zod.unknown().nullable(),
            conversion: zod.unknown().nullable(),
            exit_condition: zod
                .enum([
                    'exit_on_conversion',
                    'exit_on_trigger_not_matched',
                    'exit_on_trigger_not_matched_or_conversion',
                    'exit_only_at_end',
                ])
                .describe(
                    '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
                ),
            edges: zod.unknown(),
            actions: zod.unknown(),
            abort_action: zod.string().nullable(),
            variables: zod.unknown().nullable(),
            billable_action_types: zod.unknown().nullable(),
        })
    ),
})

export const HogFlowsRetrieveParams = zod.object({
    id: zod.string().uuid().describe('A UUID string identifying this hog flow.'),
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
    id: zod.string().uuid(),
    name: zod.string().max(hogFlowsRetrieveResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.string().datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.string().uuid(),
        distinct_id: zod.string().max(hogFlowsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFlowsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFlowsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.string().email().max(hogFlowsRetrieveResponseCreatedByOneEmailMax),
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
    updated_at: zod.string().datetime({}),
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
    abort_action: zod.string().nullable(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullable(),
})
