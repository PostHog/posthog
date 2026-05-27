/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 7 enabled ops
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
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: zod.number().optional(),
    id: zod.string().optional(),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    status: zod
        .enum(['active', 'archived', 'draft'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
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
export const hogFlowsCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsCreateBodyTriggerMaskingOneTtlMax = 94608000

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
            'Workflow state: draft (editing, no live execution), active (processing events live), or archived (soft-deleted, no execution).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
        ),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsCreateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsCreateBodyTriggerMaskingOneTtlMax)
                    .nullish()
                    .describe('Time-to-live in seconds for the masking hash. Min 60s, max 3 years.'),
                threshold: zod
                    .number()
                    .nullish()
                    .describe(
                        'Minimum number of matching events before the workflow triggers (k-anonymity threshold).'
                    ),
                hash: zod
                    .string()
                    .describe("HogQL template expression used as the masking key (e.g. '{person.properties.email}')."),
                bytecode: zod
                    .unknown()
                    .optional()
                    .describe(
                        'Compiled bytecode for the hash template. Auto-generated server-side from the hash expression.'
                    ),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            "Optional deduplication config that prevents the same entity from entering the workflow multiple times within a TTL window. Shape: {hash: <HogQL template, e.g. '{person.properties.email}'>, ttl: <seconds, 60-94608000>, threshold?: <int, min matches before triggering>}. The server compiles 'bytecode' from 'hash' automatically — do not set bytecode yourself. Omit entirely to disable deduplication."
        ),
    conversion: zod
        .unknown()
        .optional()
        .describe(
            'Conversion goal. Shape: {filters: [<property condition>, ...], window_minutes: <int>}. \'filters\' is an array of property conditions; each condition is {key, value, operator, type} where type is \'event\' | \'person\' | \'group\'. Example: {"filters": [{"key": "plan", "value": "paid", "operator": "exact", "type": "person"}], "window_minutes": 60}. Empty array means any event in the window counts. Required when exit_condition is exit_on_conversion or exit_on_trigger_not_matched_or_conversion. \'bytecode\' is compiled server-side from \'filters\' — do not set it.'
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
            zod.null(),
        ])
        .optional()
        .describe(
            "When a person exits the workflow. exit_only_at_end (default): only exits at an explicit exit node. exit_on_conversion: also exits early if a conversion event fires anywhere mid-workflow — REQUIRES 'conversion' to be set, otherwise this is a silent no-op. exit_on_trigger_not_matched: exits early if the trigger filter stops matching for that person. exit_on_trigger_not_matched_or_conversion: both of the above — also requires 'conversion' to be set.\n\n* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End"
        ),
    edges: zod
        .unknown()
        .optional()
        .describe(
            "Graph edges connecting action nodes. Array of {from, to, type, index?} objects. type='continue' is the default/fall-through edge — followed when an action does not select a specific branch (sequential nodes, the no-match path of a conditional_branch). type='branch' requires an integer 'index' field — followed when a conditional_branch / wait_until_condition action matches the condition at that index in its config.conditions array. Example for a conditional_branch with one condition: {from: 'cond', to: 'matched_node', type: 'branch', index: 0} for the matched path AND {from: 'cond', to: 'else_node', type: 'continue'} for the no-match path. Every non-exit action needs a reachable next action — orphan paths cause the runtime to error with 'No next action found'."
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
                        zod.null(),
                    ])
                    .optional()
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
                    .union([
                        zod.object({
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
                            bytecode: zod.unknown().optional(),
                            transpiled: zod.unknown().optional(),
                            filter_test_accounts: zod.boolean().optional(),
                            bytecode_error: zod.string().optional(),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Property filters that gate execution of this action.'),
                type: zod
                    .string()
                    .max(hogFlowsCreateBodyActionsItemTypeMax)
                    .describe(
                        'Action type. One of: trigger, function, function_email, function_sms, function_push, delay, conditional_branch, wait_until_condition, wait_until_time_window, random_cohort_branch, exit.'
                    ),
                config: zod
                    .unknown()
                    .describe(
                        'Type-specific configuration. For triggers: {type: \'event\'|\'webhook\'|\'manual\'|\'batch\'|\'schedule\'|\'tracking_pixel\', filters?}. filters is an object: {events: [{id, name, type: \'events\', properties: [<property condition>]}], properties: [<property condition>], actions: [...], filter_test_accounts: <bool>}. Each property condition is {key, value, operator, type: \'event\'|\'person\'|\'group\'}. Example: {"type": "event", "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "properties": [{"key": "$current_url", "value": "/pricing", "operator": "icontains", "type": "event"}]}]}}. For function*: {template_id, inputs}. For delay: {delay_duration: <string>} — duration format is \'<number><unit>\' where unit is one of m|h|d (minutes, hours, days), e.g. \'30m\', \'1.5h\', \'2d\'. Fractions allowed — for sub-minute delays use a fraction of a minute (e.g. \'0.5m\' = 30 seconds); seconds are not supported. Per-unit max enforced by executor: m<=60, h<=24, d<=30; values above these are SILENTLY CLAMPED — to wait >24h use days, etc. Max effective duration is 30d. For conditional_branch: {conditions: [{filters: {...}}, ...]} — each condition\'s array position determines which \'branch\' edge fires when it matches (condition at index 0 -> edge with index:0). For wait_until_condition: {condition: {filters: {...}}, max_wait_duration: <duration string>} — same duration format and clamping rules as delay. For exit: {reason: <string>}.'
                    ),
                output_variable: zod
                    .unknown()
                    .optional()
                    .describe("Variable definition to store this action's output for use by downstream actions."),
            })
        )
        .describe(
            "Ordered list of action nodes in the workflow. Must include exactly one action with type='trigger'. Typically also includes one action with type='exit'."
        ),
    variables: zod
        .array(
            zod
                .record(zod.string(), zod.string())
                .describe(
                    "Variable definition. Keys: 'key' (unique identifier used in templating), 'type' (string|number|boolean), 'default' (initial value as a string)."
                )
        )
        .optional()
        .describe(
            'Workflow-level variables that persist across actions. Each variable has key, type, and default. Total serialized size must be under 5KB.'
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

export const hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMax = 94608000

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
            'Workflow state: draft (editing, no live execution), active (processing events live), or archived (soft-deleted, no execution).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
        ),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMax)
                    .nullish()
                    .describe('Time-to-live in seconds for the masking hash. Min 60s, max 3 years.'),
                threshold: zod
                    .number()
                    .nullish()
                    .describe(
                        'Minimum number of matching events before the workflow triggers (k-anonymity threshold).'
                    ),
                hash: zod
                    .string()
                    .describe("HogQL template expression used as the masking key (e.g. '{person.properties.email}')."),
                bytecode: zod
                    .unknown()
                    .optional()
                    .describe(
                        'Compiled bytecode for the hash template. Auto-generated server-side from the hash expression.'
                    ),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            "Optional deduplication config that prevents the same entity from entering the workflow multiple times within a TTL window. Shape: {hash: <HogQL template, e.g. '{person.properties.email}'>, ttl: <seconds, 60-94608000>, threshold?: <int, min matches before triggering>}. The server compiles 'bytecode' from 'hash' automatically — do not set bytecode yourself. Omit entirely to disable deduplication."
        ),
    conversion: zod
        .unknown()
        .optional()
        .describe(
            'Conversion goal. Shape: {filters: [<property condition>, ...], window_minutes: <int>}. \'filters\' is an array of property conditions; each condition is {key, value, operator, type} where type is \'event\' | \'person\' | \'group\'. Example: {"filters": [{"key": "plan", "value": "paid", "operator": "exact", "type": "person"}], "window_minutes": 60}. Empty array means any event in the window counts. Required when exit_condition is exit_on_conversion or exit_on_trigger_not_matched_or_conversion. \'bytecode\' is compiled server-side from \'filters\' — do not set it.'
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
            zod.null(),
        ])
        .optional()
        .describe(
            "When a person exits the workflow. exit_only_at_end (default): only exits at an explicit exit node. exit_on_conversion: also exits early if a conversion event fires anywhere mid-workflow — REQUIRES 'conversion' to be set, otherwise this is a silent no-op. exit_on_trigger_not_matched: exits early if the trigger filter stops matching for that person. exit_on_trigger_not_matched_or_conversion: both of the above — also requires 'conversion' to be set.\n\n* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End"
        ),
    edges: zod
        .unknown()
        .optional()
        .describe(
            "Graph edges connecting action nodes. Array of {from, to, type, index?} objects. type='continue' is the default/fall-through edge — followed when an action does not select a specific branch (sequential nodes, the no-match path of a conditional_branch). type='branch' requires an integer 'index' field — followed when a conditional_branch / wait_until_condition action matches the condition at that index in its config.conditions array. Example for a conditional_branch with one condition: {from: 'cond', to: 'matched_node', type: 'branch', index: 0} for the matched path AND {from: 'cond', to: 'else_node', type: 'continue'} for the no-match path. Every non-exit action needs a reachable next action — orphan paths cause the runtime to error with 'No next action found'."
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
                        zod.null(),
                    ])
                    .optional()
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
                    .union([
                        zod.object({
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
                            bytecode: zod.unknown().optional(),
                            transpiled: zod.unknown().optional(),
                            filter_test_accounts: zod.boolean().optional(),
                            bytecode_error: zod.string().optional(),
                        }),
                        zod.null(),
                    ])
                    .optional()
                    .describe('Property filters that gate execution of this action.'),
                type: zod
                    .string()
                    .max(hogFlowsPartialUpdateBodyActionsItemTypeMax)
                    .describe(
                        'Action type. One of: trigger, function, function_email, function_sms, function_push, delay, conditional_branch, wait_until_condition, wait_until_time_window, random_cohort_branch, exit.'
                    ),
                config: zod
                    .unknown()
                    .describe(
                        'Type-specific configuration. For triggers: {type: \'event\'|\'webhook\'|\'manual\'|\'batch\'|\'schedule\'|\'tracking_pixel\', filters?}. filters is an object: {events: [{id, name, type: \'events\', properties: [<property condition>]}], properties: [<property condition>], actions: [...], filter_test_accounts: <bool>}. Each property condition is {key, value, operator, type: \'event\'|\'person\'|\'group\'}. Example: {"type": "event", "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "properties": [{"key": "$current_url", "value": "/pricing", "operator": "icontains", "type": "event"}]}]}}. For function*: {template_id, inputs}. For delay: {delay_duration: <string>} — duration format is \'<number><unit>\' where unit is one of m|h|d (minutes, hours, days), e.g. \'30m\', \'1.5h\', \'2d\'. Fractions allowed — for sub-minute delays use a fraction of a minute (e.g. \'0.5m\' = 30 seconds); seconds are not supported. Per-unit max enforced by executor: m<=60, h<=24, d<=30; values above these are SILENTLY CLAMPED — to wait >24h use days, etc. Max effective duration is 30d. For conditional_branch: {conditions: [{filters: {...}}, ...]} — each condition\'s array position determines which \'branch\' edge fires when it matches (condition at index 0 -> edge with index:0). For wait_until_condition: {condition: {filters: {...}}, max_wait_duration: <duration string>} — same duration format and clamping rules as delay. For exit: {reason: <string>}.'
                    ),
                output_variable: zod
                    .unknown()
                    .optional()
                    .describe("Variable definition to store this action's output for use by downstream actions."),
            })
        )
        .optional()
        .describe(
            "Ordered list of action nodes in the workflow. Must include exactly one action with type='trigger'. Typically also includes one action with type='exit'."
        ),
    variables: zod
        .array(
            zod
                .record(zod.string(), zod.string())
                .describe(
                    "Variable definition. Keys: 'key' (unique identifier used in templating), 'type' (string|number|boolean), 'default' (initial value as a string)."
                )
        )
        .optional()
        .describe(
            'Workflow-level variables that persist across actions. Each variable has key, type, and default. Total serialized size must be under 5KB.'
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
            'Test event data to trigger the workflow with. Object shape matches the trigger payload — typically {event: {...}, person: {...}, groups: {...}}.'
        ),
    mock_async_functions: zod
        .boolean()
        .default(hogFlowsInvocationsCreateBodyMockAsyncFunctionsDefault)
        .describe(
            'When true (default), async actions (HTTP requests, emails, SMS) are simulated rather than executed. Set false to actually fire side effects — use with caution.'
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
    after: zod.iso.datetime({ offset: true }).optional().describe('Only return entries after this ISO 8601 timestamp.'),
    before: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Only return entries before this ISO 8601 timestamp.'),
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
