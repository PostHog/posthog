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

export const hogFlowTemplatesCreateBodyNameMax = 400

export const hogFlowTemplatesCreateBodyImageUrlMax = 8201

export const hogFlowTemplatesCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesCreateBodyActionsItemNameMax = 400

export const hogFlowTemplatesCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowTemplatesCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesCreateBodyActionsItemTypeMax = 100

export const hogFlowTemplatesCreateBodyAbortActionMax = 400

export const HogFlowTemplatesCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(hogFlowTemplatesCreateBodyNameMax),
        description: zod.string().optional(),
        image_url: zod.string().max(hogFlowTemplatesCreateBodyImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: zod
            .enum(['team', 'organization', 'global'])
            .describe('\* `team` - Only team\n\* `organization` - Organization\n\* `global` - Global'),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .union([
                zod.object({
                    ttl: zod
                        .number()
                        .min(hogFlowTemplatesCreateBodyTriggerMaskingOneTtlMin)
                        .max(hogFlowTemplatesCreateBodyTriggerMaskingOneTtlMax)
                        .nullish()
                        .describe('Seconds (60 to ~94M \/ 3y) to suppress repeat firings of the same hash.'),
                    threshold: zod
                        .number()
                        .nullish()
                        .describe(
                            'Fire once per N matches of the same hash within ttl — a sampler: N=3 fires on the 1st, 4th, 7th… match. Omit to fire on the first match, then suppress repeats within ttl.'
                        ),
                    hash: zod
                        .string()
                        .describe(
                            "HogQL template defining the dedup\/grouping key, e.g. '{person.id}' (once per person) within ttl."
                        ),
                    bytecode: zod.unknown().optional().describe('Auto-compiled from hash. Do not set.'),
                }),
                zod.null(),
            ])
            .optional(),
        conversion: zod.unknown().optional(),
        exit_condition: zod
            .enum([
                'exit_on_conversion',
                'exit_on_trigger_not_matched',
                'exit_on_trigger_not_matched_or_conversion',
                'exit_only_at_end',
            ])
            .optional()
            .describe(
                '\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End'
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
                                    '\* `continue` - continue\n\* `abort` - abort\n\* `complete` - complete\n\* `branch` - branch'
                                ),
                            zod.null(),
                        ])
                        .optional(),
                    created_at: zod.number().optional(),
                    updated_at: zod.number().optional(),
                    filters: zod
                        .union([
                            zod.object({
                                source: zod
                                    .enum(['events', 'person-updates', 'data-warehouse-table'])
                                    .describe(
                                        '\* `events` - events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table'
                                    )
                                    .default(hogFlowTemplatesCreateBodyActionsItemFiltersOneSourceDefault),
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
                        .optional(),
                    type: zod.string().max(hogFlowTemplatesCreateBodyActionsItemTypeMax),
                    config: zod.unknown(),
                    output_variable: zod.unknown().optional(),
                })
                .describe(
                    'Custom action serializer for templates that skips input validation\n(since templates should have default\/empty values).'
                )
        ),
        abort_action: zod.string().max(hogFlowTemplatesCreateBodyAbortActionMax).nullish(),
        variables: zod
            .array(
                zod
                    .record(zod.string(), zod.string())
                    .describe('Variable: {key, type: string|number|boolean, default}.')
            )
            .optional(),
    })
    .describe(
        'Serializer for creating hog flow templates.\nValidates and sanitizes the workflow before creating it as a template.'
    )

export const hogFlowTemplatesUpdateBodyNameMax = 400

export const hogFlowTemplatesUpdateBodyImageUrlMax = 8201

export const hogFlowTemplatesUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesUpdateBodyActionsItemNameMax = 400

export const hogFlowTemplatesUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowTemplatesUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesUpdateBodyActionsItemTypeMax = 100

export const hogFlowTemplatesUpdateBodyAbortActionMax = 400

export const HogFlowTemplatesUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(hogFlowTemplatesUpdateBodyNameMax),
        description: zod.string().optional(),
        image_url: zod.string().max(hogFlowTemplatesUpdateBodyImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: zod
            .enum(['team', 'organization', 'global'])
            .describe('\* `team` - Only team\n\* `organization` - Organization\n\* `global` - Global'),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .union([
                zod.object({
                    ttl: zod
                        .number()
                        .min(hogFlowTemplatesUpdateBodyTriggerMaskingOneTtlMin)
                        .max(hogFlowTemplatesUpdateBodyTriggerMaskingOneTtlMax)
                        .nullish()
                        .describe('Seconds (60 to ~94M \/ 3y) to suppress repeat firings of the same hash.'),
                    threshold: zod
                        .number()
                        .nullish()
                        .describe(
                            'Fire once per N matches of the same hash within ttl — a sampler: N=3 fires on the 1st, 4th, 7th… match. Omit to fire on the first match, then suppress repeats within ttl.'
                        ),
                    hash: zod
                        .string()
                        .describe(
                            "HogQL template defining the dedup\/grouping key, e.g. '{person.id}' (once per person) within ttl."
                        ),
                    bytecode: zod.unknown().optional().describe('Auto-compiled from hash. Do not set.'),
                }),
                zod.null(),
            ])
            .optional(),
        conversion: zod.unknown().optional(),
        exit_condition: zod
            .enum([
                'exit_on_conversion',
                'exit_on_trigger_not_matched',
                'exit_on_trigger_not_matched_or_conversion',
                'exit_only_at_end',
            ])
            .optional()
            .describe(
                '\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End'
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
                                    '\* `continue` - continue\n\* `abort` - abort\n\* `complete` - complete\n\* `branch` - branch'
                                ),
                            zod.null(),
                        ])
                        .optional(),
                    created_at: zod.number().optional(),
                    updated_at: zod.number().optional(),
                    filters: zod
                        .union([
                            zod.object({
                                source: zod
                                    .enum(['events', 'person-updates', 'data-warehouse-table'])
                                    .describe(
                                        '\* `events` - events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table'
                                    )
                                    .default(hogFlowTemplatesUpdateBodyActionsItemFiltersOneSourceDefault),
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
                        .optional(),
                    type: zod.string().max(hogFlowTemplatesUpdateBodyActionsItemTypeMax),
                    config: zod.unknown(),
                    output_variable: zod.unknown().optional(),
                })
                .describe(
                    'Custom action serializer for templates that skips input validation\n(since templates should have default\/empty values).'
                )
        ),
        abort_action: zod.string().max(hogFlowTemplatesUpdateBodyAbortActionMax).nullish(),
        variables: zod
            .array(
                zod
                    .record(zod.string(), zod.string())
                    .describe('Variable: {key, type: string|number|boolean, default}.')
            )
            .optional(),
    })
    .describe(
        'Serializer for creating hog flow templates.\nValidates and sanitizes the workflow before creating it as a template.'
    )

export const hogFlowTemplatesPartialUpdateBodyNameMax = 400

export const hogFlowTemplatesPartialUpdateBodyImageUrlMax = 8201

export const hogFlowTemplatesPartialUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesPartialUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesPartialUpdateBodyActionsItemNameMax = 400

export const hogFlowTemplatesPartialUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowTemplatesPartialUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesPartialUpdateBodyActionsItemTypeMax = 100

export const hogFlowTemplatesPartialUpdateBodyAbortActionMax = 400

export const HogFlowTemplatesPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(hogFlowTemplatesPartialUpdateBodyNameMax).optional(),
        description: zod.string().optional(),
        image_url: zod.string().max(hogFlowTemplatesPartialUpdateBodyImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: zod
            .enum(['team', 'organization', 'global'])
            .optional()
            .describe('\* `team` - Only team\n\* `organization` - Organization\n\* `global` - Global'),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .union([
                zod.object({
                    ttl: zod
                        .number()
                        .min(hogFlowTemplatesPartialUpdateBodyTriggerMaskingOneTtlMin)
                        .max(hogFlowTemplatesPartialUpdateBodyTriggerMaskingOneTtlMax)
                        .nullish()
                        .describe('Seconds (60 to ~94M \/ 3y) to suppress repeat firings of the same hash.'),
                    threshold: zod
                        .number()
                        .nullish()
                        .describe(
                            'Fire once per N matches of the same hash within ttl — a sampler: N=3 fires on the 1st, 4th, 7th… match. Omit to fire on the first match, then suppress repeats within ttl.'
                        ),
                    hash: zod
                        .string()
                        .describe(
                            "HogQL template defining the dedup\/grouping key, e.g. '{person.id}' (once per person) within ttl."
                        ),
                    bytecode: zod.unknown().optional().describe('Auto-compiled from hash. Do not set.'),
                }),
                zod.null(),
            ])
            .optional(),
        conversion: zod.unknown().optional(),
        exit_condition: zod
            .enum([
                'exit_on_conversion',
                'exit_on_trigger_not_matched',
                'exit_on_trigger_not_matched_or_conversion',
                'exit_only_at_end',
            ])
            .optional()
            .describe(
                '\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End'
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
                                        '\* `continue` - continue\n\* `abort` - abort\n\* `complete` - complete\n\* `branch` - branch'
                                    ),
                                zod.null(),
                            ])
                            .optional(),
                        created_at: zod.number().optional(),
                        updated_at: zod.number().optional(),
                        filters: zod
                            .union([
                                zod.object({
                                    source: zod
                                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                                        .describe(
                                            '\* `events` - events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table'
                                        )
                                        .default(hogFlowTemplatesPartialUpdateBodyActionsItemFiltersOneSourceDefault),
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
                            .optional(),
                        type: zod.string().max(hogFlowTemplatesPartialUpdateBodyActionsItemTypeMax),
                        config: zod.unknown(),
                        output_variable: zod.unknown().optional(),
                    })
                    .describe(
                        'Custom action serializer for templates that skips input validation\n(since templates should have default\/empty values).'
                    )
            )
            .optional(),
        abort_action: zod.string().max(hogFlowTemplatesPartialUpdateBodyAbortActionMax).nullish(),
        variables: zod
            .array(
                zod
                    .record(zod.string(), zod.string())
                    .describe('Variable: {key, type: string|number|boolean, default}.')
            )
            .optional(),
    })
    .describe(
        'Serializer for creating hog flow templates.\nValidates and sanitizes the workflow before creating it as a template.'
    )

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
        .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived')
        .optional()
        .describe(
            'draft (no execution), active (live), archived (disabled).\n\n\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'
        ),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsCreateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsCreateBodyTriggerMaskingOneTtlMax)
                    .nullish()
                    .describe('Seconds (60 to ~94M \/ 3y) to suppress repeat firings of the same hash.'),
                threshold: zod
                    .number()
                    .nullish()
                    .describe(
                        'Fire once per N matches of the same hash within ttl — a sampler: N=3 fires on the 1st, 4th, 7th… match. Omit to fire on the first match, then suppress repeats within ttl.'
                    ),
                hash: zod
                    .string()
                    .describe(
                        "HogQL template defining the dedup\/grouping key, e.g. '{person.id}' (once per person) within ttl."
                    ),
                bytecode: zod.unknown().optional().describe('Auto-compiled from hash. Do not set.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            "Optional dedup\/throttle on an already-matched trigger: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Without threshold: fire once per hash, then suppress repeats within ttl (hash '{person.id}' = once per person per ttl). With threshold N: fire once per N matches of the same hash — a sampler, the 1st then every Nth. Throttles an already-qualifying trigger; it doesn't decide who enters. Server compiles bytecode from hash; omit to disable."
        ),
    conversion: zod
        .unknown()
        .optional()
        .describe(
            'Conversion goal: {filters: [<cond>, ...], window_minutes}. <cond>: {key, value, operator, type: event|person|group}. Empty filters = any event in window. Required for exit_on_conversion \/ exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side.'
        ),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .describe(
            '\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End'
        )
        .optional()
        .describe(
            "exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion').\n\n\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End"
        ),
    edges: zod
        .array(
            zod.object({
                to: zod.string().describe('Target action id.'),
                type: zod
                    .enum(['continue', 'branch'])
                    .describe('\* `continue` - continue\n\* `branch` - branch')
                    .describe(
                        "continue: fall-through (sequential or the no-match path of conditional_branch). branch: requires 'index' matching config.conditions[index].\n\n\* `continue` - continue\n\* `branch` - branch"
                    ),
                index: zod
                    .number()
                    .optional()
                    .describe(
                        "Required for type='branch'. Index into config.conditions on conditional_branch \/ wait_until_condition."
                    ),
                from: zod.string().describe('Source action id.'),
            })
        )
        .optional()
        .describe(
            "Graph edges: [{from, to, type: 'continue'|'branch', index?}]. 'continue' = fall-through (sequential, or no-match path of conditional_branch). 'branch' requires 'index': matches config.conditions[index] on conditional_branch \/ wait_until_condition. Every non-exit action needs a reachable next action ('No next action found' otherwise)."
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
                                '\* `continue` - continue\n\* `abort` - abort\n\* `complete` - complete\n\* `branch` - branch'
                            ),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        'On failure: continue (skip), abort (stop), complete (mark done), branch (follow error edge).\n\n\* `continue` - continue\n\* `abort` - abort\n\* `complete` - complete\n\* `branch` - branch'
                    ),
                created_at: zod.number().optional().describe('Created at (epoch ms). Frontend-managed.'),
                updated_at: zod.number().optional().describe('Updated at (epoch ms). Frontend-managed.'),
                filters: zod
                    .union([
                        zod.object({
                            source: zod
                                .enum(['events', 'person-updates', 'data-warehouse-table'])
                                .describe(
                                    '\* `events` - events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table'
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
                        "Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}. function\*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. wait_until_condition: {condition: {filters}, max_wait_duration: <duration>} (same rules as delay). exit: {reason}."
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

export const hogFlowsUpdateBodyNameMax = 400

export const hogFlowsUpdateBodyDescriptionDefault = ``
export const hogFlowsUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsUpdateBodyActionsItemNameMax = 400

export const hogFlowsUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowsUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsUpdateBodyActionsItemTypeMax = 100

export const HogFlowsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsUpdateBodyNameMax).nullish().describe('Workflow name.'),
    description: zod.string().default(hogFlowsUpdateBodyDescriptionDefault).describe('Optional description.'),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived')
        .optional()
        .describe(
            'draft (no execution), active (live), archived (disabled).\n\n\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'
        ),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsUpdateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsUpdateBodyTriggerMaskingOneTtlMax)
                    .nullish()
                    .describe('Seconds (60 to ~94M \/ 3y) to suppress repeat firings of the same hash.'),
                threshold: zod
                    .number()
                    .nullish()
                    .describe(
                        'Fire once per N matches of the same hash within ttl — a sampler: N=3 fires on the 1st, 4th, 7th… match. Omit to fire on the first match, then suppress repeats within ttl.'
                    ),
                hash: zod
                    .string()
                    .describe(
                        "HogQL template defining the dedup\/grouping key, e.g. '{person.id}' (once per person) within ttl."
                    ),
                bytecode: zod.unknown().optional().describe('Auto-compiled from hash. Do not set.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            "Optional dedup\/throttle on an already-matched trigger: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Without threshold: fire once per hash, then suppress repeats within ttl (hash '{person.id}' = once per person per ttl). With threshold N: fire once per N matches of the same hash — a sampler, the 1st then every Nth. Throttles an already-qualifying trigger; it doesn't decide who enters. Server compiles bytecode from hash; omit to disable."
        ),
    conversion: zod
        .unknown()
        .optional()
        .describe(
            'Conversion goal: {filters: [<cond>, ...], window_minutes}. <cond>: {key, value, operator, type: event|person|group}. Empty filters = any event in window. Required for exit_on_conversion \/ exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side.'
        ),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .describe(
            '\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End'
        )
        .optional()
        .describe(
            "exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion').\n\n\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End"
        ),
    edges: zod
        .array(
            zod.object({
                to: zod.string().describe('Target action id.'),
                type: zod
                    .enum(['continue', 'branch'])
                    .describe('\* `continue` - continue\n\* `branch` - branch')
                    .describe(
                        "continue: fall-through (sequential or the no-match path of conditional_branch). branch: requires 'index' matching config.conditions[index].\n\n\* `continue` - continue\n\* `branch` - branch"
                    ),
                index: zod
                    .number()
                    .optional()
                    .describe(
                        "Required for type='branch'. Index into config.conditions on conditional_branch \/ wait_until_condition."
                    ),
                from: zod.string().describe('Source action id.'),
            })
        )
        .optional()
        .describe(
            "Graph edges: [{from, to, type: 'continue'|'branch', index?}]. 'continue' = fall-through (sequential, or no-match path of conditional_branch). 'branch' requires 'index': matches config.conditions[index] on conditional_branch \/ wait_until_condition. Every non-exit action needs a reachable next action ('No next action found' otherwise)."
        ),
    actions: zod
        .array(
            zod.object({
                id: zod.string().describe('Unique node ID within the workflow.'),
                name: zod.string().max(hogFlowsUpdateBodyActionsItemNameMax).describe('Display name.'),
                description: zod
                    .string()
                    .default(hogFlowsUpdateBodyActionsItemDescriptionDefault)
                    .describe('Optional description.'),
                on_error: zod
                    .union([
                        zod
                            .enum(['continue', 'abort', 'complete', 'branch'])
                            .describe(
                                '\* `continue` - continue\n\* `abort` - abort\n\* `complete` - complete\n\* `branch` - branch'
                            ),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        'On failure: continue (skip), abort (stop), complete (mark done), branch (follow error edge).\n\n\* `continue` - continue\n\* `abort` - abort\n\* `complete` - complete\n\* `branch` - branch'
                    ),
                created_at: zod.number().optional().describe('Created at (epoch ms). Frontend-managed.'),
                updated_at: zod.number().optional().describe('Updated at (epoch ms). Frontend-managed.'),
                filters: zod
                    .union([
                        zod.object({
                            source: zod
                                .enum(['events', 'person-updates', 'data-warehouse-table'])
                                .describe(
                                    '\* `events` - events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table'
                                )
                                .default(hogFlowsUpdateBodyActionsItemFiltersOneSourceDefault),
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
                    .max(hogFlowsUpdateBodyActionsItemTypeMax)
                    .describe(
                        'trigger | function | function_email | function_sms | function_push | delay | conditional_branch | wait_until_condition | wait_until_time_window | random_cohort_branch | exit.'
                    ),
                config: zod
                    .unknown()
                    .describe(
                        "Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}. function\*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. wait_until_condition: {condition: {filters}, max_wait_duration: <duration>} (same rules as delay). exit: {reason}."
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

export const hogFlowsPartialUpdateBodyNameMax = 400

export const hogFlowsPartialUpdateBodyDescriptionDefault = ``
export const hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsPartialUpdateBodyActionsItemNameMax = 400

export const hogFlowsPartialUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowsPartialUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsPartialUpdateBodyActionsItemTypeMax = 100

export const HogFlowsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsPartialUpdateBodyNameMax).nullish().describe('Workflow name.'),
    description: zod.string().default(hogFlowsPartialUpdateBodyDescriptionDefault).describe('Optional description.'),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived')
        .optional()
        .describe(
            'draft (no execution), active (live), archived (disabled).\n\n\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'
        ),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMax)
                    .nullish()
                    .describe('Seconds (60 to ~94M \/ 3y) to suppress repeat firings of the same hash.'),
                threshold: zod
                    .number()
                    .nullish()
                    .describe(
                        'Fire once per N matches of the same hash within ttl — a sampler: N=3 fires on the 1st, 4th, 7th… match. Omit to fire on the first match, then suppress repeats within ttl.'
                    ),
                hash: zod
                    .string()
                    .describe(
                        "HogQL template defining the dedup\/grouping key, e.g. '{person.id}' (once per person) within ttl."
                    ),
                bytecode: zod.unknown().optional().describe('Auto-compiled from hash. Do not set.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            "Optional dedup\/throttle on an already-matched trigger: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Without threshold: fire once per hash, then suppress repeats within ttl (hash '{person.id}' = once per person per ttl). With threshold N: fire once per N matches of the same hash — a sampler, the 1st then every Nth. Throttles an already-qualifying trigger; it doesn't decide who enters. Server compiles bytecode from hash; omit to disable."
        ),
    conversion: zod
        .unknown()
        .optional()
        .describe(
            'Conversion goal: {filters: [<cond>, ...], window_minutes}. <cond>: {key, value, operator, type: event|person|group}. Empty filters = any event in window. Required for exit_on_conversion \/ exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side.'
        ),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .describe(
            '\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End'
        )
        .optional()
        .describe(
            "exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion').\n\n\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End"
        ),
    edges: zod
        .array(
            zod.object({
                to: zod.string().describe('Target action id.'),
                type: zod
                    .enum(['continue', 'branch'])
                    .describe('\* `continue` - continue\n\* `branch` - branch')
                    .describe(
                        "continue: fall-through (sequential or the no-match path of conditional_branch). branch: requires 'index' matching config.conditions[index].\n\n\* `continue` - continue\n\* `branch` - branch"
                    ),
                index: zod
                    .number()
                    .optional()
                    .describe(
                        "Required for type='branch'. Index into config.conditions on conditional_branch \/ wait_until_condition."
                    ),
                from: zod.string().describe('Source action id.'),
            })
        )
        .optional()
        .describe(
            "Graph edges: [{from, to, type: 'continue'|'branch', index?}]. 'continue' = fall-through (sequential, or no-match path of conditional_branch). 'branch' requires 'index': matches config.conditions[index] on conditional_branch \/ wait_until_condition. Every non-exit action needs a reachable next action ('No next action found' otherwise)."
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
                                '\* `continue` - continue\n\* `abort` - abort\n\* `complete` - complete\n\* `branch` - branch'
                            ),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        'On failure: continue (skip), abort (stop), complete (mark done), branch (follow error edge).\n\n\* `continue` - continue\n\* `abort` - abort\n\* `complete` - complete\n\* `branch` - branch'
                    ),
                created_at: zod.number().optional().describe('Created at (epoch ms). Frontend-managed.'),
                updated_at: zod.number().optional().describe('Updated at (epoch ms). Frontend-managed.'),
                filters: zod
                    .union([
                        zod.object({
                            source: zod
                                .enum(['events', 'person-updates', 'data-warehouse-table'])
                                .describe(
                                    '\* `events` - events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table'
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
                        "Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}. function\*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. wait_until_condition: {condition: {filters}, max_wait_duration: <duration>} (same rules as delay). exit: {reason}."
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

export const HogFlowsBatchJobsCreateBody = /* @__PURE__ */ zod.object({
    status: zod
        .enum(['waiting', 'queued', 'active', 'completed', 'cancelled', 'failed'])
        .describe(
            '\* `waiting` - Waiting\n\* `queued` - Queued\n\* `active` - Active\n\* `completed` - Completed\n\* `cancelled` - Cancelled\n\* `failed` - Failed'
        )
        .optional()
        .describe(
            'Not currently tracked — stays at its initial value. Use the workflow logs\/metrics endpoints for run outcome.\n\n\* `waiting` - Waiting\n\* `queued` - Queued\n\* `active` - Active\n\* `completed` - Completed\n\* `cancelled` - Cancelled\n\* `failed` - Failed'
        ),
    hog_flow: zod.uuid().describe('ID of the workflow this batch run belongs to.'),
    filters: zod
        .unknown()
        .optional()
        .describe("Audience snapshot the run fanned out to, taken from the workflow's batch trigger filters."),
    variables: zod.unknown().optional().describe('Variable value overrides applied to this run.'),
})

export const hogFlowsInvocationsCreateBodyConfigurationOneNameMax = 400

export const hogFlowsInvocationsCreateBodyConfigurationOneDescriptionDefault = ``
export const hogFlowsInvocationsCreateBodyConfigurationOneCreatedByOneDistinctIdMax = 200

export const hogFlowsInvocationsCreateBodyConfigurationOneCreatedByOneFirstNameMax = 150

export const hogFlowsInvocationsCreateBodyConfigurationOneCreatedByOneLastNameMax = 150

export const hogFlowsInvocationsCreateBodyConfigurationOneCreatedByOneEmailMax = 254

export const hogFlowsInvocationsCreateBodyConfigurationOneTriggerMaskingOneTtlMin = 60
export const hogFlowsInvocationsCreateBodyConfigurationOneTriggerMaskingOneTtlMax = 94608000

export const hogFlowsInvocationsCreateBodyConfigurationOneActionsItemNameMax = 400

export const hogFlowsInvocationsCreateBodyConfigurationOneActionsItemDescriptionDefault = ``
export const hogFlowsInvocationsCreateBodyConfigurationOneActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsInvocationsCreateBodyConfigurationOneActionsItemTypeMax = 100

export const hogFlowsInvocationsCreateBodyConfigurationOneSchedulesItemTimezoneMax = 64

export const hogFlowsInvocationsCreateBodyMockAsyncFunctionsDefault = true

export const HogFlowsInvocationsCreateBody = /* @__PURE__ */ zod.object({
    configuration: zod
        .object({
            id: zod.uuid(),
            name: zod
                .string()
                .max(hogFlowsInvocationsCreateBodyConfigurationOneNameMax)
                .nullish()
                .describe('Workflow name.'),
            description: zod
                .string()
                .default(hogFlowsInvocationsCreateBodyConfigurationOneDescriptionDefault)
                .describe('Optional description.'),
            version: zod.number(),
            status: zod
                .enum(['draft', 'active', 'archived'])
                .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived')
                .optional()
                .describe(
                    'draft (no execution), active (live), archived (disabled).\n\n\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'
                ),
            created_at: zod.iso.datetime({ offset: true }),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(hogFlowsInvocationsCreateBodyConfigurationOneCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(hogFlowsInvocationsCreateBodyConfigurationOneCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(hogFlowsInvocationsCreateBodyConfigurationOneCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(hogFlowsInvocationsCreateBodyConfigurationOneCreatedByOneEmailMax),
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
                                '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.null(),
                    ])
                    .optional(),
            }),
            updated_at: zod.iso.datetime({ offset: true }),
            trigger: zod.unknown(),
            trigger_masking: zod
                .union([
                    zod.object({
                        ttl: zod
                            .number()
                            .min(hogFlowsInvocationsCreateBodyConfigurationOneTriggerMaskingOneTtlMin)
                            .max(hogFlowsInvocationsCreateBodyConfigurationOneTriggerMaskingOneTtlMax)
                            .nullish()
                            .describe('Seconds (60 to ~94M \/ 3y) to suppress repeat firings of the same hash.'),
                        threshold: zod
                            .number()
                            .nullish()
                            .describe(
                                'Fire once per N matches of the same hash within ttl — a sampler: N=3 fires on the 1st, 4th, 7th… match. Omit to fire on the first match, then suppress repeats within ttl.'
                            ),
                        hash: zod
                            .string()
                            .describe(
                                "HogQL template defining the dedup\/grouping key, e.g. '{person.id}' (once per person) within ttl."
                            ),
                        bytecode: zod.unknown().optional().describe('Auto-compiled from hash. Do not set.'),
                    }),
                    zod.null(),
                ])
                .optional()
                .describe(
                    "Optional dedup\/throttle on an already-matched trigger: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Without threshold: fire once per hash, then suppress repeats within ttl (hash '{person.id}' = once per person per ttl). With threshold N: fire once per N matches of the same hash — a sampler, the 1st then every Nth. Throttles an already-qualifying trigger; it doesn't decide who enters. Server compiles bytecode from hash; omit to disable."
                ),
            conversion: zod
                .unknown()
                .optional()
                .describe(
                    'Conversion goal: {filters: [<cond>, ...], window_minutes}. <cond>: {key, value, operator, type: event|person|group}. Empty filters = any event in window. Required for exit_on_conversion \/ exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side.'
                ),
            exit_condition: zod
                .enum([
                    'exit_on_conversion',
                    'exit_on_trigger_not_matched',
                    'exit_on_trigger_not_matched_or_conversion',
                    'exit_only_at_end',
                ])
                .describe(
                    '\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End'
                )
                .optional()
                .describe(
                    "exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion').\n\n\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End"
                ),
            edges: zod
                .array(
                    zod.object({
                        to: zod.string().describe('Target action id.'),
                        type: zod
                            .enum(['continue', 'branch'])
                            .describe('\* `continue` - continue\n\* `branch` - branch')
                            .describe(
                                "continue: fall-through (sequential or the no-match path of conditional_branch). branch: requires 'index' matching config.conditions[index].\n\n\* `continue` - continue\n\* `branch` - branch"
                            ),
                        index: zod
                            .number()
                            .optional()
                            .describe(
                                "Required for type='branch'. Index into config.conditions on conditional_branch \/ wait_until_condition."
                            ),
                        from: zod.string().describe('Source action id.'),
                    })
                )
                .optional()
                .describe(
                    "Graph edges: [{from, to, type: 'continue'|'branch', index?}]. 'continue' = fall-through (sequential, or no-match path of conditional_branch). 'branch' requires 'index': matches config.conditions[index] on conditional_branch \/ wait_until_condition. Every non-exit action needs a reachable next action ('No next action found' otherwise)."
                ),
            actions: zod
                .array(
                    zod.object({
                        id: zod.string().describe('Unique node ID within the workflow.'),
                        name: zod
                            .string()
                            .max(hogFlowsInvocationsCreateBodyConfigurationOneActionsItemNameMax)
                            .describe('Display name.'),
                        description: zod
                            .string()
                            .default(hogFlowsInvocationsCreateBodyConfigurationOneActionsItemDescriptionDefault)
                            .describe('Optional description.'),
                        on_error: zod
                            .union([
                                zod
                                    .enum(['continue', 'abort', 'complete', 'branch'])
                                    .describe(
                                        '\* `continue` - continue\n\* `abort` - abort\n\* `complete` - complete\n\* `branch` - branch'
                                    ),
                                zod.null(),
                            ])
                            .optional()
                            .describe(
                                'On failure: continue (skip), abort (stop), complete (mark done), branch (follow error edge).\n\n\* `continue` - continue\n\* `abort` - abort\n\* `complete` - complete\n\* `branch` - branch'
                            ),
                        created_at: zod.number().optional().describe('Created at (epoch ms). Frontend-managed.'),
                        updated_at: zod.number().optional().describe('Updated at (epoch ms). Frontend-managed.'),
                        filters: zod
                            .union([
                                zod.object({
                                    source: zod
                                        .enum(['events', 'person-updates', 'data-warehouse-table'])
                                        .describe(
                                            '\* `events` - events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table'
                                        )
                                        .default(
                                            hogFlowsInvocationsCreateBodyConfigurationOneActionsItemFiltersOneSourceDefault
                                        ),
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
                            .max(hogFlowsInvocationsCreateBodyConfigurationOneActionsItemTypeMax)
                            .describe(
                                'trigger | function | function_email | function_sms | function_push | delay | conditional_branch | wait_until_condition | wait_until_time_window | random_cohort_branch | exit.'
                            ),
                        config: zod
                            .unknown()
                            .describe(
                                "Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}. function\*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. wait_until_condition: {condition: {filters}, max_wait_duration: <duration>} (same rules as delay). exit: {reason}."
                            ),
                        output_variable: zod
                            .unknown()
                            .optional()
                            .describe('Output variable definition for downstream actions.'),
                    })
                )
                .describe("Ordered action nodes. Exactly one type='trigger' required. Typically one type='exit' too."),
            abort_action: zod.string().nullable(),
            variables: zod
                .array(
                    zod
                        .record(zod.string(), zod.string())
                        .describe('Variable: {key, type: string|number|boolean, default}.')
                )
                .optional()
                .describe('Workflow vars (key, type, default). Total <5KB.'),
            billable_action_types: zod.unknown(),
            schedules: zod
                .array(
                    zod.object({
                        id: zod.uuid(),
                        rrule: zod
                            .string()
                            .describe(
                                "iCalendar RRULE string (e.g. 'FREQ=DAILY;INTERVAL=1'). Must produce occurrences at most once per hour."
                            ),
                        starts_at: zod.iso
                            .datetime({ offset: true })
                            .describe('ISO 8601 datetime the schedule starts from.'),
                        timezone: zod
                            .string()
                            .max(hogFlowsInvocationsCreateBodyConfigurationOneSchedulesItemTimezoneMax)
                            .optional()
                            .describe("IANA timezone for interpreting the RRULE (default 'UTC')."),
                        variables: zod
                            .unknown()
                            .optional()
                            .describe('Variable value overrides merged with the workflow defaults on each run.'),
                        status: zod
                            .enum(['active', 'paused', 'completed'])
                            .describe('\* `active` - Active\n\* `paused` - Paused\n\* `completed` - Completed')
                            .describe(
                                "active, paused, or completed (set once the RRULE's COUNT\/UNTIL is exhausted).\n\n\* `active` - Active\n\* `paused` - Paused\n\* `completed` - Completed"
                            ),
                        next_run_at: zod.iso
                            .datetime({ offset: true })
                            .nullable()
                            .describe('Next scheduled fire time, computed by the scheduler.'),
                        created_at: zod.iso.datetime({ offset: true }),
                        updated_at: zod.iso.datetime({ offset: true }),
                    })
                )
                .describe(
                    "Recurring schedules attached to this workflow (read-only here; manage via the schedules sub-resource). A batch\/schedule workflow only fires when it's active AND has an active schedule. Empty for non-scheduled workflows."
                ),
        })
        .optional()
        .describe('Optional override; omit to use saved definition.'),
    globals: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Test trigger payload, typically {event, person, groups}.'),
    mock_async_functions: zod
        .boolean()
        .default(hogFlowsInvocationsCreateBodyMockAsyncFunctionsDefault)
        .describe('True (default) mocks HTTP\/email\/SMS. False fires real side effects.'),
    current_action_id: zod.string().optional().describe('Start from this action ID instead of the trigger.'),
})

export const hogFlowsSchedulesCreateBodyTimezoneMax = 64

export const HogFlowsSchedulesCreateBody = /* @__PURE__ */ zod.object({
    rrule: zod
        .string()
        .describe(
            "iCalendar RRULE string (e.g. 'FREQ=DAILY;INTERVAL=1'). Must produce occurrences at most once per hour."
        ),
    starts_at: zod.iso.datetime({ offset: true }).describe('ISO 8601 datetime the schedule starts from.'),
    timezone: zod
        .string()
        .max(hogFlowsSchedulesCreateBodyTimezoneMax)
        .optional()
        .describe("IANA timezone for interpreting the RRULE (default 'UTC')."),
    variables: zod
        .unknown()
        .optional()
        .describe('Variable value overrides merged with the workflow defaults on each run.'),
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

export const hogFlowsBulkDeleteCreateBodyNameMax = 400

export const hogFlowsBulkDeleteCreateBodyDescriptionDefault = ``
export const hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsBulkDeleteCreateBodyActionsItemNameMax = 400

export const hogFlowsBulkDeleteCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsBulkDeleteCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsBulkDeleteCreateBodyActionsItemTypeMax = 100

export const HogFlowsBulkDeleteCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsBulkDeleteCreateBodyNameMax).nullish().describe('Workflow name.'),
    description: zod.string().default(hogFlowsBulkDeleteCreateBodyDescriptionDefault).describe('Optional description.'),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived')
        .optional()
        .describe(
            'draft (no execution), active (live), archived (disabled).\n\n\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'
        ),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMax)
                    .nullish()
                    .describe('Seconds (60 to ~94M \/ 3y) to suppress repeat firings of the same hash.'),
                threshold: zod
                    .number()
                    .nullish()
                    .describe(
                        'Fire once per N matches of the same hash within ttl — a sampler: N=3 fires on the 1st, 4th, 7th… match. Omit to fire on the first match, then suppress repeats within ttl.'
                    ),
                hash: zod
                    .string()
                    .describe(
                        "HogQL template defining the dedup\/grouping key, e.g. '{person.id}' (once per person) within ttl."
                    ),
                bytecode: zod.unknown().optional().describe('Auto-compiled from hash. Do not set.'),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            "Optional dedup\/throttle on an already-matched trigger: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Without threshold: fire once per hash, then suppress repeats within ttl (hash '{person.id}' = once per person per ttl). With threshold N: fire once per N matches of the same hash — a sampler, the 1st then every Nth. Throttles an already-qualifying trigger; it doesn't decide who enters. Server compiles bytecode from hash; omit to disable."
        ),
    conversion: zod
        .unknown()
        .optional()
        .describe(
            'Conversion goal: {filters: [<cond>, ...], window_minutes}. <cond>: {key, value, operator, type: event|person|group}. Empty filters = any event in window. Required for exit_on_conversion \/ exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side.'
        ),
    exit_condition: zod
        .enum([
            'exit_on_conversion',
            'exit_on_trigger_not_matched',
            'exit_on_trigger_not_matched_or_conversion',
            'exit_only_at_end',
        ])
        .describe(
            '\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End'
        )
        .optional()
        .describe(
            "exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion').\n\n\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End"
        ),
    edges: zod
        .array(
            zod.object({
                to: zod.string().describe('Target action id.'),
                type: zod
                    .enum(['continue', 'branch'])
                    .describe('\* `continue` - continue\n\* `branch` - branch')
                    .describe(
                        "continue: fall-through (sequential or the no-match path of conditional_branch). branch: requires 'index' matching config.conditions[index].\n\n\* `continue` - continue\n\* `branch` - branch"
                    ),
                index: zod
                    .number()
                    .optional()
                    .describe(
                        "Required for type='branch'. Index into config.conditions on conditional_branch \/ wait_until_condition."
                    ),
                from: zod.string().describe('Source action id.'),
            })
        )
        .optional()
        .describe(
            "Graph edges: [{from, to, type: 'continue'|'branch', index?}]. 'continue' = fall-through (sequential, or no-match path of conditional_branch). 'branch' requires 'index': matches config.conditions[index] on conditional_branch \/ wait_until_condition. Every non-exit action needs a reachable next action ('No next action found' otherwise)."
        ),
    actions: zod
        .array(
            zod.object({
                id: zod.string().describe('Unique node ID within the workflow.'),
                name: zod.string().max(hogFlowsBulkDeleteCreateBodyActionsItemNameMax).describe('Display name.'),
                description: zod
                    .string()
                    .default(hogFlowsBulkDeleteCreateBodyActionsItemDescriptionDefault)
                    .describe('Optional description.'),
                on_error: zod
                    .union([
                        zod
                            .enum(['continue', 'abort', 'complete', 'branch'])
                            .describe(
                                '\* `continue` - continue\n\* `abort` - abort\n\* `complete` - complete\n\* `branch` - branch'
                            ),
                        zod.null(),
                    ])
                    .optional()
                    .describe(
                        'On failure: continue (skip), abort (stop), complete (mark done), branch (follow error edge).\n\n\* `continue` - continue\n\* `abort` - abort\n\* `complete` - complete\n\* `branch` - branch'
                    ),
                created_at: zod.number().optional().describe('Created at (epoch ms). Frontend-managed.'),
                updated_at: zod.number().optional().describe('Updated at (epoch ms). Frontend-managed.'),
                filters: zod
                    .union([
                        zod.object({
                            source: zod
                                .enum(['events', 'person-updates', 'data-warehouse-table'])
                                .describe(
                                    '\* `events` - events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table'
                                )
                                .default(hogFlowsBulkDeleteCreateBodyActionsItemFiltersOneSourceDefault),
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
                    .max(hogFlowsBulkDeleteCreateBodyActionsItemTypeMax)
                    .describe(
                        'trigger | function | function_email | function_sms | function_push | delay | conditional_branch | wait_until_condition | wait_until_time_window | random_cohort_branch | exit.'
                    ),
                config: zod
                    .unknown()
                    .describe(
                        "Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}. function\*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. wait_until_condition: {condition: {filters}, max_wait_duration: <duration>} (same rules as delay). exit: {reason}."
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

export const HogFlowsUserBlastRadiusCreateBody = /* @__PURE__ */ zod.object({
    filters: zod.record(zod.string(), zod.unknown()).describe('Property filters to apply'),
    group_type_index: zod.number().nullish().describe('Group type index for group-based targeting'),
})
