/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const HogFlowTemplateScopeEnumApi = zod
    .enum(['team', 'organization', 'global'])
    .describe('\* `team` - Only team\n\* `organization` - Organization\n\* `global` - Global')

export type HogFlowTemplateScopeEnumApi = zod.input<typeof HogFlowTemplateScopeEnumApi>
export type HogFlowTemplateScopeEnumApiOutput = zod.output<typeof HogFlowTemplateScopeEnumApi>

export const hogFlowMaskingApiTtlMin = 60
export const hogFlowMaskingApiTtlMax = 94608000

export const HogFlowMaskingApi = zod.object({
    ttl: zod
        .number()
        .min(hogFlowMaskingApiTtlMin)
        .max(hogFlowMaskingApiTtlMax)
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
        .describe("HogQL template defining the dedup\/grouping key, e.g. '{person.id}' (once per person) within ttl."),
    bytecode: zod.unknown().optional().describe('Auto-compiled from hash. Do not set.'),
})

export type HogFlowMaskingApi = zod.input<typeof HogFlowMaskingApi>
export type HogFlowMaskingApiOutput = zod.output<typeof HogFlowMaskingApi>

export const ExitConditionEnumApi = zod
    .enum([
        'exit_on_conversion',
        'exit_on_trigger_not_matched',
        'exit_on_trigger_not_matched_or_conversion',
        'exit_only_at_end',
    ])
    .describe(
        '\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End'
    )

export type ExitConditionEnumApi = zod.input<typeof ExitConditionEnumApi>
export type ExitConditionEnumApiOutput = zod.output<typeof ExitConditionEnumApi>

export const OnErrorEnumApi = zod.enum(['continue', 'abort']).describe('\* `continue` - continue\n\* `abort` - abort')

export type OnErrorEnumApi = zod.input<typeof OnErrorEnumApi>
export type OnErrorEnumApiOutput = zod.output<typeof OnErrorEnumApi>

export const HogFunctionFiltersSourceEnumApi = zod
    .enum(['events', 'person-updates', 'data-warehouse-table'])
    .describe(
        '\* `events` - events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table'
    )

export type HogFunctionFiltersSourceEnumApi = zod.input<typeof HogFunctionFiltersSourceEnumApi>
export type HogFunctionFiltersSourceEnumApiOutput = zod.output<typeof HogFunctionFiltersSourceEnumApi>

export const hogFunctionFiltersApiSourceDefault = `events`

export const HogFunctionFiltersApi = zod.object({
    source: HogFunctionFiltersSourceEnumApi.default(hogFunctionFiltersApiSourceDefault),
    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
    bytecode: zod.unknown().optional(),
    transpiled: zod.unknown().optional(),
    filter_test_accounts: zod.boolean().optional(),
    bytecode_error: zod.string().optional(),
})

export type HogFunctionFiltersApi = zod.input<typeof HogFunctionFiltersApi>
export type HogFunctionFiltersApiOutput = zod.output<typeof HogFunctionFiltersApi>

export const hogFlowTemplateActionApiNameMax = 400

export const hogFlowTemplateActionApiDescriptionDefault = ``
export const hogFlowTemplateActionApiTypeMax = 100

export const HogFlowTemplateActionApi = zod
    .object({
        id: zod.string(),
        name: zod.string().max(hogFlowTemplateActionApiNameMax),
        description: zod.string().default(hogFlowTemplateActionApiDescriptionDefault),
        on_error: zod
            .union([OnErrorEnumApi, zod.null()])
            .optional()
            .describe(
                'On failure: continue (skip the action and proceed) or abort (stop the run).\n\n\* `continue` - continue\n\* `abort` - abort'
            ),
        created_at: zod.number().optional(),
        updated_at: zod.number().optional(),
        filters: zod.union([HogFunctionFiltersApi, zod.null()]).optional(),
        type: zod.string().max(hogFlowTemplateActionApiTypeMax),
        config: zod.unknown(),
        output_variable: zod.unknown().optional(),
    })
    .describe(
        'Custom action serializer for templates that skips input validation\n(since templates should have default\/empty values).'
    )

export type HogFlowTemplateActionApi = zod.input<typeof HogFlowTemplateActionApi>
export type HogFlowTemplateActionApiOutput = zod.output<typeof HogFlowTemplateActionApi>

export const hogFlowTemplateApiNameMax = 400

export const hogFlowTemplateApiImageUrlMax = 8201

export const hogFlowTemplateApiAbortActionMax = 400

export const HogFlowTemplateApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(hogFlowTemplateApiNameMax),
        description: zod.string().optional(),
        image_url: zod.string().max(hogFlowTemplateApiImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: HogFlowTemplateScopeEnumApi,
        created_at: zod.iso.datetime({ offset: true }),
        created_by: zod.looseObject({}).nullable(),
        updated_at: zod.iso.datetime({ offset: true }),
        trigger: zod.unknown().optional(),
        trigger_masking: zod.union([HogFlowMaskingApi, zod.null()]).optional(),
        conversion: zod.unknown().optional(),
        exit_condition: ExitConditionEnumApi.optional(),
        edges: zod.unknown().optional(),
        actions: zod.array(HogFlowTemplateActionApi),
        abort_action: zod.string().max(hogFlowTemplateApiAbortActionMax).nullish(),
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

export type HogFlowTemplateApi = zod.input<typeof HogFlowTemplateApi>
export type HogFlowTemplateApiOutput = zod.output<typeof HogFlowTemplateApi>

export const PaginatedHogFlowTemplateListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(HogFlowTemplateApi),
})

export type PaginatedHogFlowTemplateListApi = zod.input<typeof PaginatedHogFlowTemplateListApi>
export type PaginatedHogFlowTemplateListApiOutput = zod.output<typeof PaginatedHogFlowTemplateListApi>

export const patchedHogFlowTemplateApiNameMax = 400

export const patchedHogFlowTemplateApiImageUrlMax = 8201

export const patchedHogFlowTemplateApiAbortActionMax = 400

export const PatchedHogFlowTemplateApi = zod
    .object({
        id: zod.uuid().optional(),
        name: zod.string().max(patchedHogFlowTemplateApiNameMax).optional(),
        description: zod.string().optional(),
        image_url: zod.string().max(patchedHogFlowTemplateApiImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: HogFlowTemplateScopeEnumApi.optional(),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: zod.looseObject({}).nullish(),
        updated_at: zod.iso.datetime({ offset: true }).optional(),
        trigger: zod.unknown().optional(),
        trigger_masking: zod.union([HogFlowMaskingApi, zod.null()]).optional(),
        conversion: zod.unknown().optional(),
        exit_condition: ExitConditionEnumApi.optional(),
        edges: zod.unknown().optional(),
        actions: zod.array(HogFlowTemplateActionApi).optional(),
        abort_action: zod.string().max(patchedHogFlowTemplateApiAbortActionMax).nullish(),
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

export type PatchedHogFlowTemplateApi = zod.input<typeof PatchedHogFlowTemplateApi>
export type PatchedHogFlowTemplateApiOutput = zod.output<typeof PatchedHogFlowTemplateApi>

export const HogFlowStatusEnumApi = zod
    .enum(['draft', 'active', 'archived'])
    .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived')

export type HogFlowStatusEnumApi = zod.input<typeof HogFlowStatusEnumApi>
export type HogFlowStatusEnumApiOutput = zod.output<typeof HogFlowStatusEnumApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const HogFlowMinimalApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string().nullable(),
        description: zod.string(),
        version: zod.number(),
        status: HogFlowStatusEnumApi,
        created_at: zod.iso.datetime({ offset: true }),
        created_by: UserBasicApi,
        updated_at: zod.iso.datetime({ offset: true }),
        trigger: zod.unknown(),
        trigger_masking: zod.unknown(),
        conversion: zod.unknown(),
        exit_condition: ExitConditionEnumApi,
        edges: zod.unknown(),
        actions: zod.unknown(),
        abort_action: zod.string().nullable(),
        variables: zod.unknown(),
        billable_action_types: zod.unknown(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

export type HogFlowMinimalApi = zod.input<typeof HogFlowMinimalApi>
export type HogFlowMinimalApiOutput = zod.output<typeof HogFlowMinimalApi>

export const PaginatedHogFlowMinimalListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(HogFlowMinimalApi),
})

export type PaginatedHogFlowMinimalListApi = zod.input<typeof PaginatedHogFlowMinimalListApi>
export type PaginatedHogFlowMinimalListApiOutput = zod.output<typeof PaginatedHogFlowMinimalListApi>

export const HogFlowConversionEventApi = zod.object({
    filters: HogFunctionFiltersApi.describe(
        "Event\/action filters for this conversion event, same shape as trigger filters: {events: [{id, name, type: 'events', properties?: [<cond>]}], actions?: [...], properties?: [<cond>]}. bytecode is compiled server-side."
    ),
})

export type HogFlowConversionEventApi = zod.input<typeof HogFlowConversionEventApi>
export type HogFlowConversionEventApiOutput = zod.output<typeof HogFlowConversionEventApi>

export const HogFlowConversionApi = zod.object({
    filters: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .optional()
        .describe(
            "Property-based conversion conditions, as an ARRAY of property filters: [{key, value, operator, type: event|person|group}, ...]. Event-based goals do NOT go here — put them in 'events'. Empty array = any event within the window converts."
        ),
    events: zod
        .array(HogFlowConversionEventApi)
        .optional()
        .describe("Event-based conversion goals: [{filters: {events: [{id, name, type: 'events'}], ...}}]."),
    window_minutes: zod
        .number()
        .nullish()
        .describe('Conversion window in minutes after a person enters the workflow. null = no explicit window.'),
    bytecode: zod.unknown().optional().describe("Compiled server-side from 'filters'. Do not set; ignored if sent."),
})

export type HogFlowConversionApi = zod.input<typeof HogFlowConversionApi>
export type HogFlowConversionApiOutput = zod.output<typeof HogFlowConversionApi>

export const HogFlowEdgeTypeEnumApi = zod
    .enum(['continue', 'branch'])
    .describe('\* `continue` - continue\n\* `branch` - branch')

export type HogFlowEdgeTypeEnumApi = zod.input<typeof HogFlowEdgeTypeEnumApi>
export type HogFlowEdgeTypeEnumApiOutput = zod.output<typeof HogFlowEdgeTypeEnumApi>

export const HogFlowEdgeApi = zod.object({
    to: zod.string().describe('Target action id.'),
    type: HogFlowEdgeTypeEnumApi.describe(
        "continue: fall-through (sequential or the no-match path of conditional_branch). branch: requires 'index' matching config.conditions[index].\n\n\* `continue` - continue\n\* `branch` - branch"
    ),
    index: zod
        .number()
        .optional()
        .describe(
            "Required for type='branch'. conditional_branch: index into config.conditions[index]. random_cohort_branch: index into config.cohorts[index]. wait_until_condition: use index:0 — it advances via the index:0 branch edge when it resolves (a condition match or an events entry firing)."
        ),
    from: zod.string().describe('Source action id.'),
})

export type HogFlowEdgeApi = zod.input<typeof HogFlowEdgeApi>
export type HogFlowEdgeApiOutput = zod.output<typeof HogFlowEdgeApi>

export const HogFlowActionTypeEnumApi = zod
    .enum([
        'trigger',
        'function',
        'function_email',
        'function_sms',
        'function_push',
        'delay',
        'wait_until_condition',
        'wait_until_time_window',
        'conditional_branch',
        'random_cohort_branch',
        'exit',
    ])
    .describe(
        '\* `trigger` - trigger\n\* `function` - function\n\* `function_email` - function_email\n\* `function_sms` - function_sms\n\* `function_push` - function_push\n\* `delay` - delay\n\* `wait_until_condition` - wait_until_condition\n\* `wait_until_time_window` - wait_until_time_window\n\* `conditional_branch` - conditional_branch\n\* `random_cohort_branch` - random_cohort_branch\n\* `exit` - exit'
    )

export type HogFlowActionTypeEnumApi = zod.input<typeof HogFlowActionTypeEnumApi>
export type HogFlowActionTypeEnumApiOutput = zod.output<typeof HogFlowActionTypeEnumApi>

export const hogFlowActionApiIdMax = 200

export const hogFlowActionApiNameMax = 400

export const hogFlowActionApiDescriptionDefault = ``

export const HogFlowActionApi = zod.object({
    id: zod.string().max(hogFlowActionApiIdMax).describe('Unique node ID within the workflow.'),
    name: zod.string().max(hogFlowActionApiNameMax).describe('Display name.'),
    description: zod.string().default(hogFlowActionApiDescriptionDefault).describe('Optional description.'),
    on_error: zod
        .union([OnErrorEnumApi, zod.null()])
        .optional()
        .describe(
            'On failure: continue (skip the action and proceed) or abort (stop the run).\n\n\* `continue` - continue\n\* `abort` - abort'
        ),
    created_at: zod.number().optional().describe('Created at (epoch ms). Frontend-managed.'),
    updated_at: zod.number().optional().describe('Updated at (epoch ms). Frontend-managed.'),
    filters: zod.union([HogFunctionFiltersApi, zod.null()]).optional().describe('Property filters gating this action.'),
    type: HogFlowActionTypeEnumApi.describe(
        'One of: trigger | function | function_email | function_sms | function_push | delay | wait_until_condition | wait_until_time_window | conditional_branch | random_cohort_branch | exit.\n\n\* `trigger` - trigger\n\* `function` - function\n\* `function_email` - function_email\n\* `function_sms` - function_sms\n\* `function_push` - function_push\n\* `delay` - delay\n\* `wait_until_condition` - wait_until_condition\n\* `wait_until_time_window` - wait_until_time_window\n\* `conditional_branch` - conditional_branch\n\* `random_cohort_branch` - random_cohort_branch\n\* `exit` - exit'
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
                                .union([HogFunctionFiltersApi, zod.null()])
                                .optional()
                                .describe('Property conditions, e.g. {properties: [{key, value, operator, type}]}.'),
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
                                    .union([HogFunctionFiltersApi, zod.null()])
                                    .optional()
                                    .describe(
                                        'Event\/action filters; the workflow wakes when a matching event fires. Must target at least one event or action (entries targeting neither are dropped).'
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
                        .describe("'<number><unit>' with unit m|h|d, e.g. '30m' (same rules as delay)."),
                })
                .describe(
                    "Config for type='wait_until_condition'. Provide 'condition' and\/or 'events' — an events-only wait (no condition) is valid."
                ),
        ])
        .describe(
            "Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. webhook and manual triggers also require template_id: 'template-source-webhook', and tracking_pixel requires template_id: 'template-source-webhook-pixel'. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}, or {key: 'id', type: 'cohort', value: <cohort_id>, operator: 'in'} to reference a cohort. function\*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. function_email also accepts tracking_enabled?: <bool> (default true) - when false, no open pixel is injected, links are not rewritten, and the send skips ESP-level open\/click tracking, so opens and clicks are not recorded for that step (delivery\/bounce\/unsubscribe still are). Dictionary input values are template strings too — write booleans\/numbers as single-expression templates ('{true}', '{42}'), which evaluate to the typed value. delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. random_cohort_branch: {cohorts: [{percentage: <number>, name?}, ...]}. Index N matches the 'branch' edge with index:N; percentages should sum to 100 (an unallocated remainder routes to the last cohort). wait_until_condition: {condition: {filters}, events?: [{filters: {events: [{id, name, type: 'events'}], actions?: [...]}, name?}], max_wait_duration: <duration>} (same rules as delay). Continues when condition.filters match OR any events entry fires; each events entry must target at least one event or action. On resolution (a condition match or any events entry firing) it advances via the 'branch' edge with index:0; the max_wait_duration timeout falls through the 'continue' edge. exit: {reason}."
        ),
    output_variable: zod
        .unknown()
        .optional()
        .describe('Output variable for downstream actions: {key, result_path?, spread?, label?} or a list of those.'),
})

export type HogFlowActionApi = zod.input<typeof HogFlowActionApi>
export type HogFlowActionApiOutput = zod.output<typeof HogFlowActionApi>

export const HogFlowScheduleStatusEnumApi = zod
    .enum(['active', 'paused', 'completed'])
    .describe('\* `active` - Active\n\* `paused` - Paused\n\* `completed` - Completed')

export type HogFlowScheduleStatusEnumApi = zod.input<typeof HogFlowScheduleStatusEnumApi>
export type HogFlowScheduleStatusEnumApiOutput = zod.output<typeof HogFlowScheduleStatusEnumApi>

export const hogFlowScheduleApiTimezoneMax = 64

export const HogFlowScheduleApi = zod.object({
    id: zod.uuid(),
    rrule: zod
        .string()
        .describe(
            "iCalendar RRULE string (e.g. 'FREQ=DAILY;INTERVAL=1'). Must produce occurrences at most once per hour."
        ),
    starts_at: zod.iso.datetime({ offset: true }).describe('ISO 8601 datetime the schedule starts from.'),
    timezone: zod
        .string()
        .max(hogFlowScheduleApiTimezoneMax)
        .optional()
        .describe("IANA timezone for interpreting the RRULE (default 'UTC')."),
    variables: zod
        .unknown()
        .optional()
        .describe('Variable value overrides merged with the workflow defaults on each run.'),
    status: HogFlowScheduleStatusEnumApi.describe(
        "active, paused, or completed (set once the RRULE's COUNT\/UNTIL is exhausted).\n\n\* `active` - Active\n\* `paused` - Paused\n\* `completed` - Completed"
    ),
    next_run_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('Next scheduled fire time, computed by the scheduler.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type HogFlowScheduleApi = zod.input<typeof HogFlowScheduleApi>
export type HogFlowScheduleApiOutput = zod.output<typeof HogFlowScheduleApi>

export const hogFlowApiNameMax = 400

export const hogFlowApiDescriptionDefault = ``

export const HogFlowApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(hogFlowApiNameMax).nullish().describe('Workflow name.'),
        description: zod.string().default(hogFlowApiDescriptionDefault).describe('Optional description.'),
        version: zod.number(),
        status: HogFlowStatusEnumApi.optional().describe(
            'draft (no execution), active (live), archived (disabled).\n\n\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'
        ),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: UserBasicApi,
        updated_at: zod.iso.datetime({ offset: true }),
        trigger: zod.unknown(),
        trigger_masking: zod
            .union([HogFlowMaskingApi, zod.null()])
            .optional()
            .describe(
                "Optional dedup\/throttle on an already-matched trigger: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Without threshold: fire once per hash, then suppress repeats within ttl (hash '{person.id}' = once per person per ttl). With threshold N: fire once per N matches of the same hash — a sampler, the 1st then every Nth. Throttles an already-qualifying trigger; it doesn't decide who enters. Server compiles bytecode from hash; omit to disable."
            ),
        conversion: zod
            .union([HogFlowConversionApi, zod.null()])
            .optional()
            .describe(
                'Conversion goal. filters: ARRAY of property conditions [{key, value, operator, type: event|person|group}]; events: event-based goals [{filters: {events: [...]}}]; window_minutes: minutes after entry. Required for exit_on_conversion \/ exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side.'
            ),
        exit_condition: ExitConditionEnumApi.optional().describe(
            "exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion').\n\n\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End"
        ),
        edges: zod
            .array(HogFlowEdgeApi)
            .optional()
            .describe(
                "Graph edges: [{from, to, type: 'continue'|'branch', index?}]. 'continue' = fall-through (sequential, or no-match path of conditional_branch). 'branch' requires 'index': matches config.conditions[index] on conditional_branch \/ wait_until_condition. Every non-exit action needs a reachable next action ('No next action found' otherwise)."
            ),
        actions: zod
            .array(HogFlowActionApi)
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
            .array(HogFlowScheduleApi)
            .describe(
                "Recurring schedules attached to this workflow (read-only here; manage via the schedules sub-resource). A batch\/schedule workflow only fires when it's active AND has an active schedule. Empty for non-scheduled workflows."
            ),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        draft: zod
            .unknown()
            .describe(
                "Staged content changes awaiting publish — a full snapshot of the workflow's actions, edges and settings. Null when there's nothing staged. Test it with a use_draft test run, then promote it with the publish endpoint or throw it away with discard_draft."
            ),
        draft_updated_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe(
                "When the draft was last written; null when there's no staged draft. Pass this to publish (and as base_updated_at on further draft edits) so a concurrent editor's changes aren't clobbered — a mismatch returns 409."
            ),
        action_redirects: zod
            .record(zod.string(), zod.string())
            .nullable()
            .describe(
                'Skip-forward map for deleted steps: {deleted_action_id: next surviving action_id}. Maintained automatically when a live graph edit deletes actions, so in-flight runs parked on a deleted step continue at its surviving successor instead of exiting. Null when no live deletions have occurred.'
            ),
    })
    .describe('Mixin for serializers to add user access control fields')

export type HogFlowApi = zod.input<typeof HogFlowApi>
export type HogFlowApiOutput = zod.output<typeof HogFlowApi>

export const patchedHogFlowApiNameMax = 400

export const patchedHogFlowApiDescriptionDefault = ``

export const PatchedHogFlowApi = zod
    .object({
        id: zod.uuid().optional(),
        name: zod.string().max(patchedHogFlowApiNameMax).nullish().describe('Workflow name.'),
        description: zod.string().default(patchedHogFlowApiDescriptionDefault).describe('Optional description.'),
        version: zod.number().optional(),
        status: HogFlowStatusEnumApi.optional().describe(
            'draft (no execution), active (live), archived (disabled).\n\n\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'
        ),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        created_by: UserBasicApi.optional(),
        updated_at: zod.iso.datetime({ offset: true }).optional(),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .union([HogFlowMaskingApi, zod.null()])
            .optional()
            .describe(
                "Optional dedup\/throttle on an already-matched trigger: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Without threshold: fire once per hash, then suppress repeats within ttl (hash '{person.id}' = once per person per ttl). With threshold N: fire once per N matches of the same hash — a sampler, the 1st then every Nth. Throttles an already-qualifying trigger; it doesn't decide who enters. Server compiles bytecode from hash; omit to disable."
            ),
        conversion: zod
            .union([HogFlowConversionApi, zod.null()])
            .optional()
            .describe(
                'Conversion goal. filters: ARRAY of property conditions [{key, value, operator, type: event|person|group}]; events: event-based goals [{filters: {events: [...]}}]; window_minutes: minutes after entry. Required for exit_on_conversion \/ exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side.'
            ),
        exit_condition: ExitConditionEnumApi.optional().describe(
            "exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion').\n\n\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End"
        ),
        edges: zod
            .array(HogFlowEdgeApi)
            .optional()
            .describe(
                "Graph edges: [{from, to, type: 'continue'|'branch', index?}]. 'continue' = fall-through (sequential, or no-match path of conditional_branch). 'branch' requires 'index': matches config.conditions[index] on conditional_branch \/ wait_until_condition. Every non-exit action needs a reachable next action ('No next action found' otherwise)."
            ),
        actions: zod
            .array(HogFlowActionApi)
            .optional()
            .describe("Ordered action nodes. Exactly one type='trigger' required. Typically one type='exit' too."),
        abort_action: zod.string().nullish(),
        variables: zod
            .array(
                zod
                    .record(zod.string(), zod.string())
                    .describe('Variable: {key, type: string|number|boolean, default}.')
            )
            .optional()
            .describe('Workflow vars (key, type, default). Total <5KB.'),
        billable_action_types: zod.unknown().optional(),
        schedules: zod
            .array(HogFlowScheduleApi)
            .optional()
            .describe(
                "Recurring schedules attached to this workflow (read-only here; manage via the schedules sub-resource). A batch\/schedule workflow only fires when it's active AND has an active schedule. Empty for non-scheduled workflows."
            ),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
        draft: zod
            .unknown()
            .optional()
            .describe(
                "Staged content changes awaiting publish — a full snapshot of the workflow's actions, edges and settings. Null when there's nothing staged. Test it with a use_draft test run, then promote it with the publish endpoint or throw it away with discard_draft."
            ),
        draft_updated_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe(
                "When the draft was last written; null when there's no staged draft. Pass this to publish (and as base_updated_at on further draft edits) so a concurrent editor's changes aren't clobbered — a mismatch returns 409."
            ),
        action_redirects: zod
            .record(zod.string(), zod.string())
            .nullish()
            .describe(
                'Skip-forward map for deleted steps: {deleted_action_id: next surviving action_id}. Maintained automatically when a live graph edit deletes actions, so in-flight runs parked on a deleted step continue at its surviving successor instead of exiting. Null when no live deletions have occurred.'
            ),
    })
    .describe('Mixin for serializers to add user access control fields')

export type PatchedHogFlowApi = zod.input<typeof PatchedHogFlowApi>
export type PatchedHogFlowApiOutput = zod.output<typeof PatchedHogFlowApi>

export const MessageAssetApi = zod.object({
    invocation_id: zod.string().describe('The workflow run this email was sent in.'),
    action_id: zod.string().describe('The email step (action node) within the workflow that sent this email.'),
    function_id: zod
        .string()
        .describe(
            "The workflow id that sent this email — used to navigate from a person's Emails tab back into the originating workflow."
        ),
    function_name: zod
        .string()
        .describe(
            'Human-readable workflow name for display. Empty when the workflow has been deleted; clients should fall back to function_id in that case.'
        ),
    parent_run_id: zod
        .string()
        .describe(
            'The batch run this email belongs to, for batch-triggered workflows. Empty for event-triggered runs.'
        ),
    kind: zod
        .string()
        .describe(
            "Message channel this asset was sent on: 'email' or 'push'. The per-person endpoints return one channel each."
        ),
    distinct_id: zod.string().describe("The recipient's distinct_id."),
    person_id: zod.string().describe("The recipient's person UUID, if resolved."),
    recipient: zod
        .string()
        .describe("Who the message went to: the email address for 'email', or the recipient's distinct ID for 'push'."),
    subject: zod.string().describe('The email subject line, or the push notification title.'),
    status: zod
        .string()
        .describe("Delivery status at capture time. Currently always 'sent' - only delivered messages are captured."),
    sent_at: zod.iso.datetime({ offset: true }).describe('When the message was sent.'),
})

export type MessageAssetApi = zod.input<typeof MessageAssetApi>
export type MessageAssetApiOutput = zod.output<typeof MessageAssetApi>

export const HogFlowBatchJobStatusEnumApi = zod
    .enum(['waiting', 'queued', 'active', 'completed', 'cancelled', 'failed'])
    .describe(
        '\* `waiting` - Waiting\n\* `queued` - Queued\n\* `active` - Active\n\* `completed` - Completed\n\* `cancelled` - Cancelled\n\* `failed` - Failed'
    )

export type HogFlowBatchJobStatusEnumApi = zod.input<typeof HogFlowBatchJobStatusEnumApi>
export type HogFlowBatchJobStatusEnumApiOutput = zod.output<typeof HogFlowBatchJobStatusEnumApi>

export const HogFlowBatchJobApi = zod.object({
    id: zod.uuid(),
    status: HogFlowBatchJobStatusEnumApi.optional().describe(
        'Not currently tracked — stays at its initial value. Use the workflow logs\/metrics endpoints for run outcome.\n\n\* `waiting` - Waiting\n\* `queued` - Queued\n\* `active` - Active\n\* `completed` - Completed\n\* `cancelled` - Cancelled\n\* `failed` - Failed'
    ),
    hog_flow: zod.uuid().describe('ID of the workflow this batch run belongs to.'),
    filters: zod
        .unknown()
        .describe("Audience snapshot the run fanned out to, taken from the workflow's batch trigger filters."),
    variables: zod.unknown().optional().describe('Variable value overrides applied to this run.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    updated_at: zod.iso.datetime({ offset: true }),
})

export type HogFlowBatchJobApi = zod.input<typeof HogFlowBatchJobApi>
export type HogFlowBatchJobApiOutput = zod.output<typeof HogFlowBatchJobApi>

export const HogFlowGraphOperationOpEnumApi = zod
    .enum(['update_action', 'add_action', 'remove_action', 'add_edge', 'remove_edge', 'replace_action_edges'])
    .describe(
        '\* `update_action` - update_action\n\* `add_action` - add_action\n\* `remove_action` - remove_action\n\* `add_edge` - add_edge\n\* `remove_edge` - remove_edge\n\* `replace_action_edges` - replace_action_edges'
    )

export type HogFlowGraphOperationOpEnumApi = zod.input<typeof HogFlowGraphOperationOpEnumApi>
export type HogFlowGraphOperationOpEnumApiOutput = zod.output<typeof HogFlowGraphOperationOpEnumApi>

export const HogFlowGraphOperationApi = zod.object({
    op: HogFlowGraphOperationOpEnumApi.describe(
        "Graph edit. update_action {id, patch}: deep-merge patch into the action's fields (a null leaf deletes that key) — the surgical path for tweaking one config value. add_action {action, edges?}: append a full action node, optionally wiring its edges in the same op. remove_action {id}: delete a node and reconnect its incoming edges to its first outgoer. add_edge {edge} \/ remove_edge {edge}: add or delete one edge. replace_action_edges {id, edges}: replace this action's outgoing edges with the given set (use when adding\/removing branch conditions); incoming edges are left intact.\n\n\* `update_action` - update_action\n\* `add_action` - add_action\n\* `remove_action` - remove_action\n\* `add_edge` - add_edge\n\* `remove_edge` - remove_edge\n\* `replace_action_edges` - replace_action_edges"
    ),
    id: zod.string().optional().describe('Action id. Required for update_action, remove_action, replace_action_edges.'),
    patch: zod
        .unknown()
        .optional()
        .describe(
            "update_action only. Partial action fields, deep-merged into the existing action; a null leaf deletes that key. e.g. {config: {inputs: {subject: {value: 'Hi'}}}} changes only that input."
        ),
    action: zod
        .unknown()
        .optional()
        .describe('add_action only. A full action node {id, name, type, config, ...}; same shape as in actions.'),
    edge: HogFlowEdgeApi.optional().describe('add_edge \/ remove_edge only. The edge {from, to, type, index?}.'),
    edges: zod
        .array(HogFlowEdgeApi)
        .optional()
        .describe(
            "replace_action_edges: the complete set of the action's outgoing edges (incoming edges are preserved). add_action: optional edges to wire the new node in the same op."
        ),
})

export type HogFlowGraphOperationApi = zod.input<typeof HogFlowGraphOperationApi>
export type HogFlowGraphOperationApiOutput = zod.output<typeof HogFlowGraphOperationApi>

export const PatchedHogFlowGraphUpdateApi = zod.object({
    base_updated_at: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe(
            'Optimistic concurrency: the updated_at (or draft_updated_at) last loaded. If the stored graph is newer, the patch is rejected with 409 instead of clobbering a concurrent edit.'
        ),
    operations: zod
        .array(HogFlowGraphOperationApi)
        .optional()
        .describe(
            "Ordered graph edits applied atomically to a draft workflow: the stored graph is read, the ops are applied in order, the result is fully validated, and it's saved only if valid — otherwise the workflow is unchanged. Reference nodes\/edges by id so you never resend the whole graph. The full updated workflow is returned."
        ),
})

export type PatchedHogFlowGraphUpdateApi = zod.input<typeof PatchedHogFlowGraphUpdateApi>
export type PatchedHogFlowGraphUpdateApiOutput = zod.output<typeof PatchedHogFlowGraphUpdateApi>

export const HogInvocationResultApi = zod.object({
    invocation_id: zod.string(),
    status: zod.string(),
    error_kind: zod.string(),
    error_message: zod.string(),
    distinct_id: zod.string(),
    person_id: zod.string(),
    scheduled_at: zod.iso.datetime({ offset: true }),
    started_at: zod.iso.datetime({ offset: true }).nullable(),
    finished_at: zod.iso.datetime({ offset: true }).nullable(),
    duration_ms: zod.number().nullable(),
    attempts: zod.number(),
    is_retry: zod.boolean(),
})

export type HogInvocationResultApi = zod.input<typeof HogInvocationResultApi>
export type HogInvocationResultApiOutput = zod.output<typeof HogInvocationResultApi>

export const HogInvocationResultDetailApi = zod.object({
    invocation_globals: zod
        .record(zod.string(), zod.unknown())
        .describe('The triggering payload (event\/person\/groups) the run executed against, as a JSON object.'),
    invocation_id: zod.string(),
    status: zod.string(),
    error_kind: zod.string(),
    error_message: zod.string(),
    distinct_id: zod.string(),
    person_id: zod.string(),
    scheduled_at: zod.iso.datetime({ offset: true }),
    started_at: zod.iso.datetime({ offset: true }).nullable(),
    finished_at: zod.iso.datetime({ offset: true }).nullable(),
    duration_ms: zod.number().nullable(),
    attempts: zod.number(),
    is_retry: zod.boolean(),
})

export type HogInvocationResultDetailApi = zod.input<typeof HogInvocationResultDetailApi>
export type HogInvocationResultDetailApiOutput = zod.output<typeof HogInvocationResultDetailApi>

export const hogFlowInvocationApiMockAsyncFunctionsDefault = true
export const hogFlowInvocationApiUseDraftDefault = false

export const HogFlowInvocationApi = zod.object({
    configuration: HogFlowApi.optional().describe('Optional override; omit to use saved definition.'),
    globals: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Test trigger payload, typically {event, person, groups}.'),
    mock_async_functions: zod
        .boolean()
        .default(hogFlowInvocationApiMockAsyncFunctionsDefault)
        .describe('True (default) mocks HTTP\/email\/SMS. False fires real side effects.'),
    current_action_id: zod
        .string()
        .optional()
        .describe(
            'Start execution from this action ID instead of the trigger. Each test run executes a single node and returns the next action id.'
        ),
    use_draft: zod
        .boolean()
        .default(hogFlowInvocationApiUseDraftDefault)
        .describe(
            "Test the workflow's staged draft instead of its live config. Set this only when workflows-get returns a non-null 'draft'; it can't be combined with an explicit configuration override."
        ),
})

export type HogFlowInvocationApi = zod.input<typeof HogFlowInvocationApi>
export type HogFlowInvocationApiOutput = zod.output<typeof HogFlowInvocationApi>

export const AppMetricSeriesApi = zod.object({
    name: zod.string(),
    values: zod.array(zod.number()),
})

export type AppMetricSeriesApi = zod.input<typeof AppMetricSeriesApi>
export type AppMetricSeriesApiOutput = zod.output<typeof AppMetricSeriesApi>

export const AppMetricsResponseApi = zod.object({
    labels: zod.array(zod.string()),
    series: zod.array(AppMetricSeriesApi),
})

export type AppMetricsResponseApi = zod.input<typeof AppMetricsResponseApi>
export type AppMetricsResponseApiOutput = zod.output<typeof AppMetricsResponseApi>

export const AppMetricsTotalsResponseApi = zod.object({
    totals: zod.record(zod.string(), zod.number()),
})

export type AppMetricsTotalsResponseApi = zod.input<typeof AppMetricsTotalsResponseApi>
export type AppMetricsTotalsResponseApiOutput = zod.output<typeof AppMetricsTotalsResponseApi>

export const hogFlowPublishRequestApiConfirmDefault = false

export const HogFlowPublishRequestApi = zod.object({
    confirm: zod
        .boolean()
        .default(hogFlowPublishRequestApiConfirmDefault)
        .describe(
            'False (default) previews the publish: returns the impact on people in-flight without changing anything. True applies the staged draft to the live workflow.'
        ),
    confirm_token: zod
        .string()
        .optional()
        .describe(
            'From the preview response — required when confirm=true. Expires after 15 minutes, and any draft edit invalidates it (409), so you always publish the exact draft you previewed.'
        ),
})

export type HogFlowPublishRequestApi = zod.input<typeof HogFlowPublishRequestApi>
export type HogFlowPublishRequestApiOutput = zod.output<typeof HogFlowPublishRequestApi>

export const HogFlowPublishImpactMoveTargetApi = zod.object({
    action_id: zod.string().describe('Id of the surviving step runs will continue at.'),
    name: zod.string().describe('Name of the surviving step.'),
})

export type HogFlowPublishImpactMoveTargetApi = zod.input<typeof HogFlowPublishImpactMoveTargetApi>
export type HogFlowPublishImpactMoveTargetApiOutput = zod.output<typeof HogFlowPublishImpactMoveTargetApi>

export const HogFlowPublishImpactDeletedStepApi = zod.object({
    action_id: zod.string().describe('Id of the step this publish deletes.'),
    name: zod.string().describe('Name of the deleted step.'),
    runs: zod
        .number()
        .nullable()
        .describe('About how many in-flight runs are parked on this step. Null when the count is unavailable.'),
    moves_to: zod
        .union([HogFlowPublishImpactMoveTargetApi, zod.null()])
        .describe('Where those runs continue (skip-forward). Null when nothing downstream survives.'),
    exits: zod.boolean().describe('True when runs parked here exit the workflow instead of moving forward.'),
})

export type HogFlowPublishImpactDeletedStepApi = zod.input<typeof HogFlowPublishImpactDeletedStepApi>
export type HogFlowPublishImpactDeletedStepApiOutput = zod.output<typeof HogFlowPublishImpactDeletedStepApi>

export const HogFlowPublishImpactEmptyVariableApi = zod.object({
    variable: zod.string().describe('Variable that renders empty for runs already past its producer.'),
    set_by: zod
        .string()
        .nullable()
        .describe('Id of the new action that sets it; null when the draft newly declares it as a workflow variable.'),
    referenced_by: zod.array(zod.string()).describe('Ids of steps whose content references the variable.'),
})

export type HogFlowPublishImpactEmptyVariableApi = zod.input<typeof HogFlowPublishImpactEmptyVariableApi>
export type HogFlowPublishImpactEmptyVariableApiOutput = zod.output<typeof HogFlowPublishImpactEmptyVariableApi>

export const HogFlowPublishImpactScheduleConflictApi = zod.object({
    schedule_id: zod.string().describe('Schedule whose variable overrides reference removed variables.'),
    variables: zod.array(zod.string()).describe('Override keys the draft no longer declares as workflow variables.'),
})

export type HogFlowPublishImpactScheduleConflictApi = zod.input<typeof HogFlowPublishImpactScheduleConflictApi>
export type HogFlowPublishImpactScheduleConflictApiOutput = zod.output<typeof HogFlowPublishImpactScheduleConflictApi>

export const HogFlowPublishImpactApi = zod.object({
    deleted_steps: zod
        .array(HogFlowPublishImpactDeletedStepApi)
        .describe('Per deleted step: how many runs are parked there and where they go. Empty for content-only edits.'),
    position_unknown: zod
        .number()
        .nullable()
        .describe('In-flight runs whose current step is unknown. Null when the count is unavailable.'),
    empty_variables: zod
        .array(HogFlowPublishImpactEmptyVariableApi)
        .describe('Variables that render empty for runs predating their producer.'),
    schedule_conflicts: zod
        .array(HogFlowPublishImpactScheduleConflictApi)
        .describe('Schedules overriding variables the draft removes.'),
})

export type HogFlowPublishImpactApi = zod.input<typeof HogFlowPublishImpactApi>
export type HogFlowPublishImpactApiOutput = zod.output<typeof HogFlowPublishImpactApi>

export const HogFlowPublishResponseApi = zod.object({
    published: zod.boolean().describe('Whether the draft was applied to the live workflow.'),
    in_flight_runs: zod
        .number()
        .nullable()
        .describe(
            'Runs currently in flight (parked on waits\/delays or executing) that will follow the new config once published. Null when the count is unavailable.'
        ),
    draft_updated_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe("The staged draft's timestamp, for reference; publishing is confirmed via confirm_token."),
    confirm_token: zod
        .string()
        .nullable()
        .describe('Echo this back with confirm=true to publish the previewed draft. Only set on previews.'),
    impact: zod
        .union([HogFlowPublishImpactApi, zod.null()])
        .describe('What publishing does to people in-flight. Only set on previews; counts are approximate.'),
    workflow: zod
        .union([HogFlowApi, zod.null()])
        .optional()
        .describe('The workflow after publishing (only set when published=true).'),
})

export type HogFlowPublishResponseApi = zod.input<typeof HogFlowPublishResponseApi>
export type HogFlowPublishResponseApiOutput = zod.output<typeof HogFlowPublishResponseApi>

export const HogInvocationRerunFilterStatusEnumApi = zod
    .enum(['running', 'succeeded', 'failed'])
    .describe('\* `running` - running\n\* `succeeded` - succeeded\n\* `failed` - failed')

export type HogInvocationRerunFilterStatusEnumApi = zod.input<typeof HogInvocationRerunFilterStatusEnumApi>
export type HogInvocationRerunFilterStatusEnumApiOutput = zod.output<typeof HogInvocationRerunFilterStatusEnumApi>

export const hogInvocationRerunFilterApiMaxAttemptsMax = 255

export const hogInvocationRerunFilterApiMaxCountMax = 10000

export const hogInvocationRerunFilterApiInvocationIdsMax = 10000

export const HogInvocationRerunFilterApi = zod
    .object({
        window_start: zod.iso.datetime({ offset: true }).describe('Inclusive lower bound on `scheduled_at` (UTC).'),
        window_end: zod.iso.datetime({ offset: true }).describe('Exclusive upper bound on `scheduled_at` (UTC).'),
        status: zod
            .array(HogInvocationRerunFilterStatusEnumApi)
            .optional()
            .describe("Restrict to invocations whose latest status is one of these. Defaults to ['failed']."),
        error_kind: zod
            .array(zod.string())
            .optional()
            .describe("Restrict to invocations whose error_kind matches one of these (e.g. 'http_5xx', 'timeout')."),
        max_attempts: zod
            .number()
            .min(1)
            .max(hogInvocationRerunFilterApiMaxAttemptsMax)
            .optional()
            .describe('Skip invocations that have already been attempted this many times or more.'),
        max_count: zod
            .number()
            .min(1)
            .max(hogInvocationRerunFilterApiMaxCountMax)
            .optional()
            .describe('Maximum number of invocations to rerun in this request. Server-side cap is 10000.'),
        invocation_ids: zod
            .array(zod.string())
            .max(hogInvocationRerunFilterApiInvocationIdsMax)
            .optional()
            .describe(
                'Optional restriction to specific invocation IDs within the window. Capped at 10000 per request. Always combined with `window_start`\/`window_end` so the ClickHouse query can be partition-pruned.'
            ),
    })
    .describe('Filter shape for the rerun endpoint. `window_start`\/`window_end` are required.')

export type HogInvocationRerunFilterApi = zod.input<typeof HogInvocationRerunFilterApi>
export type HogInvocationRerunFilterApiOutput = zod.output<typeof HogInvocationRerunFilterApi>

export const HogInvocationRerunRequestApi = zod
    .object({
        filter: HogInvocationRerunFilterApi.describe(
            'Required. `window_start` \/ `window_end` pin the query to a small set of date partitions on the `hog_invocation_results` table. Optional `invocation_ids` restricts to specific invocations within that window.'
        ),
    })
    .describe('Rerun invocations of a hog function or hog flow from their stored payloads.')

export type HogInvocationRerunRequestApi = zod.input<typeof HogInvocationRerunRequestApi>
export type HogInvocationRerunRequestApiOutput = zod.output<typeof HogInvocationRerunRequestApi>

export const HogInvocationRerunResponseApi = zod
    .object({
        rerun_job_id: zod
            .string()
            .describe('ID of the cyclotron wrapper job that will run the rerun. Use this to poll status.'),
        queued_count: zod.number().describe('Always 0 — rerun runs asynchronously. Kept for response shape stability.'),
        skipped_count: zod
            .number()
            .describe('Always 0 — rerun runs asynchronously. Kept for response shape stability.'),
    })
    .describe(
        'Response from the rerun endpoint. The endpoint only enqueues a wrapper\njob onto the cyclotron `rerun` queue — the actual ClickHouse paging and\nre-enqueue work happens asynchronously in the `cdp-rerun-worker` service.\nUse `rerun_job_id` to look up progress on the wrapper job later.'
    )

export type HogInvocationRerunResponseApi = zod.input<typeof HogInvocationRerunResponseApi>
export type HogInvocationRerunResponseApiOutput = zod.output<typeof HogInvocationRerunResponseApi>

export const HogFlowRevisionBasicApi = zod.object({
    version: zod.number().describe('Workflow version this snapshot was published as.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: zod.union([UserBasicApi, zod.null()]),
})

export type HogFlowRevisionBasicApi = zod.input<typeof HogFlowRevisionBasicApi>
export type HogFlowRevisionBasicApiOutput = zod.output<typeof HogFlowRevisionBasicApi>

export const PaginatedHogFlowRevisionBasicListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(HogFlowRevisionBasicApi),
})

export type PaginatedHogFlowRevisionBasicListApi = zod.input<typeof PaginatedHogFlowRevisionBasicListApi>
export type PaginatedHogFlowRevisionBasicListApiOutput = zod.output<typeof PaginatedHogFlowRevisionBasicListApi>

export const HogFlowRevisionApi = zod.object({
    version: zod.number().describe('Workflow version this snapshot was published as.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: zod.union([UserBasicApi, zod.null()]),
    content: zod
        .unknown()
        .describe("Full snapshot of the workflow's content fields (actions, edges, trigger, etc.) at this version."),
})

export type HogFlowRevisionApi = zod.input<typeof HogFlowRevisionApi>
export type HogFlowRevisionApiOutput = zod.output<typeof HogFlowRevisionApi>

export const hogFlowRevisionRestoreRequestApiOverwriteDefault = false

export const HogFlowRevisionRestoreRequestApi = zod.object({
    overwrite: zod
        .boolean()
        .default(hogFlowRevisionRestoreRequestApiOverwriteDefault)
        .describe(
            "Replace the open staged draft with this revision's content. Without it, restoring while a draft is open returns 409."
        ),
})

export type HogFlowRevisionRestoreRequestApi = zod.input<typeof HogFlowRevisionRestoreRequestApi>
export type HogFlowRevisionRestoreRequestApiOutput = zod.output<typeof HogFlowRevisionRestoreRequestApi>

export const patchedHogFlowScheduleApiTimezoneMax = 64

export const PatchedHogFlowScheduleApi = zod.object({
    id: zod.uuid().optional(),
    rrule: zod
        .string()
        .optional()
        .describe(
            "iCalendar RRULE string (e.g. 'FREQ=DAILY;INTERVAL=1'). Must produce occurrences at most once per hour."
        ),
    starts_at: zod.iso.datetime({ offset: true }).optional().describe('ISO 8601 datetime the schedule starts from.'),
    timezone: zod
        .string()
        .max(patchedHogFlowScheduleApiTimezoneMax)
        .optional()
        .describe("IANA timezone for interpreting the RRULE (default 'UTC')."),
    variables: zod
        .unknown()
        .optional()
        .describe('Variable value overrides merged with the workflow defaults on each run.'),
    status: HogFlowScheduleStatusEnumApi.optional().describe(
        "active, paused, or completed (set once the RRULE's COUNT\/UNTIL is exhausted).\n\n\* `active` - Active\n\* `paused` - Paused\n\* `completed` - Completed"
    ),
    next_run_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('Next scheduled fire time, computed by the scheduler.'),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
})

export type PatchedHogFlowScheduleApi = zod.input<typeof PatchedHogFlowScheduleApi>
export type PatchedHogFlowScheduleApiOutput = zod.output<typeof PatchedHogFlowScheduleApi>

export const EmailSendingSuspensionStatusApi = zod
    .object({
        email_sending_suspended: zod
            .boolean()
            .describe('True while workflow email sending is suspended for this project to protect deliverability.'),
        email_sending_suspended_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When email sending was suspended; null while sending is enabled.'),
        email_sending_suspension_reason: zod
            .string()
            .describe(
                'Staff-authored reason shown to customers alongside the suspension notice; empty when not suspended.'
            ),
    })
    .describe('Cheap suspension-only read for the persistent scene-wide banner — no reputation computation.')

export type EmailSendingSuspensionStatusApi = zod.input<typeof EmailSendingSuspensionStatusApi>
export type EmailSendingSuspensionStatusApiOutput = zod.output<typeof EmailSendingSuspensionStatusApi>

export const WorkflowStatsRowApi = zod.object({
    workflow_id: zod.string().describe('The workflow these counts are for.'),
    succeeded: zod.number().describe('Successful invocations in the window.'),
    failed: zod.number().describe('Failed invocations in the window.'),
})

export type WorkflowStatsRowApi = zod.input<typeof WorkflowStatsRowApi>
export type WorkflowStatsRowApiOutput = zod.output<typeof WorkflowStatsRowApi>

export const AwsTenantReputationHealthEnumApi = zod
    .enum(['healthy', 'warning', 'critical', 'suspended'])
    .describe('\* `healthy` - healthy\n\* `warning` - warning\n\* `critical` - critical\n\* `suspended` - suspended')

export type AwsTenantReputationHealthEnumApi = zod.input<typeof AwsTenantReputationHealthEnumApi>
export type AwsTenantReputationHealthEnumApiOutput = zod.output<typeof AwsTenantReputationHealthEnumApi>

export const SendingStatusEnumApi = zod
    .enum(['ENABLED', 'REINSTATED', 'DISABLED'])
    .describe('\* `ENABLED` - ENABLED\n\* `REINSTATED` - REINSTATED\n\* `DISABLED` - DISABLED')

export type SendingStatusEnumApi = zod.input<typeof SendingStatusEnumApi>
export type SendingStatusEnumApiOutput = zod.output<typeof SendingStatusEnumApi>

export const FindingTypeEnumApi = zod
    .enum(['DKIM', 'DMARC', 'SPF', 'BIMI', 'COMPLAINT', 'BOUNCE', 'FEEDBACK_3P', 'IP_LISTING'])
    .describe(
        '\* `DKIM` - DKIM\n\* `DMARC` - DMARC\n\* `SPF` - SPF\n\* `BIMI` - BIMI\n\* `COMPLAINT` - COMPLAINT\n\* `BOUNCE` - BOUNCE\n\* `FEEDBACK_3P` - FEEDBACK_3P\n\* `IP_LISTING` - IP_LISTING'
    )

export type FindingTypeEnumApi = zod.input<typeof FindingTypeEnumApi>
export type FindingTypeEnumApiOutput = zod.output<typeof FindingTypeEnumApi>

export const ImpactEnumApi = zod.enum(['LOW', 'HIGH']).describe('\* `LOW` - LOW\n\* `HIGH` - HIGH')

export type ImpactEnumApi = zod.input<typeof ImpactEnumApi>
export type ImpactEnumApiOutput = zod.output<typeof ImpactEnumApi>

export const AwsTenantFindingApi = zod
    .object({
        finding_type: FindingTypeEnumApi.describe(
            'What the finding is about: authentication setup (DKIM\/DMARC\/SPF\/BIMI), recipient signals (COMPLAINT\/BOUNCE\/FEEDBACK_3P), or a blocklist listing (IP_LISTING).\n\n\* `DKIM` - DKIM\n\* `DMARC` - DMARC\n\* `SPF` - SPF\n\* `BIMI` - BIMI\n\* `COMPLAINT` - COMPLAINT\n\* `BOUNCE` - BOUNCE\n\* `FEEDBACK_3P` - FEEDBACK_3P\n\* `IP_LISTING` - IP_LISTING'
        ),
        impact: ImpactEnumApi.describe(
            "AWS's impact rating. HIGH-impact findings can pause the project's sending automatically.\n\n\* `LOW` - LOW\n\* `HIGH` - HIGH"
        ),
        description: zod
            .string()
            .describe(
                "AWS's short description of the finding. Often a terse disambiguator (e.g. DKIM1) rather than full remediation prose — finding_type carries the remediation category."
            ),
        last_updated_at: zod.iso.datetime({ offset: true }).nullable().describe('When AWS last updated this finding.'),
    })
    .describe("An open reputation finding AWS SES raised for this project's email sending.")

export type AwsTenantFindingApi = zod.input<typeof AwsTenantFindingApi>
export type AwsTenantFindingApiOutput = zod.output<typeof AwsTenantFindingApi>

export const AwsTenantReputationApi = zod
    .object({
        health: AwsTenantReputationHealthEnumApi.describe(
            "Overall health derived from AWS's verdicts: healthy (no findings), warning (low-impact findings), critical (high-impact findings — sending may be paused), suspended (the SES tenant's sending is paused). Reflects AWS state only; PostHog-initiated suspensions are reported separately via email_sending_suspended.\n\n\* `healthy` - healthy\n\* `warning` - warning\n\* `critical` - critical\n\* `suspended` - suspended"
        ),
        sending_status: SendingStatusEnumApi.describe(
            "The tenant's aggregate sending status. REINSTATED means sending was re-enabled after a pause and AWS is re-monitoring it.\n\n\* `ENABLED` - ENABLED\n\* `REINSTATED` - REINSTATED\n\* `DISABLED` - DISABLED"
        ),
        findings: zod.array(AwsTenantFindingApi).describe("Open findings, if any, with AWS's remediation guidance."),
    })
    .describe("Authoritative reputation for this project's SES tenant, as judged and enforced by AWS.")

export type AwsTenantReputationApi = zod.input<typeof AwsTenantReputationApi>
export type AwsTenantReputationApiOutput = zod.output<typeof AwsTenantReputationApi>

export const EmailSendingRatesApi = zod
    .object({
        bounce_rate: zod
            .number()
            .describe(
                'Hard (permanent) bounces \/ emails sent over the last 30 days (0-1), matching how AWS counts its bounce rate — transient bounces (greylisting, mailbox full) are excluded. Bounces are counted when the feedback arrives, so the ratio is approximate at the window boundary and capped at 1.'
            ),
        complaint_rate: zod
            .number()
            .describe(
                'Spam complaints \/ emails sent over the last 30 days (0-1). Complaints are counted when the feedback arrives, so the ratio is approximate at the window boundary and capped at 1.'
            ),
        emails_sent: zod.number().describe('Emails sent in the last 30 days.'),
    })
    .describe('Bounce\/complaint rates over the last 30 days of workflow email, computed on the fly from app metrics.')

export type EmailSendingRatesApi = zod.input<typeof EmailSendingRatesApi>
export type EmailSendingRatesApiOutput = zod.output<typeof EmailSendingRatesApi>

export const WorkflowEmailSendingRatesApi = zod
    .object({
        bounce_rate: zod
            .number()
            .describe(
                'Hard (permanent) bounces \/ emails sent over the last 30 days (0-1), matching how AWS counts its bounce rate — transient bounces (greylisting, mailbox full) are excluded. Bounces are counted when the feedback arrives, so the ratio is approximate at the window boundary and capped at 1.'
            ),
        complaint_rate: zod
            .number()
            .describe(
                'Spam complaints \/ emails sent over the last 30 days (0-1). Complaints are counted when the feedback arrives, so the ratio is approximate at the window boundary and capped at 1.'
            ),
        emails_sent: zod.number().describe('Emails sent in the last 30 days.'),
        hog_flow_id: zod.uuid().describe('The workflow these rates are for.'),
        hog_flow_name: zod.string().describe('Display name of the workflow; empty for unnamed workflows.'),
    })
    .describe('Bounce\/complaint rates over the last 30 days of workflow email, computed on the fly from app metrics.')

export type WorkflowEmailSendingRatesApi = zod.input<typeof WorkflowEmailSendingRatesApi>
export type WorkflowEmailSendingRatesApiOutput = zod.output<typeof WorkflowEmailSendingRatesApi>

export const TeamEmailReputationResponseApi = zod.object({
    aws: zod
        .union([AwsTenantReputationApi, zod.null()])
        .describe(
            "Sending health as judged and enforced by AWS SES for this project's tenant; null when the caller lacks project-wide workflow access, no tenant is provisioned, or AWS is unreachable."
        ),
    reputation: zod
        .union([EmailSendingRatesApi, zod.null()])
        .describe(
            'Project-wide rates across all workflow email in the last 30 days (including sends from since-deleted workflows); null when nothing was sent.'
        ),
    workflows: zod
        .array(WorkflowEmailSendingRatesApi)
        .describe('Rates per workflow, worst first (complaint rate, then bounce rate), capped at the worst 50.'),
    email_sending_suspended: zod
        .boolean()
        .describe('True while workflow email sending is suspended for this project to protect deliverability.'),
    email_sending_suspended_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When email sending was suspended; null while sending is enabled.'),
    email_sending_suspension_reason: zod
        .string()
        .describe(
            'Staff-authored reason shown to customers alongside the suspension notice; empty when not suspended.'
        ),
})

export type TeamEmailReputationResponseApi = zod.input<typeof TeamEmailReputationResponseApi>
export type TeamEmailReputationResponseApiOutput = zod.output<typeof TeamEmailReputationResponseApi>

export const DedupeKeyEnumApi = zod.enum(['email']).describe('\* `email` - email')

export type DedupeKeyEnumApi = zod.input<typeof DedupeKeyEnumApi>
export type DedupeKeyEnumApiOutput = zod.output<typeof DedupeKeyEnumApi>

export const BlastRadiusRequestApi = zod.object({
    filters: zod.record(zod.string(), zod.unknown()).describe('Property filters to apply'),
    group_type_index: zod.number().nullish().describe('Group type index for group-based targeting'),
    dedupe_key: zod
        .union([DedupeKeyEnumApi, zod.null()])
        .optional()
        .describe(
            "When 'email', count unique email addresses instead of persons, matching how batch email sends deduplicate recipients.\n\n\* `email` - email"
        ),
})

export type BlastRadiusRequestApi = zod.input<typeof BlastRadiusRequestApi>
export type BlastRadiusRequestApiOutput = zod.output<typeof BlastRadiusRequestApi>

export const BlastRadiusApi = zod.object({
    affected: zod.number().describe('Number of users matching the filters'),
    total: zod.number().describe('Total number of users'),
    limit: zod.number().describe('Maximum allowed audience size for batch triggers for this team.'),
    dedupe_key: zod
        .union([DedupeKeyEnumApi, zod.null()])
        .describe(
            "The dedupe key that was actually applied to 'affected'. 'email' means it counts unique email addresses; null means it counts persons.\n\n\* `email` - email"
        ),
    confirm_token: zod
        .string()
        .describe(
            "Proof this audience was previewed: pass it to the batch dispatch (confirm_token) after echoing 'affected' to the user. Signs these exact filters; expires in 15 minutes."
        ),
})

export type BlastRadiusApi = zod.input<typeof BlastRadiusApi>
export type BlastRadiusApiOutput = zod.output<typeof BlastRadiusApi>
