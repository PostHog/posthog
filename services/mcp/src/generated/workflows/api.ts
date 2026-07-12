/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 13 enabled ops
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

export const hogFlowsCreateBodyConversionOneEventsItemFiltersOneSourceDefault = `events`
export const hogFlowsCreateBodyActionsItemNameMax = 400

export const hogFlowsCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsCreateBodyActionsItemTypeMax = 100

export const hogFlowsCreateBodyActionsItemConfigTwoConditionFiltersOneSourceDefault = `events`
export const hogFlowsCreateBodyActionsItemConfigTwoEventsItemFiltersOneSourceDefault = `events`

export const HogFlowsCreateBody = /* @__PURE__ */ zod
    .object({
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
                        .describe('Seconds (60 to ~94M / 3y) to suppress repeat firings of the same hash.'),
                    threshold: zod
                        .number()
                        .nullish()
                        .describe(
                            'Fire once per N matches of the same hash within ttl — a sampler: N=3 fires on the 1st, 4th, 7th… match. Omit to fire on the first match, then suppress repeats within ttl.'
                        ),
                    hash: zod
                        .string()
                        .describe(
                            "HogQL template defining the dedup/grouping key, e.g. '{person.id}' (once per person) within ttl."
                        ),
                    bytecode: zod.unknown().optional().describe('Auto-compiled from hash. Do not set.'),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                "Optional dedup/throttle on an already-matched trigger: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Without threshold: fire once per hash, then suppress repeats within ttl (hash '{person.id}' = once per person per ttl). With threshold N: fire once per N matches of the same hash — a sampler, the 1st then every Nth. Throttles an already-qualifying trigger; it doesn't decide who enters. Server compiles bytecode from hash; omit to disable."
            ),
        conversion: zod
            .union([
                zod.object({
                    filters: zod
                        .array(zod.record(zod.string(), zod.unknown()))
                        .optional()
                        .describe(
                            "Property-based conversion conditions, as an ARRAY of property filters: [{key, value, operator, type: event|person|group}, ...]. Event-based goals do NOT go here — put them in 'events'. Empty array = any event within the window converts."
                        ),
                    events: zod
                        .array(
                            zod.object({
                                filters: zod
                                    .object({
                                        source: zod
                                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                                            .describe(
                                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                            )
                                            .default(hogFlowsCreateBodyConversionOneEventsItemFiltersOneSourceDefault),
                                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                        bytecode: zod.unknown().optional(),
                                        transpiled: zod.unknown().optional(),
                                        filter_test_accounts: zod.boolean().optional(),
                                        bytecode_error: zod.string().optional(),
                                    })
                                    .describe(
                                        "Event/action filters for this conversion event, same shape as trigger filters: {events: [{id, name, type: 'events', properties?: [<cond>]}], actions?: [...], properties?: [<cond>]}. bytecode is compiled server-side."
                                    ),
                            })
                        )
                        .optional()
                        .describe(
                            "Event-based conversion goals: [{filters: {events: [{id, name, type: 'events'}], ...}}]."
                        ),
                    window_minutes: zod
                        .number()
                        .nullish()
                        .describe(
                            'Conversion window in minutes after a person enters the workflow. null = no explicit window.'
                        ),
                    bytecode: zod
                        .unknown()
                        .optional()
                        .describe("Compiled server-side from 'filters'. Do not set; ignored if sent."),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                'Conversion goal. filters: ARRAY of property conditions [{key, value, operator, type: event|person|group}]; events: event-based goals [{filters: {events: [...]}}]; window_minutes: minutes after entry. Required for exit_on_conversion / exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side.'
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
                            "Required for type='branch'. conditional_branch: index into config.conditions[index]. wait_until_condition: use index:0 — it advances via the index:0 branch edge when it resolves (a condition match or an events entry firing)."
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
                            zod.enum(['continue', 'abort']).describe('* `continue` - continue\n* `abort` - abort'),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'On failure: continue (skip the action and proceed) or abort (stop the run).\n\n* `continue` - continue\n* `abort` - abort'
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
                            'trigger | function | function_email | function_sms | delay | conditional_branch | wait_until_condition | wait_until_time_window | random_cohort_branch | exit.'
                        ),
                    config: zod
                        .union([
                            zod
                                .record(zod.string(), zod.unknown())
                                .describe(
                                    'Config for every action type except wait_until_condition — see the field description for per-type shapes.'
                                ),
                            zod
                                .object({
                                    condition: zod
                                        .object({
                                            filters: zod
                                                .union([
                                                    zod.object({
                                                        source: zod
                                                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                                                            .describe(
                                                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                                            )
                                                            .default(
                                                                hogFlowsCreateBodyActionsItemConfigTwoConditionFiltersOneSourceDefault
                                                            ),
                                                        actions: zod
                                                            .array(zod.record(zod.string(), zod.unknown()))
                                                            .optional(),
                                                        events: zod
                                                            .array(zod.record(zod.string(), zod.unknown()))
                                                            .optional(),
                                                        data_warehouse: zod
                                                            .array(zod.record(zod.string(), zod.unknown()))
                                                            .optional(),
                                                        properties: zod
                                                            .array(zod.record(zod.string(), zod.unknown()))
                                                            .optional(),
                                                        bytecode: zod.unknown().optional(),
                                                        transpiled: zod.unknown().optional(),
                                                        filter_test_accounts: zod.boolean().optional(),
                                                        bytecode_error: zod.string().optional(),
                                                    }),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    'Property conditions, e.g. {properties: [{key, value, operator, type}]}.'
                                                ),
                                            name: zod.string().optional().describe('Optional display name.'),
                                        })
                                        .optional()
                                        .describe(
                                            "Property-based wait condition; continues when the person matches. A condition with no property filters is ignored — the wait then relies on 'events' and the max_wait_duration timeout."
                                        ),
                                    events: zod
                                        .array(
                                            zod.object({
                                                filters: zod
                                                    .union([
                                                        zod.object({
                                                            source: zod
                                                                .enum([
                                                                    'events',
                                                                    'person-updates',
                                                                    'data-warehouse-table',
                                                                ])
                                                                .describe(
                                                                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                                                )
                                                                .default(
                                                                    hogFlowsCreateBodyActionsItemConfigTwoEventsItemFiltersOneSourceDefault
                                                                ),
                                                            actions: zod
                                                                .array(zod.record(zod.string(), zod.unknown()))
                                                                .optional(),
                                                            events: zod
                                                                .array(zod.record(zod.string(), zod.unknown()))
                                                                .optional(),
                                                            data_warehouse: zod
                                                                .array(zod.record(zod.string(), zod.unknown()))
                                                                .optional(),
                                                            properties: zod
                                                                .array(zod.record(zod.string(), zod.unknown()))
                                                                .optional(),
                                                            bytecode: zod.unknown().optional(),
                                                            transpiled: zod.unknown().optional(),
                                                            filter_test_accounts: zod.boolean().optional(),
                                                            bytecode_error: zod.string().optional(),
                                                        }),
                                                        zod.null(),
                                                    ])
                                                    .optional()
                                                    .describe(
                                                        'Event/action filters; the workflow wakes when a matching event fires. Must target at least one event or action (entries targeting neither are dropped).'
                                                    ),
                                                name: zod.string().optional().describe('Optional display name.'),
                                            })
                                        )
                                        .optional()
                                        .describe(
                                            "Events to wait for: continues when ANY entry fires (OR'd with 'condition'). Each entry: {filters: {events: [{id, name, type: 'events'}], actions?: [...]}, name?}."
                                        ),
                                    max_wait_duration: zod
                                        .string()
                                        .describe(
                                            "'<number><unit>' with unit m|h|d, e.g. '30m' (same rules as delay)."
                                        ),
                                })
                                .describe(
                                    "Config for type='wait_until_condition'. Provide 'condition' and/or 'events' — an events-only wait (no condition) is valid."
                                ),
                        ])
                        .describe(
                            "Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}. function*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. Dictionary input values are template strings too — write booleans/numbers as single-expression templates ('{true}', '{42}'), which evaluate to the typed value. delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. wait_until_condition: {condition: {filters}, events?: [{filters: {events: [{id, name, type: 'events'}], actions?: [...]}, name?}], max_wait_duration: <duration>} (same rules as delay). Continues when condition.filters match OR any events entry fires; each events entry must target at least one event or action. On resolution (a condition match or any events entry firing) it advances via the 'branch' edge with index:0; the max_wait_duration timeout falls through the 'continue' edge. exit: {reason}."
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
                zod
                    .record(zod.string(), zod.string())
                    .describe('Variable: {key, type: string|number|boolean, default}.')
            )
            .optional()
            .describe('Workflow vars (key, type, default). Total <5KB.'),
    })
    .describe('Mixin for serializers to add user access control fields')

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

export const hogFlowsPartialUpdateBodyConversionOneEventsItemFiltersOneSourceDefault = `events`
export const hogFlowsPartialUpdateBodyActionsItemNameMax = 400

export const hogFlowsPartialUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowsPartialUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsPartialUpdateBodyActionsItemTypeMax = 100

export const hogFlowsPartialUpdateBodyActionsItemConfigTwoConditionFiltersOneSourceDefault = `events`
export const hogFlowsPartialUpdateBodyActionsItemConfigTwoEventsItemFiltersOneSourceDefault = `events`

export const HogFlowsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
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
                        .describe('Seconds (60 to ~94M / 3y) to suppress repeat firings of the same hash.'),
                    threshold: zod
                        .number()
                        .nullish()
                        .describe(
                            'Fire once per N matches of the same hash within ttl — a sampler: N=3 fires on the 1st, 4th, 7th… match. Omit to fire on the first match, then suppress repeats within ttl.'
                        ),
                    hash: zod
                        .string()
                        .describe(
                            "HogQL template defining the dedup/grouping key, e.g. '{person.id}' (once per person) within ttl."
                        ),
                    bytecode: zod.unknown().optional().describe('Auto-compiled from hash. Do not set.'),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                "Optional dedup/throttle on an already-matched trigger: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Without threshold: fire once per hash, then suppress repeats within ttl (hash '{person.id}' = once per person per ttl). With threshold N: fire once per N matches of the same hash — a sampler, the 1st then every Nth. Throttles an already-qualifying trigger; it doesn't decide who enters. Server compiles bytecode from hash; omit to disable."
            ),
        conversion: zod
            .union([
                zod.object({
                    filters: zod
                        .array(zod.record(zod.string(), zod.unknown()))
                        .optional()
                        .describe(
                            "Property-based conversion conditions, as an ARRAY of property filters: [{key, value, operator, type: event|person|group}, ...]. Event-based goals do NOT go here — put them in 'events'. Empty array = any event within the window converts."
                        ),
                    events: zod
                        .array(
                            zod.object({
                                filters: zod
                                    .object({
                                        source: zod
                                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                                            .describe(
                                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                            )
                                            .default(
                                                hogFlowsPartialUpdateBodyConversionOneEventsItemFiltersOneSourceDefault
                                            ),
                                        actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                        events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                        data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                        properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
                                        bytecode: zod.unknown().optional(),
                                        transpiled: zod.unknown().optional(),
                                        filter_test_accounts: zod.boolean().optional(),
                                        bytecode_error: zod.string().optional(),
                                    })
                                    .describe(
                                        "Event/action filters for this conversion event, same shape as trigger filters: {events: [{id, name, type: 'events', properties?: [<cond>]}], actions?: [...], properties?: [<cond>]}. bytecode is compiled server-side."
                                    ),
                            })
                        )
                        .optional()
                        .describe(
                            "Event-based conversion goals: [{filters: {events: [{id, name, type: 'events'}], ...}}]."
                        ),
                    window_minutes: zod
                        .number()
                        .nullish()
                        .describe(
                            'Conversion window in minutes after a person enters the workflow. null = no explicit window.'
                        ),
                    bytecode: zod
                        .unknown()
                        .optional()
                        .describe("Compiled server-side from 'filters'. Do not set; ignored if sent."),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                'Conversion goal. filters: ARRAY of property conditions [{key, value, operator, type: event|person|group}]; events: event-based goals [{filters: {events: [...]}}]; window_minutes: minutes after entry. Required for exit_on_conversion / exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side.'
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
                            "Required for type='branch'. conditional_branch: index into config.conditions[index]. wait_until_condition: use index:0 — it advances via the index:0 branch edge when it resolves (a condition match or an events entry firing)."
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
                            zod.enum(['continue', 'abort']).describe('* `continue` - continue\n* `abort` - abort'),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'On failure: continue (skip the action and proceed) or abort (stop the run).\n\n* `continue` - continue\n* `abort` - abort'
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
                            'trigger | function | function_email | function_sms | delay | conditional_branch | wait_until_condition | wait_until_time_window | random_cohort_branch | exit.'
                        ),
                    config: zod
                        .union([
                            zod
                                .record(zod.string(), zod.unknown())
                                .describe(
                                    'Config for every action type except wait_until_condition — see the field description for per-type shapes.'
                                ),
                            zod
                                .object({
                                    condition: zod
                                        .object({
                                            filters: zod
                                                .union([
                                                    zod.object({
                                                        source: zod
                                                            .enum(['events', 'person-updates', 'data-warehouse-table'])
                                                            .describe(
                                                                '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                                            )
                                                            .default(
                                                                hogFlowsPartialUpdateBodyActionsItemConfigTwoConditionFiltersOneSourceDefault
                                                            ),
                                                        actions: zod
                                                            .array(zod.record(zod.string(), zod.unknown()))
                                                            .optional(),
                                                        events: zod
                                                            .array(zod.record(zod.string(), zod.unknown()))
                                                            .optional(),
                                                        data_warehouse: zod
                                                            .array(zod.record(zod.string(), zod.unknown()))
                                                            .optional(),
                                                        properties: zod
                                                            .array(zod.record(zod.string(), zod.unknown()))
                                                            .optional(),
                                                        bytecode: zod.unknown().optional(),
                                                        transpiled: zod.unknown().optional(),
                                                        filter_test_accounts: zod.boolean().optional(),
                                                        bytecode_error: zod.string().optional(),
                                                    }),
                                                    zod.null(),
                                                ])
                                                .optional()
                                                .describe(
                                                    'Property conditions, e.g. {properties: [{key, value, operator, type}]}.'
                                                ),
                                            name: zod.string().optional().describe('Optional display name.'),
                                        })
                                        .optional()
                                        .describe(
                                            "Property-based wait condition; continues when the person matches. A condition with no property filters is ignored — the wait then relies on 'events' and the max_wait_duration timeout."
                                        ),
                                    events: zod
                                        .array(
                                            zod.object({
                                                filters: zod
                                                    .union([
                                                        zod.object({
                                                            source: zod
                                                                .enum([
                                                                    'events',
                                                                    'person-updates',
                                                                    'data-warehouse-table',
                                                                ])
                                                                .describe(
                                                                    '* `events` - events\n* `person-updates` - person-updates\n* `data-warehouse-table` - data-warehouse-table'
                                                                )
                                                                .default(
                                                                    hogFlowsPartialUpdateBodyActionsItemConfigTwoEventsItemFiltersOneSourceDefault
                                                                ),
                                                            actions: zod
                                                                .array(zod.record(zod.string(), zod.unknown()))
                                                                .optional(),
                                                            events: zod
                                                                .array(zod.record(zod.string(), zod.unknown()))
                                                                .optional(),
                                                            data_warehouse: zod
                                                                .array(zod.record(zod.string(), zod.unknown()))
                                                                .optional(),
                                                            properties: zod
                                                                .array(zod.record(zod.string(), zod.unknown()))
                                                                .optional(),
                                                            bytecode: zod.unknown().optional(),
                                                            transpiled: zod.unknown().optional(),
                                                            filter_test_accounts: zod.boolean().optional(),
                                                            bytecode_error: zod.string().optional(),
                                                        }),
                                                        zod.null(),
                                                    ])
                                                    .optional()
                                                    .describe(
                                                        'Event/action filters; the workflow wakes when a matching event fires. Must target at least one event or action (entries targeting neither are dropped).'
                                                    ),
                                                name: zod.string().optional().describe('Optional display name.'),
                                            })
                                        )
                                        .optional()
                                        .describe(
                                            "Events to wait for: continues when ANY entry fires (OR'd with 'condition'). Each entry: {filters: {events: [{id, name, type: 'events'}], actions?: [...]}, name?}."
                                        ),
                                    max_wait_duration: zod
                                        .string()
                                        .describe(
                                            "'<number><unit>' with unit m|h|d, e.g. '30m' (same rules as delay)."
                                        ),
                                })
                                .describe(
                                    "Config for type='wait_until_condition'. Provide 'condition' and/or 'events' — an events-only wait (no condition) is valid."
                                ),
                        ])
                        .describe(
                            "Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}. function*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. Dictionary input values are template strings too — write booleans/numbers as single-expression templates ('{true}', '{42}'), which evaluate to the typed value. delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. wait_until_condition: {condition: {filters}, events?: [{filters: {events: [{id, name, type: 'events'}], actions?: [...]}, name?}], max_wait_duration: <duration>} (same rules as delay). Continues when condition.filters match OR any events entry fires; each events entry must target at least one event or action. On resolution (a condition match or any events entry firing) it advances via the 'branch' edge with index:0; the max_wait_duration timeout falls through the 'continue' edge. exit: {reason}."
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
                zod
                    .record(zod.string(), zod.string())
                    .describe('Variable: {key, type: string|number|boolean, default}.')
            )
            .optional()
            .describe('Workflow vars (key, type, default). Total <5KB.'),
    })
    .describe('Mixin for serializers to add user access control fields')

export const HogFlowsBatchJobsListParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowsGraphPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const HogFlowsGraphPartialUpdateBody = /* @__PURE__ */ zod.object({
    operations: zod
        .array(
            zod.object({
                op: zod
                    .enum([
                        'update_action',
                        'add_action',
                        'remove_action',
                        'add_edge',
                        'remove_edge',
                        'replace_action_edges',
                    ])
                    .describe(
                        '* `update_action` - update_action\n* `add_action` - add_action\n* `remove_action` - remove_action\n* `add_edge` - add_edge\n* `remove_edge` - remove_edge\n* `replace_action_edges` - replace_action_edges'
                    )
                    .describe(
                        "Graph edit. update_action {id, patch}: deep-merge patch into the action's fields (a null leaf deletes that key) — the surgical path for tweaking one config value. add_action {action}: append a full action node. remove_action {id}: delete a node and reconnect its incoming edges to its first outgoer. add_edge {edge} / remove_edge {edge}: add or delete one edge. replace_action_edges {id, edges}: replace this action's outgoing edges with the given set (use when adding/removing branch conditions); incoming edges are left intact.\n\n* `update_action` - update_action\n* `add_action` - add_action\n* `remove_action` - remove_action\n* `add_edge` - add_edge\n* `remove_edge` - remove_edge\n* `replace_action_edges` - replace_action_edges"
                    ),
                id: zod
                    .string()
                    .optional()
                    .describe('Action id. Required for update_action, remove_action, replace_action_edges.'),
                patch: zod
                    .unknown()
                    .optional()
                    .describe(
                        "update_action only. Partial action fields, deep-merged into the existing action; a null leaf deletes that key. e.g. {config: {inputs: {subject: {value: 'Hi'}}}} changes only that input."
                    ),
                action: zod
                    .unknown()
                    .optional()
                    .describe(
                        'add_action only. A full action node {id, name, type, config, ...}; same shape as in actions.'
                    ),
                edge: zod
                    .object({
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
                                "Required for type='branch'. conditional_branch: index into config.conditions[index]. wait_until_condition: use index:0 — it advances via the index:0 branch edge when it resolves (a condition match or an events entry firing)."
                            ),
                        from: zod.string().describe('Source action id.'),
                    })
                    .optional()
                    .describe('add_edge / remove_edge only. The edge {from, to, type, index?}.'),
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
                                    "Required for type='branch'. conditional_branch: index into config.conditions[index]. wait_until_condition: use index:0 — it advances via the index:0 branch edge when it resolves (a condition match or an events entry firing)."
                                ),
                            from: zod.string().describe('Source action id.'),
                        })
                    )
                    .optional()
                    .describe(
                        "replace_action_edges only. The complete set of the action's outgoing edges; incoming edges are preserved."
                    ),
            })
        )
        .optional()
        .describe(
            "Ordered graph edits applied atomically to a draft workflow: the stored graph is read, the ops are applied in order, the result is fully validated, and it's saved only if valid — otherwise the workflow is unchanged. Reference nodes/edges by id so you never resend the whole graph. The full updated workflow is returned."
        ),
})

export const HogFlowsInvocationResultsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsInvocationResultsRetrieveQueryAfterDefault = `-7d`

export const hogFlowsInvocationResultsRetrieveQueryLimitDefault = 50
export const hogFlowsInvocationResultsRetrieveQueryLimitMax = 500

export const HogFlowsInvocationResultsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    after: zod
        .string()
        .min(1)
        .default(hogFlowsInvocationResultsRetrieveQueryAfterDefault)
        .describe(
            "Start of the time range, matched on scheduled time. Relative ('-7d', '-24h') or ISO 8601. Defaults to -7d — bounds the ClickHouse partition scan, so widen it explicitly for older runs."
        ),
    before: zod
        .string()
        .min(1)
        .optional()
        .describe("End of the time range, matched on scheduled time. Same format as 'after'. Defaults to now."),
    distinct_id: zod
        .string()
        .min(1)
        .optional()
        .describe('Only return invocations triggered for this distinct_id (the person the run executed for).'),
    limit: zod
        .number()
        .min(1)
        .max(hogFlowsInvocationResultsRetrieveQueryLimitMax)
        .default(hogFlowsInvocationResultsRetrieveQueryLimitDefault)
        .describe('Maximum number of invocations to return (1-500, default 50).'),
    status: zod
        .string()
        .min(1)
        .optional()
        .describe("Comma-separated invocation statuses to include, e.g. 'failed' or 'success,failed'."),
})

export const HogFlowsInvocationResultRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    invocation_id: zod.string(),
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
    current_action_id: zod
        .string()
        .optional()
        .describe(
            'Start execution from this action ID instead of the trigger. Each test run executes a single node and returns the next action id.'
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

export const HogFlowsMetricsGlobalRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const hogFlowsMetricsGlobalRetrieveQueryAfterDefault = `-7d`

export const HogFlowsMetricsGlobalRetrieveQueryParams = /* @__PURE__ */ zod.object({
    after: zod
        .string()
        .min(1)
        .default(hogFlowsMetricsGlobalRetrieveQueryAfterDefault)
        .describe(
            "Start of the window, matched on metric time. Relative ('-7d', '-24h') or ISO 8601. Defaults to -7d."
        ),
    before: zod.string().min(1).optional().describe("End of the window. Same format as 'after'. Defaults to now."),
})
