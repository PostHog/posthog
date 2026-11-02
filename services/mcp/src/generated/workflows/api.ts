/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 33 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const HogFlowsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const HogFlowsListQueryParams = () => zod.object({
    broadcast_eligible: zod
        .boolean()
        .optional()
        .describe(
            'Pass `true` to return broadcasts plus the ordinary workflows the broadcasts UI can render: a batch trigger and a single email step.'
        ),
    broadcast_status: zod
        .string()
        .optional()
        .describe(
            'Comma-separated broadcast statuses as the broadcasts UI shows them: draft, scheduled, sending, sent, failed, archived. Scheduled, sending, sent and failed come from the latest run and whether a schedule still has sends to come.'
        ),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: zod.string().optional().describe('Filter to workflows created by the user with this uuid.'),
    id: zod.string().optional(),
    latest_send_first: zod
        .boolean()
        .optional()
        .describe(
            "Pass `true` to order by when each workflow's newest completed run finished, newest first. Workflows that never finished a run come last."
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    optimization_enabled: zod.boolean().optional().describe('Only workflows someone turned suggestions on for.'),
    origin_product: zod
        .enum(['broadcasts', 'loops', 'transactional_emails'])
        .optional()
        .describe('Filter to workflows owned by a product surface, e.g. `loops` for Desktop loops.'),
    search: zod
        .string()
        .optional()
        .describe(
            'Case-insensitive search. Matches workflow name, description and tag names first; only when nothing matches those, it matches step names and the subject line, preheader and body text of email steps, in both the live workflow and its pending draft.'
        ),
    source_record: zod
        .string()
        .optional()
        .describe("Filter to workflows started from this record, as '<kind>:<id>', e.g. `early_access:<id>`."),
    status: zod
        .enum(['active', 'archived', 'draft'])
        .optional()
        .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'),
    tags: zod
        .string()
        .optional()
        .describe(
            'JSON-encoded list of tag names, e.g. [\"growth\", \"onboarding\"]. Returns workflows that carry at least one of these tags.'
        ),
    trigger: zod
        .string()
        .optional()
        .describe(
            'Filter by trigger config as a JSON object. Returns workflows whose trigger contains the given object, e.g. {\"type\": \"event\"}.'
        ),
    type: zod
        .string()
        .optional()
        .describe(
            'Comma-separated workflow types. `loop` and `broadcast` return the workflows those surfaces own; `messaging` returns the remaining workflows with an email, SMS, or push action, and `automation` the rest.'
        ),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
})

export const HogFlowsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogFlowsCreateBodyNameMax = 400

export const hogFlowsCreateBodyDescriptionDefault = ``
export const hogFlowsCreateBodyTagsItemMax = 255

export const hogFlowsCreateBodyTagsMax = 10

export const hogFlowsCreateBodySourceRecordMax = 255

export const hogFlowsCreateBodySourceRecordRegExp = new RegExp('^[a-z_]+:[A-Za-z0-9_-]+$')
export const hogFlowsCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsCreateBodyConversionOneEventsItemFiltersOneSourceDefault = `events`
export const hogFlowsCreateBodyConversionOneWindowMax = 32

export const hogFlowsCreateBodyConversionOneWindowRegExp = new RegExp('^(?:[0-9]+(?:\\.[0-9]+)?|\\.[0-9]+)[dhms]$')
export const hogFlowsCreateBodyEmailSendingRateLimitOneCountMax = 1000000

export const hogFlowsCreateBodyActionsItemIdMax = 200

export const hogFlowsCreateBodyActionsItemNameMax = 400

export const hogFlowsCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsCreateBodyActionsItemConfigTwoConditionFiltersOneSourceDefault = `events`
export const hogFlowsCreateBodyActionsItemConfigTwoEventsItemFiltersOneSourceDefault = `events`

export const HogFlowsCreateBody = () => zod
    .object({
        name: zod.string().max(hogFlowsCreateBodyNameMax).nullish().describe('Workflow name.'),
        description: zod.string().default(hogFlowsCreateBodyDescriptionDefault).describe('Optional description.'),
        tags: zod
            .array(zod.string().max(hogFlowsCreateBodyTagsItemMax))
            .max(hogFlowsCreateBodyTagsMax)
            .optional()
            .describe(
                'Tags for organizing workflows, for example by team or use case. Tags are shared with the rest of the project. Omit to keep the current tags, send an empty list to remove them all.'
            ),
        status: zod
            .enum(['draft', 'active', 'archived'])
            .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived')
            .optional()
            .describe(
                'draft (no execution), active (live), archived (disabled).\n\n\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'
            ),
        origin_product: zod
            .union([
                zod
                    .enum(['loops', 'broadcasts', 'transactional_emails'])
                    .describe(
                        '\* `loops` - Loops\n\* `broadcasts` - Broadcasts\n\* `transactional_emails` - Transactional emails'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Product surface that owns this workflow (e.g. `loops` for Desktop loops). Set only when creating a workflow. Filter the list with `?origin_product=`.\n\n\* `loops` - Loops\n\* `broadcasts` - Broadcasts\n\* `transactional_emails` - Transactional emails'
            ),
        source_record: zod
            .string()
            .max(hogFlowsCreateBodySourceRecordMax)
            .regex(hogFlowsCreateBodySourceRecordRegExp)
            .nullish()
            .describe(
                "The record another product's entry point started this workflow from, as '<kind>:<id>'. Set only when creating a workflow. Filter the list with `?source_record=`."
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
                                            .enum([
                                                'events',
                                                'internal-events',
                                                'person-updates',
                                                'data-warehouse-table',
                                                'data-warehouse-view',
                                            ])
                                            .describe(
                                                '\* `events` - events\n\* `internal-events` - internal-events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table\n\* `data-warehouse-view` - data-warehouse-view'
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
                                        bytecode_contract: zod.string().optional(),
                                    })
                                    .describe(
                                        "Event\/action filters for this conversion event, same shape as trigger filters: {events: [{id, name, type: 'events', properties?: [<cond>]}], actions?: [...], properties?: [<cond>]}. bytecode is compiled server-side."
                                    ),
                            })
                        )
                        .optional()
                        .describe(
                            "Event-based conversion goals: [{filters: {events: [{id, name, type: 'events'}], ...}}]."
                        ),
                    window: zod
                        .string()
                        .max(hogFlowsCreateBodyConversionOneWindowMax)
                        .regex(hogFlowsCreateBodyConversionOneWindowRegExp)
                        .nullish()
                        .describe(
                            "How long after entering the workflow a conversion still counts, as a duration string: '7d', '12h', '30m', '45s'. Same form the delay steps use. Must be longer than zero, and at most '365d'. Omit it to use the default of 90 days."
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
                "Conversion goal. filters: ARRAY of property conditions [{key, value, operator, type: event|person|group}]; events: event-based goals [{filters: {events: [...]}}]; window: how long after entry a conversion counts, as a duration string such as '7d' or '12h', maximum '365d'. Required for exit_on_conversion \/ exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side."
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
                "exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion'). Only event and cohort triggers are re-checked, so on any other trigger these two are stored as exit_only_at_end and exit_on_conversion. A cohort trigger no longer matches once the person leaves the cohort (or rejoins it, for a 'left' trigger).\n\n\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End"
            ),
        email_sending_rate_limit: zod
            .union([
                zod.object({
                    count: zod
                        .number()
                        .min(1)
                        .max(hogFlowsCreateBodyEmailSendingRateLimitOneCountMax)
                        .describe('Maximum number of emails this workflow sends per period.'),
                    period: zod
                        .enum(['minute', 'hour'])
                        .describe('\* `minute` - minute\n\* `hour` - hour')
                        .describe(
                            'Window the count applies to. Sends over the limit are delayed until capacity frees up, not dropped.\n\n\* `minute` - minute\n\* `hour` - hour'
                        ),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                "Optional email pacing for deliverability: {count, period: 'minute' | 'hour'}. The email worker spreads this workflow's sends to stay under the limit; over-limit sends wait for capacity instead of failing. Null disables pacing."
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
                            "Required for type='branch'. conditional_branch: index into config.conditions[index]. random_cohort_branch: index into config.cohorts[index]. wait_until_condition: use index:0 — it advances via the index:0 branch edge when it resolves (a condition match or an events entry firing)."
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
                    id: zod
                        .string()
                        .max(hogFlowsCreateBodyActionsItemIdMax)
                        .describe('Unique node ID within the workflow.'),
                    name: zod.string().max(hogFlowsCreateBodyActionsItemNameMax).describe('Display name.'),
                    description: zod
                        .string()
                        .default(hogFlowsCreateBodyActionsItemDescriptionDefault)
                        .describe('Optional description.'),
                    on_error: zod
                        .union([
                            zod.enum(['continue', 'abort']).describe('\* `continue` - continue\n\* `abort` - abort'),
                            zod.null(),
                        ])
                        .optional()
                        .describe(
                            'On failure: continue (skip the action and proceed) or abort (stop the run).\n\n\* `continue` - continue\n\* `abort` - abort'
                        ),
                    created_at: zod.number().optional().describe('Created at (epoch ms). Frontend-managed.'),
                    updated_at: zod.number().optional().describe('Updated at (epoch ms). Frontend-managed.'),
                    filters: zod
                        .union([
                            zod.object({
                                source: zod
                                    .enum([
                                        'events',
                                        'internal-events',
                                        'person-updates',
                                        'data-warehouse-table',
                                        'data-warehouse-view',
                                    ])
                                    .describe(
                                        '\* `events` - events\n\* `internal-events` - internal-events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table\n\* `data-warehouse-view` - data-warehouse-view'
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
                                bytecode_contract: zod.string().optional(),
                            }),
                            zod.null(),
                        ])
                        .optional()
                        .describe('Property filters gating this action.'),
                    type: zod
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
                        .describe(
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
                                                .union([
                                                    zod.object({
                                                        source: zod
                                                            .enum([
                                                                'events',
                                                                'internal-events',
                                                                'person-updates',
                                                                'data-warehouse-table',
                                                                'data-warehouse-view',
                                                            ])
                                                            .describe(
                                                                '\* `events` - events\n\* `internal-events` - internal-events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table\n\* `data-warehouse-view` - data-warehouse-view'
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
                                                        bytecode_contract: zod.string().optional(),
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
                                                                    'internal-events',
                                                                    'person-updates',
                                                                    'data-warehouse-table',
                                                                    'data-warehouse-view',
                                                                ])
                                                                .describe(
                                                                    '\* `events` - events\n\* `internal-events` - internal-events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table\n\* `data-warehouse-view` - data-warehouse-view'
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
                                                            bytecode_contract: zod.string().optional(),
                                                        }),
                                                        zod.null(),
                                                    ])
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
                                        .describe(
                                            "'<number><unit>' with unit s|m|h|d, e.g. '30m' (same rules as delay)."
                                        ),
                                })
                                .describe(
                                    "Config for type='wait_until_condition'. Provide 'condition' and\/or 'events' — an events-only wait (no condition) is valid."
                                ),
                        ])
                        .describe(
                            "Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel|internal-event, filters?}. An active event trigger must name at least one event, action or property filter; with filters.source 'person-updates' that means at least one property filter. internal-event requires filters.events naming one or more allowed event ids, and runs once for each matching event on the internal-events stream. Runs are person-less, so person-dependent steps are rejected. $slack_message_received takes filters: {properties: [<cond>]} over the message properties (channel, user, bot_id, text, subtype, is_thread_reply), and requires an exact-match channel filter; without one it runs on every message in every connected channel. $github_event_received takes filters: {properties: [<cond>]} over the delivery properties (repository, event_type, action, sender, bot_sender, own_app, author_association, actor_access, title, body, review_state, branch, repository_visibility), and requires exact-match repository and event_type filters; without them it runs on every delivery from every connected repository. webhook and manual triggers also require template_id: 'template-source-webhook', and tracking_pixel requires template_id: 'template-source-webhook-pixel'. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}, or {key: 'id', type: 'cohort', value: <cohort_id>, operator: 'in'} to reference a cohort. batch triggers may set filters.audience_type: 'persons' (default) or 'accounts'. An accounts audience fans out one run per customer analytics account and takes account filters instead: properties entries of type 'account_custom_property' (key = definition id), plus tag_names: [<str>], assignment_status: 'all'|'assigned'|'unassigned', and assigned_to_user_ids: [<int>] when assignment_status is 'assigned'. all_roles_unassigned remains accepted for workflows saved before assignment_status was added. function\*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. function_email also accepts tracking_enabled?: <bool> (default true) - when false, no open pixel is injected, links are not rewritten, and the send skips ESP-level open\/click tracking, so opens and clicks are not recorded for that step (delivery\/bounce\/unsubscribe still are). function_push also accepts sensitive?: <bool> (default false) - when true, the notification is still sent but PostHog keeps no copy of its title, subtitle, body or image, and the run keeps no variables, so it can't be rerun. Dictionary input values are template strings too — write booleans\/numbers as single-expression templates ('{true}', '{42}'), which evaluate to the typed value. delay: waits a fixed span or until a per-person\/-event date — set EXACTLY ONE of delay_duration or delay_until. {delay_duration: '<number><unit>'} where unit is s|m|h|d, at most 365d, 24h, 60m or 60s. Fractions OK ('1.5d'=36h). A larger value is rejected. delay_until: {expression: '<SQL>', offset?: '<±number><unit>'} waits until the date expression evaluates to (an ISO string, unix seconds, or a date value all resolve to the same instant); offset is a signed duration shifting it ('-1d' a day before, '2h' two hours after). expression is compiled server-side, so any bytecode sent with it is discarded. A person property is person.properties.<key>; an event property is properties.<key>, as the 'event.' prefix resolves to nothing and aborts the run. Optional timezone (IANA name), use_person_timezone (read $geoip_time_zone) and fallback_timezone decide which zone a date with no offset of its own is read in; a date that states an offset, and unix seconds, ignore them. Default UTC. Optional sibling max_delay_duration (default 30d, at most 365d, same '<number><unit>' format) caps how far past the step's start the wait may run. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. random_cohort_branch: {cohorts: [{percentage: <number>, name?}, ...]}. Index N matches the 'branch' edge with index:N; percentages are relative weights, so they should sum to 100 but a total above or below that still splits traffic in the given proportions. wait_until_condition: {condition: {filters}, events?: [{filters: {events: [{id, name, type: 'events'}], actions?: [...]}, name?}], max_wait_duration: <duration>} (same format as delay, at most 30d). Continues when condition.filters match OR any events entry fires; each events entry must target at least one event or action. On resolution (a condition match or any events entry firing) it advances via the 'branch' edge with index:0; the max_wait_duration timeout falls through the 'continue' edge. exit: {reason}."
                        ),
                    output_variable: zod
                        .unknown()
                        .optional()
                        .describe(
                            'Output variable for downstream actions: {key, result_path?, spread?, label?} or a list of those.'
                        ),
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

export const HogFlowsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const HogFlowsPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogFlowsPartialUpdateBodyNameMax = 400

export const hogFlowsPartialUpdateBodyTagsItemMax = 255

export const hogFlowsPartialUpdateBodyTagsMax = 10

export const hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsPartialUpdateBodyConversionOneEventsItemFiltersOneSourceDefault = `events`
export const hogFlowsPartialUpdateBodyConversionOneWindowMax = 32

export const hogFlowsPartialUpdateBodyConversionOneWindowRegExp = new RegExp(
    '^(?:[0-9]+(?:\\.[0-9]+)?|\\.[0-9]+)[dhms]$'
)
export const hogFlowsPartialUpdateBodyEmailSendingRateLimitOneCountMax = 1000000

export const HogFlowsPartialUpdateBody = () => zod
    .object({
        name: zod.string().max(hogFlowsPartialUpdateBodyNameMax).nullish().describe('Workflow name.'),
        description: zod.string().optional().describe('Optional description.'),
        tags: zod
            .array(zod.string().max(hogFlowsPartialUpdateBodyTagsItemMax))
            .max(hogFlowsPartialUpdateBodyTagsMax)
            .optional()
            .describe(
                'Tags for organizing workflows, for example by team or use case. Tags are shared with the rest of the project. Omit to keep the current tags, send an empty list to remove them all.'
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
                                            .enum([
                                                'events',
                                                'internal-events',
                                                'person-updates',
                                                'data-warehouse-table',
                                                'data-warehouse-view',
                                            ])
                                            .describe(
                                                '\* `events` - events\n\* `internal-events` - internal-events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table\n\* `data-warehouse-view` - data-warehouse-view'
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
                                        bytecode_contract: zod.string().optional(),
                                    })
                                    .describe(
                                        "Event\/action filters for this conversion event, same shape as trigger filters: {events: [{id, name, type: 'events', properties?: [<cond>]}], actions?: [...], properties?: [<cond>]}. bytecode is compiled server-side."
                                    ),
                            })
                        )
                        .optional()
                        .describe(
                            "Event-based conversion goals: [{filters: {events: [{id, name, type: 'events'}], ...}}]."
                        ),
                    window: zod
                        .string()
                        .max(hogFlowsPartialUpdateBodyConversionOneWindowMax)
                        .regex(hogFlowsPartialUpdateBodyConversionOneWindowRegExp)
                        .nullish()
                        .describe(
                            "How long after entering the workflow a conversion still counts, as a duration string: '7d', '12h', '30m', '45s'. Same form the delay steps use. Must be longer than zero, and at most '365d'. Omit it to use the default of 90 days."
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
                "Conversion goal. filters: ARRAY of property conditions [{key, value, operator, type: event|person|group}]; events: event-based goals [{filters: {events: [...]}}]; window: how long after entry a conversion counts, as a duration string such as '7d' or '12h', maximum '365d'. Required for exit_on_conversion \/ exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side."
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
                "exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion'). Only event and cohort triggers are re-checked, so on any other trigger these two are stored as exit_only_at_end and exit_on_conversion. A cohort trigger no longer matches once the person leaves the cohort (or rejoins it, for a 'left' trigger).\n\n\* `exit_on_conversion` - Conversion\n\* `exit_on_trigger_not_matched` - Trigger Not Matched\n\* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n\* `exit_only_at_end` - Only At End"
            ),
        email_sending_rate_limit: zod
            .union([
                zod.object({
                    count: zod
                        .number()
                        .min(1)
                        .max(hogFlowsPartialUpdateBodyEmailSendingRateLimitOneCountMax)
                        .describe('Maximum number of emails this workflow sends per period.'),
                    period: zod
                        .enum(['minute', 'hour'])
                        .describe('\* `minute` - minute\n\* `hour` - hour')
                        .describe(
                            'Window the count applies to. Sends over the limit are delayed until capacity frees up, not dropped.\n\n\* `minute` - minute\n\* `hour` - hour'
                        ),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                "Optional email pacing for deliverability: {count, period: 'minute' | 'hour'}. The email worker spreads this workflow's sends to stay under the limit; over-limit sends wait for capacity instead of failing. Null disables pacing."
            ),
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

export const HogFlowsActionsEmailPartialUpdateParams = () => zod.object({
    action_id: zod.string().describe('Id of the function_email step to edit.'),
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const HogFlowsActionsEmailPartialUpdateBody = () => zod.object({
    base_updated_at: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe(
            'Optimistic concurrency: the updated_at (or draft_updated_at) last loaded. If the stored workflow is newer, the patch is rejected with 409 instead of clobbering a concurrent edit.'
        ),
    operations: zod
        .array(
            zod.object({
                op: zod
                    .enum([
                        'update_content',
                        'update_column',
                        'update_row',
                        'update_body',
                        'add_content',
                        'remove_content',
                        'move_content',
                        'add_row',
                        'remove_row',
                    ])
                    .describe(
                        '\* `update_content` - update_content\n\* `update_column` - update_column\n\* `update_row` - update_row\n\* `update_body` - update_body\n\* `add_content` - add_content\n\* `remove_content` - remove_content\n\* `move_content` - move_content\n\* `add_row` - add_row\n\* `remove_row` - remove_row'
                    )
                    .describe(
                        "Design edit. update_content {id, patch}: deep-merge patch into the content block's fields (a null leaf deletes that key) — the surgical path, e.g. change just values.text. update_row \/ update_column {id, patch} and update_body {patch}: same deep-merge for row\/column\/body-level settings. add_content {column_id, content, index?}: insert a content block into a column (id and Unlayer numbering are filled in for you). remove_content {id} \/ move_content {id, column_id, index?}: delete or relocate a block. add_row {row, index?} \/ remove_row {id}: add or delete a row.\n\n\* `update_content` - update_content\n\* `update_column` - update_column\n\* `update_row` - update_row\n\* `update_body` - update_body\n\* `add_content` - add_content\n\* `remove_content` - remove_content\n\* `move_content` - move_content\n\* `add_row` - add_row\n\* `remove_row` - remove_row"
                    ),
                id: zod
                    .string()
                    .optional()
                    .describe(
                        'Target node id. Required for update_content\/column\/row, remove_content, remove_row, move_content.'
                    ),
                column_id: zod
                    .string()
                    .optional()
                    .describe('Target column id. Required for add_content and move_content.'),
                patch: zod
                    .unknown()
                    .optional()
                    .describe(
                        "update_\* only. Partial fields deep-merged into the existing node; a null leaf deletes that key. e.g. {values: {text: '<p>Hi<\/p>'}} changes only the block's text."
                    ),
                content: zod
                    .unknown()
                    .optional()
                    .describe(
                        "add_content only. A content block {type, values: {...}}; omit id and values._meta — they're assigned server-side. type is one of text, heading, button, image, divider, html, etc."
                    ),
                row: zod
                    .unknown()
                    .optional()
                    .describe(
                        'add_row only. A full row {cells, columns: [{contents: [...], values}], values}; ids and Unlayer numbering are assigned server-side for the row and everything nested in it.'
                    ),
                index: zod
                    .number()
                    .optional()
                    .describe('add_\*\/move_content only. 0-based insert position; omit to append to the end.'),
            })
        )
        .optional()
        .describe(
            "Ordered design edits applied atomically to this step's email design - the same operations as the email template patch. The result is re-rendered to HTML server-side, so the sent email always matches the patched design."
        ),
    email_patch: zod
        .unknown()
        .optional()
        .describe(
            "Partial email fields deep-merged into the step's email (a null leaf deletes the key): subject, preheader, text, to, from, replyTo, cc, bcc. The sender is from: {integrationId, email?, name?}, where email and name are optional templated overrides resolved per invocation; the address must resolve to the selected sender's verified domain or the send fails. The design is edited via operations, and html is always re-rendered from it."
        ),
})

export const HogFlowsBatchJobsListParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Move a workflow to broadcasts. It keeps its id, runs and metrics, leaves the workflows list and opens
 * in the broadcast editor. This cannot be undone.
 */
export const HogFlowsConvertToBroadcastParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const HogFlowsDiscardDraftCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const HogFlowsGraphPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const HogFlowsGraphPartialUpdateBody = () => zod.object({
    base_updated_at: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe(
            'Optimistic concurrency: the updated_at (or draft_updated_at) last loaded. If the stored graph is newer, the patch is rejected with 409 instead of clobbering a concurrent edit.'
        ),
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
                        '\* `update_action` - update_action\n\* `add_action` - add_action\n\* `remove_action` - remove_action\n\* `add_edge` - add_edge\n\* `remove_edge` - remove_edge\n\* `replace_action_edges` - replace_action_edges'
                    )
                    .describe(
                        "Graph edit. update_action {id, patch}: deep-merge patch into the action's fields (a null leaf deletes that key) — the surgical path for tweaking one config value. add_action {action, edges?}: append a full action node, optionally wiring its edges in the same op. remove_action {id}: delete a node and reconnect its incoming edges to its first outgoer. add_edge {edge} \/ remove_edge {edge}: add or delete one edge. replace_action_edges {id, edges}: replace this action's outgoing edges with the given set (use when adding\/removing branch conditions); incoming edges are left intact.\n\n\* `update_action` - update_action\n\* `add_action` - add_action\n\* `remove_action` - remove_action\n\* `add_edge` - add_edge\n\* `remove_edge` - remove_edge\n\* `replace_action_edges` - replace_action_edges"
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
                            .describe('\* `continue` - continue\n\* `branch` - branch')
                            .describe(
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
                    .optional()
                    .describe('add_edge \/ remove_edge only. The edge {from, to, type, index?}.'),
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
                                    "Required for type='branch'. conditional_branch: index into config.conditions[index]. random_cohort_branch: index into config.cohorts[index]. wait_until_condition: use index:0 — it advances via the index:0 branch edge when it resolves (a condition match or an events entry firing)."
                                ),
                            from: zod.string().describe('Source action id.'),
                        })
                    )
                    .optional()
                    .describe(
                        "replace_action_edges: the complete set of the action's outgoing edges (incoming edges are preserved). add_action: optional edges to wire the new node in the same op."
                    ),
            })
        )
        .optional()
        .describe(
            "Ordered graph edits applied atomically to a draft workflow: the stored graph is read, the ops are applied in order, the result is fully validated, and it's saved only if valid — otherwise the workflow is unchanged. Reference nodes\/edges by id so you never resend the whole graph. The full updated workflow is returned."
        ),
})

export const HogFlowsInvocationResultsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogFlowsInvocationResultsRetrieveQueryAfterDefault = `-7d`

export const hogFlowsInvocationResultsRetrieveQueryErrorMessageContainsMax = 200

export const hogFlowsInvocationResultsRetrieveQueryLimitDefault = 50
export const hogFlowsInvocationResultsRetrieveQueryLimitMax = 500

export const HogFlowsInvocationResultsRetrieveQueryParams = () => zod.object({
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
    error_message_contains: zod
        .string()
        .min(1)
        .max(hogFlowsInvocationResultsRetrieveQueryErrorMessageContainsMax)
        .optional()
        .describe(
            "Only return invocations whose latest error_message contains this substring (case-insensitive). Matches the rerun endpoint's filter of the same name, so callers can check what a rerun would target."
        ),
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

export const HogFlowsInvocationResultRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    invocation_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const HogFlowsInvocationsCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogFlowsInvocationsCreateBodyMockAsyncFunctionsDefault = true
export const hogFlowsInvocationsCreateBodyUseDraftDefault = false

export const HogFlowsInvocationsCreateBody = () => zod.object({
    globals: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            "Test trigger payload, typically {event, person, groups}. Shape it like the trigger's real payload: an event matching the trigger filters for event triggers, or for an internal-event trigger an event named in its filters.events (e.g. $slack_message_received with Slack properties like channel, user, text, ts) and no person."
        ),
    mock_async_functions: zod
        .boolean()
        .default(hogFlowsInvocationsCreateBodyMockAsyncFunctionsDefault)
        .describe('True (default) mocks HTTP\/email\/SMS. False fires real side effects.'),
    current_action_id: zod
        .string()
        .optional()
        .describe(
            'Start execution from this action ID instead of the trigger. Each test run executes a single node and returns the next action id.'
        ),
    use_draft: zod
        .boolean()
        .default(hogFlowsInvocationsCreateBodyUseDraftDefault)
        .describe(
            "Test the workflow's staged draft instead of its live config. Set this only when workflows-get returns a non-null 'draft'; it can't be combined with an explicit configuration override."
        ),
})

export const HogFlowsLogsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogFlowsLogsRetrieveQueryLimitDefault = 50
export const hogFlowsLogsRetrieveQueryLimitMax = 500

export const HogFlowsLogsRetrieveQueryParams = () => zod.object({
    after: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe(
            'Only return entries after this ISO 8601 timestamp. Defaults to 7 days ago; pass an explicit value to read further back.'
        ),
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

export const HogFlowsMetricsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogFlowsMetricsRetrieveQueryAfterDefault = `-7d`

export const hogFlowsMetricsRetrieveQueryBreakdownByDefault = `kind`
export const hogFlowsMetricsRetrieveQueryIntervalDefault = `day`

export const HogFlowsMetricsRetrieveQueryParams = () => zod.object({
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
            "Group the series by metric 'name' or 'kind'. Defaults to 'kind'.\n\n\* `name` - name\n\* `kind` - kind"
        ),
    instance_id: zod.string().min(1).optional().describe('Filter metrics to a specific execution instance.'),
    interval: zod
        .enum(['hour', 'day', 'week'])
        .default(hogFlowsMetricsRetrieveQueryIntervalDefault)
        .describe(
            "Time bucket size for the series. One of: hour, day, week. Defaults to 'day'.\n\n\* `hour` - hour\n\* `day` - day\n\* `week` - week"
        ),
    kind: zod.string().min(1).optional().describe("Comma-separated metric kinds to filter by, e.g. 'success,failure'."),
    name: zod.string().min(1).optional().describe('Comma-separated metric names to filter by.'),
})

/**
 * One published version's series. Every hog flow metric is mirrored under
 * `hog_flow_version` with the version appended to the id, which is what makes "before and
 * after this change" answerable at all. The unversioned read keys batch and broadcast runs on
 * the run instead, so it is not the sum of the versions.
 */
export const HogFlowsMetricsVersionRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogFlowsMetricsVersionRetrieveQueryAfterDefault = `-7d`

export const hogFlowsMetricsVersionRetrieveQueryBreakdownByDefault = `kind`
export const hogFlowsMetricsVersionRetrieveQueryIntervalDefault = `day`

export const HogFlowsMetricsVersionRetrieveQueryParams = () => zod.object({
    after: zod
        .string()
        .min(1)
        .default(hogFlowsMetricsVersionRetrieveQueryAfterDefault)
        .describe(
            "Start of the time range. Accepts relative formats like '-7d', '-24h' or ISO 8601 timestamps. Defaults to '-7d'."
        ),
    before: zod.string().min(1).optional().describe("End of the time range. Same format as 'after'. Defaults to now."),
    breakdown_by: zod
        .enum(['name', 'kind'])
        .default(hogFlowsMetricsVersionRetrieveQueryBreakdownByDefault)
        .describe(
            "Group the series by metric 'name' or 'kind'. Defaults to 'kind'.\n\n\* `name` - name\n\* `kind` - kind"
        ),
    instance_id: zod.string().min(1).optional().describe('Filter metrics to a specific execution instance.'),
    interval: zod
        .enum(['hour', 'day', 'week'])
        .default(hogFlowsMetricsVersionRetrieveQueryIntervalDefault)
        .describe(
            "Time bucket size for the series. One of: hour, day, week. Defaults to 'day'.\n\n\* `hour` - hour\n\* `day` - day\n\* `week` - week"
        ),
    kind: zod.string().min(1).optional().describe("Comma-separated metric kinds to filter by, e.g. 'success,failure'."),
    name: zod.string().min(1).optional().describe('Comma-separated metric names to filter by.'),
    version: zod
        .number()
        .describe(
            "Read one workflow version's series: every run of that version, keyed on the workflow. The unversioned read keys batch and broadcast runs on the run instead, so it is not the sum of the versions; compare versions with each other, not with it."
        ),
})

/**
 * Agent-authored changes to this workflow, awaiting a human's decision.
 *
 * Creating one stages nothing: a proposal only reaches the workflow's draft once a human
 * approves it, and only reaches the live config once someone publishes that draft.
 */
export const HogFlowsProposalsListParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const HogFlowsProposalsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    status: zod
        .enum(['applied', 'approved', 'rejected', 'suggested'])
        .optional()
        .describe('Only return proposals in this status (suggested, approved, rejected, applied).'),
})

/**
 * Agent-authored changes to this workflow, awaiting a human's decision.
 *
 * Creating one stages nothing: a proposal only reaches the workflow's draft once a human
 * approves it, and only reaches the live config once someone publishes that draft.
 */
export const HogFlowsProposalsCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogFlowsProposalsCreateBodyTitleMax = 200

export const hogFlowsProposalsCreateBodyStepIdMax = 200

export const hogFlowsProposalsCreateBodySourceIdMax = 200

export const HogFlowsProposalsCreateBody = () => zod.object({
    title: zod.string().max(hogFlowsProposalsCreateBodyTitleMax).describe('Short summary of the proposed change.'),
    rationale: zod.string().describe('Why this change is worth making, in prose a human reads.'),
    content: zod
        .record(zod.string(), zod.unknown())
        .describe(
            'Only the workflow content fields this proposal changes. Approving merges them over the live content to build the staged draft, so unrelated parts of the workflow stay as they are. In `actions`, send each step you change with its `id` and only the fields you change; they merge into the live step, and a null field deletes it.'
        ),
    evidence: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('The metric numbers behind the proposal, so a human can judge it without re-deriving them.'),
    base_version: zod
        .number()
        .min(1)
        .describe(
            'Workflow version this was authored against, as read from the workflow. It is the snapshot approve compares against to tell whether someone edited the same steps or fields since, and a defaulted version would read as current however long the producer took.'
        ),
    step_id: zod
        .string()
        .max(hogFlowsProposalsCreateBodyStepIdMax)
        .nullish()
        .describe(
            "The step this is about. Send it for a change to one step: both the evidence and the outcome then read that step's metrics, so a change to one email in a sequence is not measured against the rest. Leave it out only for a change that spans the workflow, such as its exit condition or a step being taken out, which is measured on the workflow's own numbers."
        ),
    source_id: zod
        .string()
        .max(hogFlowsProposalsCreateBodySourceIdMax)
        .nullish()
        .describe(
            'Stable id of the producing agent run or finding. Posting the same one twice returns the existing proposal instead of creating a duplicate.'
        ),
})

export const HogFlowsPublishCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogFlowsPublishCreateBodyConfirmDefault = false

export const HogFlowsPublishCreateBody = () => zod.object({
    confirm: zod
        .boolean()
        .default(hogFlowsPublishCreateBodyConfirmDefault)
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

export const HogFlowsRevisionsListParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const HogFlowsRevisionsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const HogFlowsRevisionsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    version: zod.number().describe('Workflow version to fetch.'),
})

export const HogFlowsRevisionsRestoreCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    version: zod.number().describe('Workflow version to restore.'),
})

export const hogFlowsRevisionsRestoreCreateBodyOverwriteDefault = false

export const HogFlowsRevisionsRestoreCreateBody = () => zod.object({
    overwrite: zod
        .boolean()
        .default(hogFlowsRevisionsRestoreCreateBodyOverwriteDefault)
        .describe(
            "Replace the open staged draft with this revision's content. Without it, restoring while a draft is open returns 409."
        ),
    expected_draft_updated_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe(
            'The draft_updated_at of the staged draft this overwrite was confirmed against. If a draft exists with a different stamp (it was staged or edited since the confirmation was shown), the restore returns 409 instead of overwriting it. Omit to overwrite unconditionally.'
        ),
})

export const HogFlowsSchedulesPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this hog flow.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    schedule_id: zod.string(),
})

export const hogFlowsSchedulesPartialUpdateBodyTimezoneMax = 64

export const HogFlowsSchedulesPartialUpdateBody = () => zod.object({
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

export const HogFlowsMetricsGlobalRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const hogFlowsMetricsGlobalRetrieveQueryAfterDefault = `-7d`

export const HogFlowsMetricsGlobalRetrieveQueryParams = () => zod.object({
    after: zod
        .string()
        .min(1)
        .default(hogFlowsMetricsGlobalRetrieveQueryAfterDefault)
        .describe(
            "Start of the window, matched on metric time. Relative ('-7d', '-24h') or ISO 8601. Defaults to -7d."
        ),
    before: zod.string().min(1).optional().describe("End of the window. Same format as 'after'. Defaults to now."),
})

/**
 * Bounce/complaint rates for this project's workflow email over the last 30 days, computed on
 * the fly from app metrics (a project-wide aggregate plus per-workflow rows, worst first,
 * capped), together with the authoritative AWS SES tenant verdict — sending status and open
 * reputation findings. Our rates are the per-workflow diagnosis; AWS judges and enforces.
 */
export const HogFlowsReputationRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const HogFlowsReputationRetrieveQueryParams = () => zod.object({
    search: zod
        .string()
        .optional()
        .describe(
            'Case-insensitive workflow name filter. Applied before the worst-50 cap, so it finds workflows the unfiltered response cuts off.'
        ),
})

/**
 * Workflow ideas written by AI from the project's own events. Both calls are free for the customer.
 */
export const WorkflowDataSuggestionsBuildParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const workflowDataSuggestionsBuildBodyRetryDefault = false

export const WorkflowDataSuggestionsBuildBody = () => zod.object({
    suggestion_id: zod.string().describe('The id of a suggestion from the list endpoint.'),
    retry: zod
        .boolean()
        .default(workflowDataSuggestionsBuildBodyRetryDefault)
        .describe(
            "Start a new build when the last one failed. Leave it false when asking for a running build's status."
        ),
})

/**
 * Build and save draft email workflows for events the team picked, such as the events it was about to send
 * to an email tool. Free for the customer. Needs the feature flag and AI data processing approved for the organization.
 */
export const WorkflowDataSuggestionsBuildForEventsParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const workflowDataSuggestionsBuildForEventsBodyEventsItemMax = 400

export const workflowDataSuggestionsBuildForEventsBodyEventsMax = 5

export const workflowDataSuggestionsBuildForEventsBodyRetryDefault = false

export const WorkflowDataSuggestionsBuildForEventsBody = () => zod.object({
    events: zod
        .array(
            zod
                .string()
                .max(workflowDataSuggestionsBuildForEventsBodyEventsItemMax)
                .describe('An event name, exactly as the project sends it.')
        )
        .min(1)
        .max(workflowDataSuggestionsBuildForEventsBodyEventsMax)
        .describe(
            'The events to build email workflows for, at most 5. Each event gets at most one draft workflow that starts when the event happens.'
        ),
    retry: zod
        .boolean()
        .default(workflowDataSuggestionsBuildForEventsBodyRetryDefault)
        .describe(
            "Start a new build when the last one for these events failed. Leave it false when asking for a running build's status."
        ),
})

/**
 * Workflow ideas written by AI from the project's own events. Both calls are free for the customer.
 */
export const WorkflowDataSuggestionsCurrentParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Workflow ideas written by AI from the project's own events. Both calls are free for the customer.
 */
export const WorkflowDataSuggestionsGenerateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const workflowDataSuggestionsGenerateBodyRefreshDefault = false

export const WorkflowDataSuggestionsGenerateBody = () => zod.object({
    refresh: zod
        .boolean()
        .default(workflowDataSuggestionsGenerateBodyRefreshDefault)
        .describe('Make new suggestions even when the cached ones are still valid.'),
})

/**
 * Turns Customer.io automations into draft workflows. Pass each automation as Customer.io's Journeys UI API returns it. Pass the templates its messages use, or leave them out when the project stored a Customer.io App API key, and PostHog reads them. Each result lists what the import changed or left out. Importing an automation again updates its draft, unless that workflow is no longer a draft. Set dry_run to preview without saving.
 * @summary Import Customer.io automations as draft workflows
 */
export const WorkflowImportsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const workflowImportsCreateBodySenderIdentitiesItemNameDefault = ``
export const workflowImportsCreateBodyDryRunDefault = false

export const WorkflowImportsCreateBody = () => zod.object({
    source: zod
        .enum(['customerio'])
        .describe('\* `customerio` - Customer.io')
        .describe('The tool the automations come from.\n\n\* `customerio` - Customer.io'),
    campaigns: zod
        .array(
            zod.object({
                campaign: zod
                    .record(zod.string(), zod.unknown())
                    .describe(
                        "The `campaign` object from Customer.io's `GET \/v1\/environments\/{environment_id}\/campaigns\/{campaign_id}` (Journeys UI API, what the Customer.io CLI and MCP read). Must include `id`, `type`, `edges` and the trigger fields."
                    ),
                actions: zod
                    .array(zod.record(zod.string(), zod.unknown()))
                    .describe('The top-level `actions` array from the same response, every step of the automation.'),
                templates: zod
                    .unknown()
                    .optional()
                    .describe(
                        'The message templates the actions point at, from `GET \/v1\/environments\/{environment_id}\/templates\/{template_id}`: a list of template objects, or an object keyed by template id. Leave them out when the project stored a Customer.io App API key: PostHog then reads the content from Customer.io itself. Without either, messages import with empty content.'
                    ),
            })
        )
        .describe('The automations to import, at most 50. People are never read from these objects.'),
    snippets: zod
        .record(zod.string(), zod.string())
        .optional()
        .describe(
            'Customer.io snippet name to its content, inlined where a message uses `{{ snippets.name }}`. When PostHog reads the message content with a stored Customer.io App API key, it reads the snippets too.'
        ),
    segment_cohorts: zod
        .record(zod.string(), zod.number())
        .optional()
        .describe(
            'Customer.io segment id to the PostHog cohort that replaces it. Segment triggers and segment conditions with no cohort here are left for the team to set.'
        ),
    layouts: zod
        .record(zod.string(), zod.string())
        .optional()
        .describe(
            "Customer.io layout id to the layout's `body`, from `GET \/v1\/environments\/{environment_id}\/layouts\/{layout_id}`. An email whose template names a `layout_id` is wrapped in that layout at `{{ content }}`."
        ),
    sender_identities: zod
        .array(
            zod.object({
                id: zod.string().describe("The sender identity's id, which templates name in `from_identity_id`."),
                email: zod.email().describe('The address the sender sends from.'),
                name: zod
                    .string()
                    .default(workflowImportsCreateBodySenderIdentitiesItemNameDefault)
                    .describe("The sender's display name."),
            })
        )
        .optional()
        .describe(
            'Customer.io sender identities, from `GET \/v1\/environments\/{environment_id}\/identities?type=email`. Each email gets the PostHog sender with the same address.'
        ),
    segments: zod
        .array(
            zod.object({
                id: zod.string().describe("The segment's id."),
                name: zod.string().describe("The segment's name."),
                type: zod.string().describe("The segment's type: `dynamic`, or `static` for a hand-made list."),
            })
        )
        .optional()
        .describe(
            'Customer.io segment ids, names and types, without members, so the notes can name each segment and flag static ones.'
        ),
    dry_run: zod
        .boolean()
        .default(workflowImportsCreateBodyDryRunDefault)
        .describe('When true, translate and check the automations but save nothing, to preview the import.'),
})

/**
 * @summary Read what importing a workflow changed or left out
 */
export const WorkflowImportsForWorkflowRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const WorkflowImportsForWorkflowRetrieveQueryParams = () => zod.object({
    hog_flow_id: zod.string().describe('The workflow to read the import of.'),
})

/**
 * The project-wide rules every workflow and broadcast follows when it sends a message.
 */
export const WorkflowSendingRulesRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * The project-wide rules every workflow and broadcast follows when it sends a message.
 */
export const WorkflowSendingRulesPartialUpdateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const workflowSendingRulesPartialUpdateBodyMarketingFrequencyCapMaxMessagesMax = 1000

export const workflowSendingRulesPartialUpdateBodyMarketingFrequencyCapWindowDaysMax = 30

export const WorkflowSendingRulesPartialUpdateBody = () => zod.object({
    expected_project_id: zod
        .number()
        .optional()
        .describe(
            'Optional. The project_id from the rules being changed. The update is rejected when it does not match the current project, so a change never lands in a project the user did not look at.'
        ),
    marketing_frequency_cap_max_messages: zod
        .number()
        .min(1)
        .max(workflowSendingRulesPartialUpdateBodyMarketingFrequencyCapMaxMessagesMax)
        .nullish()
        .describe(
            'The most marketing messages one person gets in the window, across all workflows and broadcasts. Set it together with marketing_frequency_cap_window_days, or set both to null to turn the cap off. Transactional messages are never capped. The recommended cap is 1 message every 2 days.'
        ),
    marketing_frequency_cap_window_days: zod
        .number()
        .min(1)
        .max(workflowSendingRulesPartialUpdateBodyMarketingFrequencyCapWindowDaysMax)
        .nullish()
        .describe(
            'The length of the rolling frequency cap window, in days. Set it together with marketing_frequency_cap_max_messages, or set both to null to turn the cap off.'
        ),
    email_tracking_consent_mode: zod
        .enum(['off', 'opt_out', 'opt_in'])
        .describe('\* `off` - Off\n\* `opt_out` - Opt Out\n\* `opt_in` - Opt In')
        .optional()
        .describe(
            "Whether tracking opens and clicks on marketing email needs the recipient's consent. 'off' follows each email step's own setting, 'opt_out' tracks unless the recipient objected, and 'opt_in' tracks only recipients who consented. Transactional email is never affected.\n\n\* `off` - Off\n\* `opt_out` - Opt Out\n\* `opt_in` - Opt In"
        ),
    capture_workflows_engagement_events: zod
        .boolean()
        .optional()
        .describe(
            "Capture email sends, opens, clicks and bounces as PostHog events, so they can be used in insights and funnels. These events count toward the project's event usage."
        ),
})

/**
 * Whether a project is set up to send messages from workflows.
 */
export const WorkflowSetupStatusParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
