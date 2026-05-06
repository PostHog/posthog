/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 8 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const HogFlowsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowsListQueryParams = /* @__PURE__ */ zod.object({
    created_at: zod.iso.datetime({}).optional(),
    created_by: zod.number().optional(),
    id: zod.string().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    updated_at: zod.iso.datetime({}).optional(),
})

export const HogFlowsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsCreateBodyNameMax = 400

export const hogFlowsCreateBodyDescriptionDefault = ``
export const hogFlowsCreateBodyActionsItemNameMax = 400

export const hogFlowsCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsCreateBodyActionsItemTypeMax = 100

export const HogFlowsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsCreateBodyNameMax).nullish().describe('Human-readable name for the workflow.'),
    description: zod
        .string()
        .default(hogFlowsCreateBodyDescriptionDefault)
        .describe("Optional description of the workflow's purpose."),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived')
        .optional()
        .describe(
            'Workflow state: draft (editing), active (live and processing events), or archived (soft-deleted).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
        ),
    exit_condition: zod
        .union([
            zod
                .enum([
                    'exit_on_conversion',
                    'exit_on_trigger_not_matched',
                    'exit_on_trigger_not_matched_or_conversion',
                    'exit_only_at_end',
                ])
                .describe(
                    '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'When a person exits the workflow: exit_on_conversion, exit_on_trigger_not_matched, exit_on_trigger_not_matched_or_conversion, or exit_only_at_end.\n\n* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod
        .unknown()
        .optional()
        .describe(
            'Graph edges connecting action nodes. Array of {source, target} objects defining the execution flow between actions.'
        ),
    actions: zod
        .array(
            zod.object({
                id: zod.string().describe('Unique identifier for this action node within the workflow graph.'),
                name: zod
                    .string()
                    .max(hogFlowsCreateBodyActionsItemNameMax)
                    .describe('Human-readable name for the action node.'),
                description: zod
                    .string()
                    .default(hogFlowsCreateBodyActionsItemDescriptionDefault)
                    .describe('Optional description of what this action does.'),
                on_error: zod
                    .union([
                        zod
                            .enum(['continue', 'abort', 'complete', 'branch'])
                            .describe(
                                '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                            ),
                        zod.literal(null),
                    ])
                    .nullish()
                    .describe(
                        'Behavior when this action fails: continue (skip and proceed), abort (stop workflow), complete (mark as done), or branch (follow error edge).\n\n* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                    ),
                created_at: zod
                    .number()
                    .optional()
                    .describe('Unix epoch milliseconds when the action was added. Auto-managed by the frontend.'),
                updated_at: zod
                    .number()
                    .optional()
                    .describe(
                        'Unix epoch milliseconds when the action was last modified. Auto-managed by the frontend.'
                    ),
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
                    .nullish()
                    .describe('Property filters that gate execution of this action.'),
                type: zod
                    .string()
                    .max(hogFlowsCreateBodyActionsItemTypeMax)
                    .describe(
                        'Action type: trigger, function, function_email, function_sms, function_push, delay, conditional_branch, wait_until_condition, random_cohort_branch, exit.'
                    ),
                config: zod
                    .unknown()
                    .describe(
                        "Type-specific configuration. For triggers: {type, filters}. For functions: {template_id, inputs}. For delays: {delay_duration, e.g. '30m', '2h', '1d'}. For conditional branches: {conditions}."
                    ),
                output_variable: zod
                    .unknown()
                    .nullish()
                    .describe("Variable definition to store this action's output for use by downstream actions."),
            })
        )
        .describe("Ordered list of action nodes in the workflow. Must include exactly one action with type='trigger'."),
    variables: zod
        .array(
            zod
                .record(zod.string(), zod.string())
                .describe(
                    "Variable definition with keys: 'key' (unique identifier), 'type' (string/number/boolean), 'default' (initial value)."
                )
        )
        .optional()
        .describe(
            'Workflow-level variables that persist across actions. Each variable has a key, type, and default value. Total size must be under 5KB.'
        ),
})

export const HogFlowsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsPartialUpdateBodyNameMax = 400

export const hogFlowsPartialUpdateBodyActionsItemNameMax = 400

export const hogFlowsPartialUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowsPartialUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsPartialUpdateBodyActionsItemTypeMax = 100

export const HogFlowsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(hogFlowsPartialUpdateBodyNameMax)
        .nullish()
        .describe('Human-readable name for the workflow.'),
    description: zod.string().optional().describe("Optional description of the workflow's purpose."),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived')
        .optional()
        .describe(
            'Workflow state: draft (editing), active (live and processing events), or archived (soft-deleted).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
        ),
    exit_condition: zod
        .union([
            zod
                .enum([
                    'exit_on_conversion',
                    'exit_on_trigger_not_matched',
                    'exit_on_trigger_not_matched_or_conversion',
                    'exit_only_at_end',
                ])
                .describe(
                    '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'When a person exits the workflow: exit_on_conversion, exit_on_trigger_not_matched, exit_on_trigger_not_matched_or_conversion, or exit_only_at_end.\n\n* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
        ),
    edges: zod
        .unknown()
        .optional()
        .describe(
            'Graph edges connecting action nodes. Array of {source, target} objects defining the execution flow between actions.'
        ),
    actions: zod
        .array(
            zod.object({
                id: zod.string().describe('Unique identifier for this action node within the workflow graph.'),
                name: zod
                    .string()
                    .max(hogFlowsPartialUpdateBodyActionsItemNameMax)
                    .describe('Human-readable name for the action node.'),
                description: zod
                    .string()
                    .default(hogFlowsPartialUpdateBodyActionsItemDescriptionDefault)
                    .describe('Optional description of what this action does.'),
                on_error: zod
                    .union([
                        zod
                            .enum(['continue', 'abort', 'complete', 'branch'])
                            .describe(
                                '* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                            ),
                        zod.literal(null),
                    ])
                    .nullish()
                    .describe(
                        'Behavior when this action fails: continue (skip and proceed), abort (stop workflow), complete (mark as done), or branch (follow error edge).\n\n* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                    ),
                created_at: zod
                    .number()
                    .optional()
                    .describe('Unix epoch milliseconds when the action was added. Auto-managed by the frontend.'),
                updated_at: zod
                    .number()
                    .optional()
                    .describe(
                        'Unix epoch milliseconds when the action was last modified. Auto-managed by the frontend.'
                    ),
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
                    .nullish()
                    .describe('Property filters that gate execution of this action.'),
                type: zod
                    .string()
                    .max(hogFlowsPartialUpdateBodyActionsItemTypeMax)
                    .describe(
                        'Action type: trigger, function, function_email, function_sms, function_push, delay, conditional_branch, wait_until_condition, random_cohort_branch, exit.'
                    ),
                config: zod
                    .unknown()
                    .describe(
                        "Type-specific configuration. For triggers: {type, filters}. For functions: {template_id, inputs}. For delays: {delay_duration, e.g. '30m', '2h', '1d'}. For conditional branches: {conditions}."
                    ),
                output_variable: zod
                    .unknown()
                    .nullish()
                    .describe("Variable definition to store this action's output for use by downstream actions."),
            })
        )
        .optional()
        .describe("Ordered list of action nodes in the workflow. Must include exactly one action with type='trigger'."),
    variables: zod
        .array(
            zod
                .record(zod.string(), zod.string())
                .describe(
                    "Variable definition with keys: 'key' (unique identifier), 'type' (string/number/boolean), 'default' (initial value)."
                )
        )
        .optional()
        .describe(
            'Workflow-level variables that persist across actions. Each variable has a key, type, and default value. Total size must be under 5KB.'
        ),
})

export const HogFlowsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowsInvocationsCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsInvocationsCreateBodyMockAsyncFunctionsDefault = true

export const HogFlowsInvocationsCreateBody = /* @__PURE__ */ zod.object({
    globals: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            "Test event data to trigger the workflow with. Object with keys like 'event', 'person', 'groups' matching the event shape."
        ),
    mock_async_functions: zod
        .boolean()
        .default(hogFlowsInvocationsCreateBodyMockAsyncFunctionsDefault)
        .describe(
            'When true (default), async actions (HTTP requests, emails) are simulated rather than executed for safety.'
        ),
    current_action_id: zod
        .string()
        .optional()
        .describe(
            'Start execution from a specific action node ID instead of the trigger. Useful for testing mid-workflow actions.'
        ),
})

export const HogFlowsLogsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsLogsRetrieveQueryLimitDefault = 50
export const hogFlowsLogsRetrieveQueryLimitMax = 500

export const HogFlowsLogsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    after: zod.iso.datetime({}).optional().describe('Only return entries after this ISO 8601 timestamp.'),
    before: zod.iso.datetime({}).optional().describe('Only return entries before this ISO 8601 timestamp.'),
    instance_id: zod.string().min(1).optional().describe('Filter logs to a specific execution instance.'),
    level: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Comma-separated log levels to include, e.g. 'WARN,ERROR'. Valid levels: DEBUG, LOG, INFO, WARN, ERROR."
        ),
    limit: zod
        .number()
        .min(1)
        .max(hogFlowsLogsRetrieveQueryLimitMax)
        .default(hogFlowsLogsRetrieveQueryLimitDefault)
        .describe('Maximum number of log entries to return (1-500, default 50).'),
    search: zod.string().min(1).optional().describe('Case-insensitive substring search across log messages.'),
})

export const HogFlowsMetricsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsMetricsRetrieveQueryAfterDefault = `-7d`

export const hogFlowsMetricsRetrieveQueryBreakdownByDefault = `kind`
export const hogFlowsMetricsRetrieveQueryIntervalDefault = `day`

export const HogFlowsMetricsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    after: zod
        .string()
        .min(1)
        .default(hogFlowsMetricsRetrieveQueryAfterDefault)
        .describe(
            "Start of the time range. Accepts relative formats like '-7d', '-24h' or ISO 8601 timestamps. Defaults to '-7d'."
        ),
    before: zod.string().min(1).optional().describe("End of the time range. Same format as 'after'. Defaults to now."),
    breakdown_by: zod
        .enum(['name', 'kind'])
        .default(hogFlowsMetricsRetrieveQueryBreakdownByDefault)
        .describe(
            "Group the series by metric 'name' or 'kind'. Defaults to 'kind'.\n\n* `name` - name\n* `kind` - kind"
        ),
    instance_id: zod.string().min(1).optional().describe('Filter metrics to a specific execution instance.'),
    interval: zod
        .enum(['hour', 'day', 'week'])
        .default(hogFlowsMetricsRetrieveQueryIntervalDefault)
        .describe(
            "Time bucket size for the series. One of: hour, day, week. Defaults to 'day'.\n\n* `hour` - hour\n* `day` - day\n* `week` - week"
        ),
    kind: zod.string().min(1).optional().describe("Comma-separated metric kinds to filter by, e.g. 'success,failure'."),
    name: zod.string().min(1).optional().describe('Comma-separated metric names to filter by.'),
})
