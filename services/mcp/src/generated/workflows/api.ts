/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Returns all workflows for the team, ordered by most recently updated. Use the HogQL hog_flows table for richer filtering and aggregation.
 * @summary List workflows
 */
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

export const hogFlowsListResponseResultsItemTriggerMaskingOneTtlMin = 60
export const hogFlowsListResponseResultsItemTriggerMaskingOneTtlMax = 94608000

export const hogFlowsListResponseResultsItemVariablesItemValueDefault = ``

export const HogFlowsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().nullable(),
            description: zod.string(),
            version: zod.number(),
            status: zod
                .enum(['draft', 'active', 'archived'])
                .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
            created_at: zod.string().datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.string(),
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
            trigger: zod.unknown().describe("Trigger configuration derived from the trigger action's config."),
            trigger_masking: zod
                .object({
                    ttl: zod
                        .number()
                        .min(hogFlowsListResponseResultsItemTriggerMaskingOneTtlMin)
                        .max(hogFlowsListResponseResultsItemTriggerMaskingOneTtlMax)
                        .nullish()
                        .describe(
                            'How long (in seconds) a masked person is remembered before they can re-enter the flow.'
                        ),
                    threshold: zod
                        .number()
                        .nullish()
                        .describe(
                            'Minimum number of persons that must accumulate before the flow proceeds, for k-anonymity.'
                        ),
                    hash: zod.string().describe('HogQL expression that determines the masking group identity.'),
                    bytecode: zod.unknown().nullish(),
                })
                .nullable()
                .describe('K-anonymity masking settings applied before the flow starts processing.'),
            conversion: zod
                .object({
                    window_minutes: zod
                        .number()
                        .nullish()
                        .describe('Time window in minutes within which a conversion is counted. Null means no limit.'),
                    filters: zod
                        .array(zod.record(zod.string(), zod.unknown()))
                        .nullish()
                        .describe('Array of PostHog property filter objects that define the conversion event.'),
                    bytecode: zod
                        .array(zod.unknown())
                        .nullish()
                        .describe('Compiled bytecode for the conversion filter. Auto-generated; do not set manually.'),
                })
                .nullish(),
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
            edges: zod
                .array(
                    zod.object({
                        from: zod.string().describe('ID of the source action node.'),
                        to: zod.string().describe('ID of the target action node.'),
                        type: zod.enum(['continue', 'branch']).describe('Edge type.'),
                        index: zod
                            .number()
                            .nullish()
                            .describe('Branch index (0-based) for ordered branching across multiple outgoing edges.'),
                    })
                )
                .optional(),
            actions: zod.unknown(),
            abort_action: zod
                .string()
                .nullable()
                .describe('ID of the action node to execute when the flow is aborted due to an error.'),
            variables: zod
                .array(
                    zod.object({
                        key: zod.string().describe('Variable name. Referenced in action configs as {variables.key}.'),
                        value: zod
                            .string()
                            .default(hogFlowsListResponseResultsItemVariablesItemValueDefault)
                            .describe('Default value for this variable.'),
                    })
                )
                .nullish(),
            billable_action_types: zod.unknown().nullable(),
        })
    ),
})

/**
 * Create a new workflow. The actions array must contain exactly one action with type='trigger'. All other actions define the flow steps; connect them via the edges array. The workflow is created in 'draft' status; set status='active' to activate it.
 * @summary Create a workflow
 */
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
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsCreateBodyTriggerMaskingOneTtlMax)
                .nullish()
                .describe('How long (in seconds) a masked person is remembered before they can re-enter the flow.'),
            threshold: zod
                .number()
                .nullish()
                .describe('Minimum number of persons that must accumulate before the flow proceeds, for k-anonymity.'),
            hash: zod.string().describe('HogQL expression that determines the masking group identity.'),
            bytecode: zod.unknown().nullish(),
        })
        .nullish()
        .describe('K-anonymity masking settings applied before the flow starts processing.'),
    conversion: zod
        .object({
            window_minutes: zod
                .number()
                .nullish()
                .describe('Time window in minutes within which a conversion is counted. Null means no limit.'),
            filters: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .nullish()
                .describe('Array of PostHog property filter objects that define the conversion event.'),
            bytecode: zod
                .array(zod.unknown())
                .nullish()
                .describe('Compiled bytecode for the conversion filter. Auto-generated; do not set manually.'),
        })
        .nullish(),
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
    edges: zod
        .array(
            zod.object({
                from: zod.string().describe('ID of the source action node.'),
                to: zod.string().describe('ID of the target action node.'),
                type: zod.enum(['continue', 'branch']).describe('Edge type.'),
                index: zod
                    .number()
                    .nullish()
                    .describe('Branch index (0-based) for ordered branching across multiple outgoing edges.'),
            })
        )
        .optional(),
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
            created_at: zod
                .number()
                .describe('Unix epoch timestamp (milliseconds) when this action was first added to the workflow.'),
            updated_at: zod
                .number()
                .describe('Unix epoch timestamp (milliseconds) when this action was last modified.'),
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
            config: zod
                .union([
                    zod.object({
                        type: zod.enum(['event']),
                        filters: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe('PostHog event and property filters.'),
                        filter_test_accounts: zod.boolean().optional(),
                    }),
                    zod.object({
                        type: zod.enum(['webhook', 'manual', 'schedule', 'tracking_pixel']),
                        template_id: zod.string().describe('HogFunction template ID.'),
                        inputs: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe('Input values keyed by schema item name.'),
                        scheduled_at: zod.string().optional().describe('ISO 8601 datetime for one-time scheduling.'),
                    }),
                    zod.object({
                        type: zod.enum(['batch']),
                        filters: zod
                            .record(zod.string(), zod.unknown())
                            .describe('PostHog property filters selecting persons to process.'),
                    }),
                    zod.object({
                        type: zod.enum(['delay']),
                        delay_duration: zod.string().describe("ISO 8601 duration string, e.g. 'PT1H'."),
                    }),
                    zod.object({
                        type: zod.enum(['wait_until_condition']),
                        condition: zod
                            .record(zod.string(), zod.unknown())
                            .describe('Single condition with a filters object.'),
                        max_wait_duration: zod.string().describe('ISO 8601 maximum wait duration.'),
                    }),
                    zod.object({
                        type: zod.enum(['conditional_branch']),
                        conditions: zod
                            .array(zod.record(zod.string(), zod.unknown()))
                            .describe('Ordered list of conditions with filters objects.'),
                    }),
                    zod.object({
                        type: zod.enum(['random_cohort_branch']),
                        cohorts: zod
                            .array(zod.record(zod.string(), zod.unknown()))
                            .describe('Cohort percentage splits, each with a percentage and optional name.'),
                    }),
                    zod.object({
                        type: zod.enum(['function', 'function_email', 'function_sms']).optional(),
                        template_id: zod.string().describe('HogFunction template ID.'),
                        inputs: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe('Input values keyed by schema item name.'),
                    }),
                    zod.object({
                        type: zod.enum(['exit']),
                        reason: zod.string().optional().describe('Human-readable exit reason.'),
                    }),
                ])
                .describe('Action-specific configuration. Structure is determined by the action type.'),
            output_variable: zod
                .object({
                    key: zod.string().describe('Variable name to store the action output in.'),
                    result_path: zod
                        .string()
                        .nullish()
                        .describe('JSONPath expression into the action result to extract a specific value.'),
                    spread: zod
                        .boolean()
                        .nullish()
                        .describe('When true, spreads all result keys as separate top-level variables.'),
                })
                .nullish(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

/**
 * Returns the full workflow definition including trigger, edges, actions, exit condition, and variables.
 * @summary Get a workflow
 */
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
    id: zod.string(),
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
        uuid: zod.string(),
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
    trigger: zod.unknown().describe("Trigger configuration derived from the trigger action's config."),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsRetrieveResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsRetrieveResponseTriggerMaskingOneTtlMax)
                .nullish()
                .describe('How long (in seconds) a masked person is remembered before they can re-enter the flow.'),
            threshold: zod
                .number()
                .nullish()
                .describe('Minimum number of persons that must accumulate before the flow proceeds, for k-anonymity.'),
            hash: zod.string().describe('HogQL expression that determines the masking group identity.'),
            bytecode: zod.unknown().nullish(),
        })
        .nullish()
        .describe('K-anonymity masking settings applied before the flow starts processing.'),
    conversion: zod
        .object({
            window_minutes: zod
                .number()
                .nullish()
                .describe('Time window in minutes within which a conversion is counted. Null means no limit.'),
            filters: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .nullish()
                .describe('Array of PostHog property filter objects that define the conversion event.'),
            bytecode: zod
                .array(zod.unknown())
                .nullish()
                .describe('Compiled bytecode for the conversion filter. Auto-generated; do not set manually.'),
        })
        .nullish(),
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
    edges: zod
        .array(
            zod.object({
                from: zod.string().describe('ID of the source action node.'),
                to: zod.string().describe('ID of the target action node.'),
                type: zod.enum(['continue', 'branch']).describe('Edge type.'),
                index: zod
                    .number()
                    .nullish()
                    .describe('Branch index (0-based) for ordered branching across multiple outgoing edges.'),
            })
        )
        .optional(),
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
            created_at: zod
                .number()
                .describe('Unix epoch timestamp (milliseconds) when this action was first added to the workflow.'),
            updated_at: zod
                .number()
                .describe('Unix epoch timestamp (milliseconds) when this action was last modified.'),
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
            config: zod
                .union([
                    zod.object({
                        type: zod.enum(['event']),
                        filters: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe('PostHog event and property filters.'),
                        filter_test_accounts: zod.boolean().optional(),
                    }),
                    zod.object({
                        type: zod.enum(['webhook', 'manual', 'schedule', 'tracking_pixel']),
                        template_id: zod.string().describe('HogFunction template ID.'),
                        inputs: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe('Input values keyed by schema item name.'),
                        scheduled_at: zod.string().optional().describe('ISO 8601 datetime for one-time scheduling.'),
                    }),
                    zod.object({
                        type: zod.enum(['batch']),
                        filters: zod
                            .record(zod.string(), zod.unknown())
                            .describe('PostHog property filters selecting persons to process.'),
                    }),
                    zod.object({
                        type: zod.enum(['delay']),
                        delay_duration: zod.string().describe("ISO 8601 duration string, e.g. 'PT1H'."),
                    }),
                    zod.object({
                        type: zod.enum(['wait_until_condition']),
                        condition: zod
                            .record(zod.string(), zod.unknown())
                            .describe('Single condition with a filters object.'),
                        max_wait_duration: zod.string().describe('ISO 8601 maximum wait duration.'),
                    }),
                    zod.object({
                        type: zod.enum(['conditional_branch']),
                        conditions: zod
                            .array(zod.record(zod.string(), zod.unknown()))
                            .describe('Ordered list of conditions with filters objects.'),
                    }),
                    zod.object({
                        type: zod.enum(['random_cohort_branch']),
                        cohorts: zod
                            .array(zod.record(zod.string(), zod.unknown()))
                            .describe('Cohort percentage splits, each with a percentage and optional name.'),
                    }),
                    zod.object({
                        type: zod.enum(['function', 'function_email', 'function_sms']).optional(),
                        template_id: zod.string().describe('HogFunction template ID.'),
                        inputs: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe('Input values keyed by schema item name.'),
                    }),
                    zod.object({
                        type: zod.enum(['exit']),
                        reason: zod.string().optional().describe('Human-readable exit reason.'),
                    }),
                ])
                .describe('Action-specific configuration. Structure is determined by the action type.'),
            output_variable: zod
                .object({
                    key: zod.string().describe('Variable name to store the action output in.'),
                    result_path: zod
                        .string()
                        .nullish()
                        .describe('JSONPath expression into the action result to extract a specific value.'),
                    spread: zod
                        .boolean()
                        .nullish()
                        .describe('When true, spreads all result keys as separate top-level variables.'),
                })
                .nullish(),
        })
    ),
    abort_action: zod
        .string()
        .nullable()
        .describe('ID of the action node to execute when the flow is aborted due to an error.'),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullable(),
})

/**
 * Update workflow fields. Set status='active' to activate a draft workflow, or status='archived' to archive it. Only changed fields need to be included.
 * @summary Update a workflow
 */
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
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMax)
                .nullish()
                .describe('How long (in seconds) a masked person is remembered before they can re-enter the flow.'),
            threshold: zod
                .number()
                .nullish()
                .describe('Minimum number of persons that must accumulate before the flow proceeds, for k-anonymity.'),
            hash: zod.string().describe('HogQL expression that determines the masking group identity.'),
            bytecode: zod.unknown().nullish(),
        })
        .nullish()
        .describe('K-anonymity masking settings applied before the flow starts processing.'),
    conversion: zod
        .object({
            window_minutes: zod
                .number()
                .nullish()
                .describe('Time window in minutes within which a conversion is counted. Null means no limit.'),
            filters: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .nullish()
                .describe('Array of PostHog property filter objects that define the conversion event.'),
            bytecode: zod
                .array(zod.unknown())
                .nullish()
                .describe('Compiled bytecode for the conversion filter. Auto-generated; do not set manually.'),
        })
        .nullish(),
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
    edges: zod
        .array(
            zod.object({
                from: zod.string().describe('ID of the source action node.'),
                to: zod.string().describe('ID of the target action node.'),
                type: zod.enum(['continue', 'branch']).describe('Edge type.'),
                index: zod
                    .number()
                    .nullish()
                    .describe('Branch index (0-based) for ordered branching across multiple outgoing edges.'),
            })
        )
        .optional(),
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
                created_at: zod
                    .number()
                    .describe('Unix epoch timestamp (milliseconds) when this action was first added to the workflow.'),
                updated_at: zod
                    .number()
                    .describe('Unix epoch timestamp (milliseconds) when this action was last modified.'),
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
                config: zod
                    .union([
                        zod.object({
                            type: zod.enum(['event']),
                            filters: zod
                                .record(zod.string(), zod.unknown())
                                .optional()
                                .describe('PostHog event and property filters.'),
                            filter_test_accounts: zod.boolean().optional(),
                        }),
                        zod.object({
                            type: zod.enum(['webhook', 'manual', 'schedule', 'tracking_pixel']),
                            template_id: zod.string().describe('HogFunction template ID.'),
                            inputs: zod
                                .record(zod.string(), zod.unknown())
                                .optional()
                                .describe('Input values keyed by schema item name.'),
                            scheduled_at: zod
                                .string()
                                .optional()
                                .describe('ISO 8601 datetime for one-time scheduling.'),
                        }),
                        zod.object({
                            type: zod.enum(['batch']),
                            filters: zod
                                .record(zod.string(), zod.unknown())
                                .describe('PostHog property filters selecting persons to process.'),
                        }),
                        zod.object({
                            type: zod.enum(['delay']),
                            delay_duration: zod.string().describe("ISO 8601 duration string, e.g. 'PT1H'."),
                        }),
                        zod.object({
                            type: zod.enum(['wait_until_condition']),
                            condition: zod
                                .record(zod.string(), zod.unknown())
                                .describe('Single condition with a filters object.'),
                            max_wait_duration: zod.string().describe('ISO 8601 maximum wait duration.'),
                        }),
                        zod.object({
                            type: zod.enum(['conditional_branch']),
                            conditions: zod
                                .array(zod.record(zod.string(), zod.unknown()))
                                .describe('Ordered list of conditions with filters objects.'),
                        }),
                        zod.object({
                            type: zod.enum(['random_cohort_branch']),
                            cohorts: zod
                                .array(zod.record(zod.string(), zod.unknown()))
                                .describe('Cohort percentage splits, each with a percentage and optional name.'),
                        }),
                        zod.object({
                            type: zod.enum(['function', 'function_email', 'function_sms']).optional(),
                            template_id: zod.string().describe('HogFunction template ID.'),
                            inputs: zod
                                .record(zod.string(), zod.unknown())
                                .optional()
                                .describe('Input values keyed by schema item name.'),
                        }),
                        zod.object({
                            type: zod.enum(['exit']),
                            reason: zod.string().optional().describe('Human-readable exit reason.'),
                        }),
                    ])
                    .describe('Action-specific configuration. Structure is determined by the action type.'),
                output_variable: zod
                    .object({
                        key: zod.string().describe('Variable name to store the action output in.'),
                        result_path: zod
                            .string()
                            .nullish()
                            .describe('JSONPath expression into the action result to extract a specific value.'),
                        spread: zod
                            .boolean()
                            .nullish()
                            .describe('When true, spreads all result keys as separate top-level variables.'),
                    })
                    .nullish(),
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
    id: zod.string(),
    name: zod.string().max(hogFlowsPartialUpdateResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.string().datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.string(),
        distinct_id: zod.string().max(hogFlowsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFlowsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFlowsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.string().email().max(hogFlowsPartialUpdateResponseCreatedByOneEmailMax),
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
    trigger: zod.unknown().describe("Trigger configuration derived from the trigger action's config."),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsPartialUpdateResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsPartialUpdateResponseTriggerMaskingOneTtlMax)
                .nullish()
                .describe('How long (in seconds) a masked person is remembered before they can re-enter the flow.'),
            threshold: zod
                .number()
                .nullish()
                .describe('Minimum number of persons that must accumulate before the flow proceeds, for k-anonymity.'),
            hash: zod.string().describe('HogQL expression that determines the masking group identity.'),
            bytecode: zod.unknown().nullish(),
        })
        .nullish()
        .describe('K-anonymity masking settings applied before the flow starts processing.'),
    conversion: zod
        .object({
            window_minutes: zod
                .number()
                .nullish()
                .describe('Time window in minutes within which a conversion is counted. Null means no limit.'),
            filters: zod
                .array(zod.record(zod.string(), zod.unknown()))
                .nullish()
                .describe('Array of PostHog property filter objects that define the conversion event.'),
            bytecode: zod
                .array(zod.unknown())
                .nullish()
                .describe('Compiled bytecode for the conversion filter. Auto-generated; do not set manually.'),
        })
        .nullish(),
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
    edges: zod
        .array(
            zod.object({
                from: zod.string().describe('ID of the source action node.'),
                to: zod.string().describe('ID of the target action node.'),
                type: zod.enum(['continue', 'branch']).describe('Edge type.'),
                index: zod
                    .number()
                    .nullish()
                    .describe('Branch index (0-based) for ordered branching across multiple outgoing edges.'),
            })
        )
        .optional(),
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
            created_at: zod
                .number()
                .describe('Unix epoch timestamp (milliseconds) when this action was first added to the workflow.'),
            updated_at: zod
                .number()
                .describe('Unix epoch timestamp (milliseconds) when this action was last modified.'),
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
            config: zod
                .union([
                    zod.object({
                        type: zod.enum(['event']),
                        filters: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe('PostHog event and property filters.'),
                        filter_test_accounts: zod.boolean().optional(),
                    }),
                    zod.object({
                        type: zod.enum(['webhook', 'manual', 'schedule', 'tracking_pixel']),
                        template_id: zod.string().describe('HogFunction template ID.'),
                        inputs: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe('Input values keyed by schema item name.'),
                        scheduled_at: zod.string().optional().describe('ISO 8601 datetime for one-time scheduling.'),
                    }),
                    zod.object({
                        type: zod.enum(['batch']),
                        filters: zod
                            .record(zod.string(), zod.unknown())
                            .describe('PostHog property filters selecting persons to process.'),
                    }),
                    zod.object({
                        type: zod.enum(['delay']),
                        delay_duration: zod.string().describe("ISO 8601 duration string, e.g. 'PT1H'."),
                    }),
                    zod.object({
                        type: zod.enum(['wait_until_condition']),
                        condition: zod
                            .record(zod.string(), zod.unknown())
                            .describe('Single condition with a filters object.'),
                        max_wait_duration: zod.string().describe('ISO 8601 maximum wait duration.'),
                    }),
                    zod.object({
                        type: zod.enum(['conditional_branch']),
                        conditions: zod
                            .array(zod.record(zod.string(), zod.unknown()))
                            .describe('Ordered list of conditions with filters objects.'),
                    }),
                    zod.object({
                        type: zod.enum(['random_cohort_branch']),
                        cohorts: zod
                            .array(zod.record(zod.string(), zod.unknown()))
                            .describe('Cohort percentage splits, each with a percentage and optional name.'),
                    }),
                    zod.object({
                        type: zod.enum(['function', 'function_email', 'function_sms']).optional(),
                        template_id: zod.string().describe('HogFunction template ID.'),
                        inputs: zod
                            .record(zod.string(), zod.unknown())
                            .optional()
                            .describe('Input values keyed by schema item name.'),
                    }),
                    zod.object({
                        type: zod.enum(['exit']),
                        reason: zod.string().optional().describe('Human-readable exit reason.'),
                    }),
                ])
                .describe('Action-specific configuration. Structure is determined by the action type.'),
            output_variable: zod
                .object({
                    key: zod.string().describe('Variable name to store the action output in.'),
                    result_path: zod
                        .string()
                        .nullish()
                        .describe('JSONPath expression into the action result to extract a specific value.'),
                    spread: zod
                        .boolean()
                        .nullish()
                        .describe('When true, spreads all result keys as separate top-level variables.'),
                })
                .nullish(),
        })
    ),
    abort_action: zod
        .string()
        .nullable()
        .describe('ID of the action node to execute when the flow is aborted due to an error.'),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullable(),
})

/**
 * Permanently delete an archived workflow. Prefer archiving (status='archived' via partial update) over deletion to preserve audit history.
 * @summary Delete a workflow
 */
export const HogFlowsDestroyParams = zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Permanently delete multiple archived workflows by their IDs. Only archived workflows can be deleted.
 * @summary Bulk delete workflows
 */
export const HogFlowsBulkDeleteCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowsBulkDeleteCreateBody = zod.object({
    ids: zod.array(zod.string()).describe('List of workflow IDs to delete.'),
})

export const HogFlowsBulkDeleteCreateResponse = zod.object({
    deleted: zod.number().describe('Number of workflows deleted.'),
})
