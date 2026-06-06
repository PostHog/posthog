/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 9 enabled ops
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
    name: zod.string().max(hogFlowsCreateBodyNameMax).nullish().describe('Workflow name.'),
    description: zod.string().default(hogFlowsCreateBodyDescriptionDefault).describe('Optional description.'),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived')
        .optional()
        .describe(
            'draft (no execution), active (live), archived (disabled).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
        ),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsCreateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsCreateBodyTriggerMaskingOneTtlMax)
                    .nullish()
                    .describe('Hash TTL in seconds (60 to ~94M / 3y).'),
                threshold: zod.number().nullish().describe('Min matching events before triggering (k-anonymity).'),
                hash: zod.string().describe("HogQL template, e.g. '{person.properties.email}'."),
                bytecode: zod.unknown().optional().describe('Auto-compiled from hash. Do not set.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            'Optional dedup: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Server compiles bytecode from hash. Omit to disable.'
        ),
    conversion: zod
        .unknown()
        .optional()
        .describe(
            'Conversion goal: {filters: [<cond>, ...], window_minutes}. <cond>: {key, value, operator, type: event|person|group}. Empty filters = any event in window. Required for exit_on_conversion / exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side.'
        ),
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
        .optional()
        .describe(
            "exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion').\n\n* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End"
        ),
    edges: zod
        .array(
            zod.object({
                to: zod.string().describe('Target action id.'),
                type: zod
                    .enum(['continue', 'branch'])
                    .describe('* `continue` - continue\n* `branch` - branch')
                    .describe(
                        "continue: fall-through (sequential or the no-match path of conditional_branch). branch: requires 'index' matching config.conditions[index].\n\n* `continue` - continue\n* `branch` - branch"
                    ),
                index: zod
                    .number()
                    .optional()
                    .describe(
                        "Required for type='branch'. Index into config.conditions on conditional_branch / wait_until_condition."
                    ),
                from: zod.string().describe('Source action id.'),
            })
        )
        .optional()
        .describe(
            "Graph edges: [{from, to, type: 'continue'|'branch', index?}]. 'continue' = fall-through (sequential, or no-match path of conditional_branch). 'branch' requires 'index': matches config.conditions[index] on conditional_branch / wait_until_condition. Every non-exit action needs a reachable next action ('No next action found' otherwise)."
        ),
    actions: zod
        .array(
            zod.object({
                id: zod.string().describe('Unique node ID within the workflow.'),
                name: zod.string().max(hogFlowsCreateBodyActionsItemNameMax).describe('Display name.'),
                description: zod
                    .string()
                    .default(hogFlowsCreateBodyActionsItemDescriptionDefault)
                    .describe('Optional description.'),
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
                        'On failure: continue (skip), abort (stop), complete (mark done), branch (follow error edge).\n\n* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                    ),
                created_at: zod.number().optional().describe('Created at (epoch ms). Frontend-managed.'),
                updated_at: zod.number().optional().describe('Updated at (epoch ms). Frontend-managed.'),
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
                    .describe('Property filters gating this action.'),
                type: zod
                    .string()
                    .max(hogFlowsCreateBodyActionsItemTypeMax)
                    .describe(
                        'trigger | function | function_email | function_sms | function_push | delay | conditional_branch | wait_until_condition | wait_until_time_window | random_cohort_branch | exit.'
                    ),
                config: zod
                    .unknown()
                    .describe(
                        "Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}. function*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. wait_until_condition: {condition: {filters}, max_wait_duration: <duration>} (same rules as delay). exit: {reason}."
                    ),
                output_variable: zod
                    .unknown()
                    .optional()
                    .describe('Output variable definition for downstream actions.'),
            })
        )
        .describe("Ordered action nodes. Exactly one type='trigger' required. Typically one type='exit' too."),
    variables: zod
        .array(
            zod.record(zod.string(), zod.string()).describe('Variable: {key, type: string|number|boolean, default}.')
        )
        .optional()
        .describe('Workflow vars (key, type, default). Total <5KB.'),
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
    name: zod.string().max(hogFlowsPartialUpdateBodyNameMax).nullish().describe('Workflow name.'),
    description: zod.string().optional().describe('Optional description.'),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMax)
                    .nullish()
                    .describe('Hash TTL in seconds (60 to ~94M / 3y).'),
                threshold: zod.number().nullish().describe('Min matching events before triggering (k-anonymity).'),
                hash: zod.string().describe("HogQL template, e.g. '{person.properties.email}'."),
                bytecode: zod.unknown().optional().describe('Auto-compiled from hash. Do not set.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            'Optional dedup: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Server compiles bytecode from hash. Omit to disable.'
        ),
    conversion: zod
        .unknown()
        .optional()
        .describe(
            'Conversion goal: {filters: [<cond>, ...], window_minutes}. <cond>: {key, value, operator, type: event|person|group}. Empty filters = any event in window. Required for exit_on_conversion / exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side.'
        ),
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
        .optional()
        .describe(
            "exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion').\n\n* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End"
        ),
    edges: zod
        .array(
            zod.object({
                to: zod.string().describe('Target action id.'),
                type: zod
                    .enum(['continue', 'branch'])
                    .describe('* `continue` - continue\n* `branch` - branch')
                    .describe(
                        "continue: fall-through (sequential or the no-match path of conditional_branch). branch: requires 'index' matching config.conditions[index].\n\n* `continue` - continue\n* `branch` - branch"
                    ),
                index: zod
                    .number()
                    .optional()
                    .describe(
                        "Required for type='branch'. Index into config.conditions on conditional_branch / wait_until_condition."
                    ),
                from: zod.string().describe('Source action id.'),
            })
        )
        .optional()
        .describe(
            "Graph edges: [{from, to, type: 'continue'|'branch', index?}]. 'continue' = fall-through (sequential, or no-match path of conditional_branch). 'branch' requires 'index': matches config.conditions[index] on conditional_branch / wait_until_condition. Every non-exit action needs a reachable next action ('No next action found' otherwise)."
        ),
    actions: zod
        .array(
            zod.object({
                id: zod.string().describe('Unique node ID within the workflow.'),
                name: zod.string().max(hogFlowsPartialUpdateBodyActionsItemNameMax).describe('Display name.'),
                description: zod
                    .string()
                    .default(hogFlowsPartialUpdateBodyActionsItemDescriptionDefault)
                    .describe('Optional description.'),
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
                        'On failure: continue (skip), abort (stop), complete (mark done), branch (follow error edge).\n\n* `continue` - continue\n* `abort` - abort\n* `complete` - complete\n* `branch` - branch'
                    ),
                created_at: zod.number().optional().describe('Created at (epoch ms). Frontend-managed.'),
                updated_at: zod.number().optional().describe('Updated at (epoch ms). Frontend-managed.'),
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
                    .describe('Property filters gating this action.'),
                type: zod
                    .string()
                    .max(hogFlowsPartialUpdateBodyActionsItemTypeMax)
                    .describe(
                        'trigger | function | function_email | function_sms | function_push | delay | conditional_branch | wait_until_condition | wait_until_time_window | random_cohort_branch | exit.'
                    ),
                config: zod
                    .unknown()
                    .describe(
                        "Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}. function*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. wait_until_condition: {condition: {filters}, max_wait_duration: <duration>} (same rules as delay). exit: {reason}."
                    ),
                output_variable: zod
                    .unknown()
                    .optional()
                    .describe('Output variable definition for downstream actions.'),
            })
        )
        .optional()
        .describe("Ordered action nodes. Exactly one type='trigger' required. Typically one type='exit' too."),
    variables: zod
        .array(
            zod.record(zod.string(), zod.string()).describe('Variable: {key, type: string|number|boolean, default}.')
        )
        .optional()
        .describe('Workflow vars (key, type, default). Total <5KB.'),
})

export const HogFlowsBatchJobsListParams = /* @__PURE__ */ zod.object({
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
        .describe('Test trigger payload, typically {event, person, groups}.'),
    mock_async_functions: zod
        .boolean()
        .default(hogFlowsInvocationsCreateBodyMockAsyncFunctionsDefault)
        .describe('True (default) mocks HTTP/email/SMS. False fires real side effects.'),
    current_action_id: zod.string().optional().describe('Start from this action ID instead of the trigger.'),
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

export const HogFlowsSchedulesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    schedule_id: zod.string(),
})

export const hogFlowsSchedulesPartialUpdateBodyTimezoneMax = 64

export const HogFlowsSchedulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    rrule: zod
        .string()
        .optional()
        .describe(
            "iCalendar RRULE string (e.g. 'FREQ=DAILY;INTERVAL=1'). Must produce occurrences at most once per hour."
        ),
    starts_at: zod.iso.datetime({ offset: true }).optional().describe('ISO 8601 datetime the schedule starts from.'),
    timezone: zod
        .string()
        .max(hogFlowsSchedulesPartialUpdateBodyTimezoneMax)
        .optional()
        .describe("IANA timezone for interpreting the RRULE (default 'UTC')."),
    variables: zod
        .unknown()
        .optional()
        .describe('Variable value overrides merged with the workflow defaults on each run.'),
})
