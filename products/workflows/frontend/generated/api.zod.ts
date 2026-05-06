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
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesCreateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesCreateBodyTriggerMaskingOneTtlMax)
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
                    .nullish()
                    .describe('Compiled bytecode for the hash template. Auto-generated server-side.'),
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
        variables: zod
            .array(
                zod
                    .record(zod.string(), zod.string())
                    .describe(
                        "Variable definition with keys: 'key' (unique identifier), 'type' (string/number/boolean), 'default' (initial value)."
                    )
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
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesUpdateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesUpdateBodyTriggerMaskingOneTtlMax)
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
                    .nullish()
                    .describe('Compiled bytecode for the hash template. Auto-generated server-side.'),
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
        variables: zod
            .array(
                zod
                    .record(zod.string(), zod.string())
                    .describe(
                        "Variable definition with keys: 'key' (unique identifier), 'type' (string/number/boolean), 'default' (initial value)."
                    )
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
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesPartialUpdateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesPartialUpdateBodyTriggerMaskingOneTtlMax)
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
                    .nullish()
                    .describe('Compiled bytecode for the hash template. Auto-generated server-side.'),
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
        variables: zod
            .array(
                zod
                    .record(zod.string(), zod.string())
                    .describe(
                        "Variable definition with keys: 'key' (unique identifier), 'type' (string/number/boolean), 'default' (initial value)."
                    )
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
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsCreateBodyTriggerMaskingOneTtlMax)
                .nullish()
                .describe('Time-to-live in seconds for the masking hash. Min 60s, max 3 years.'),
            threshold: zod
                .number()
                .nullish()
                .describe('Minimum number of matching events before the workflow triggers (k-anonymity threshold).'),
            hash: zod
                .string()
                .describe("HogQL template expression used as the masking key (e.g. '{person.properties.email}')."),
            bytecode: zod
                .unknown()
                .nullish()
                .describe('Compiled bytecode for the hash template. Auto-generated server-side.'),
        })
        .nullish()
        .describe(
            'Optional masking/deduplication configuration. Prevents the same entity from entering the workflow multiple times within a TTL window.'
        ),
    conversion: zod
        .unknown()
        .nullish()
        .describe('Conversion goal definition with filters and bytecode. Used with exit_on_conversion exit condition.'),
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

export const hogFlowsUpdateBodyNameMax = 400

export const hogFlowsUpdateBodyDescriptionDefault = ``
export const hogFlowsUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsUpdateBodyActionsItemNameMax = 400

export const hogFlowsUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowsUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsUpdateBodyActionsItemTypeMax = 100

export const HogFlowsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsUpdateBodyNameMax).nullish().describe('Human-readable name for the workflow.'),
    description: zod
        .string()
        .default(hogFlowsUpdateBodyDescriptionDefault)
        .describe("Optional description of the workflow's purpose."),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived')
        .optional()
        .describe(
            'Workflow state: draft (editing), active (live and processing events), or archived (soft-deleted).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
        ),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsUpdateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsUpdateBodyTriggerMaskingOneTtlMax)
                .nullish()
                .describe('Time-to-live in seconds for the masking hash. Min 60s, max 3 years.'),
            threshold: zod
                .number()
                .nullish()
                .describe('Minimum number of matching events before the workflow triggers (k-anonymity threshold).'),
            hash: zod
                .string()
                .describe("HogQL template expression used as the masking key (e.g. '{person.properties.email}')."),
            bytecode: zod
                .unknown()
                .nullish()
                .describe('Compiled bytecode for the hash template. Auto-generated server-side.'),
        })
        .nullish()
        .describe(
            'Optional masking/deduplication configuration. Prevents the same entity from entering the workflow multiple times within a TTL window.'
        ),
    conversion: zod
        .unknown()
        .nullish()
        .describe('Conversion goal definition with filters and bytecode. Used with exit_on_conversion exit condition.'),
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
                    .max(hogFlowsUpdateBodyActionsItemNameMax)
                    .describe('Human-readable name for the action node.'),
                description: zod
                    .string()
                    .default(hogFlowsUpdateBodyActionsItemDescriptionDefault)
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
                    .nullish()
                    .describe('Property filters that gate execution of this action.'),
                type: zod
                    .string()
                    .max(hogFlowsUpdateBodyActionsItemTypeMax)
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

export const hogFlowsPartialUpdateBodyNameMax = 400

export const hogFlowsPartialUpdateBodyDescriptionDefault = ``
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
    description: zod
        .string()
        .default(hogFlowsPartialUpdateBodyDescriptionDefault)
        .describe("Optional description of the workflow's purpose."),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived')
        .optional()
        .describe(
            'Workflow state: draft (editing), active (live and processing events), or archived (soft-deleted).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
        ),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMax)
                .nullish()
                .describe('Time-to-live in seconds for the masking hash. Min 60s, max 3 years.'),
            threshold: zod
                .number()
                .nullish()
                .describe('Minimum number of matching events before the workflow triggers (k-anonymity threshold).'),
            hash: zod
                .string()
                .describe("HogQL template expression used as the masking key (e.g. '{person.properties.email}')."),
            bytecode: zod
                .unknown()
                .nullish()
                .describe('Compiled bytecode for the hash template. Auto-generated server-side.'),
        })
        .nullish()
        .describe(
            'Optional masking/deduplication configuration. Prevents the same entity from entering the workflow multiple times within a TTL window.'
        ),
    conversion: zod
        .unknown()
        .nullish()
        .describe('Conversion goal definition with filters and bytecode. Used with exit_on_conversion exit condition.'),
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

export const hogFlowsBatchJobsCreateBodyNameMax = 400

export const hogFlowsBatchJobsCreateBodyDescriptionDefault = ``
export const hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsBatchJobsCreateBodyActionsItemNameMax = 400

export const hogFlowsBatchJobsCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsBatchJobsCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsBatchJobsCreateBodyActionsItemTypeMax = 100

export const HogFlowsBatchJobsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(hogFlowsBatchJobsCreateBodyNameMax)
        .nullish()
        .describe('Human-readable name for the workflow.'),
    description: zod
        .string()
        .default(hogFlowsBatchJobsCreateBodyDescriptionDefault)
        .describe("Optional description of the workflow's purpose."),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived')
        .optional()
        .describe(
            'Workflow state: draft (editing), active (live and processing events), or archived (soft-deleted).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
        ),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMax)
                .nullish()
                .describe('Time-to-live in seconds for the masking hash. Min 60s, max 3 years.'),
            threshold: zod
                .number()
                .nullish()
                .describe('Minimum number of matching events before the workflow triggers (k-anonymity threshold).'),
            hash: zod
                .string()
                .describe("HogQL template expression used as the masking key (e.g. '{person.properties.email}')."),
            bytecode: zod
                .unknown()
                .nullish()
                .describe('Compiled bytecode for the hash template. Auto-generated server-side.'),
        })
        .nullish()
        .describe(
            'Optional masking/deduplication configuration. Prevents the same entity from entering the workflow multiple times within a TTL window.'
        ),
    conversion: zod
        .unknown()
        .nullish()
        .describe('Conversion goal definition with filters and bytecode. Used with exit_on_conversion exit condition.'),
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
                    .max(hogFlowsBatchJobsCreateBodyActionsItemNameMax)
                    .describe('Human-readable name for the action node.'),
                description: zod
                    .string()
                    .default(hogFlowsBatchJobsCreateBodyActionsItemDescriptionDefault)
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
                    .nullish()
                    .describe('Property filters that gate execution of this action.'),
                type: zod
                    .string()
                    .max(hogFlowsBatchJobsCreateBodyActionsItemTypeMax)
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

export const hogFlowsInvocationsCreateBodyMockAsyncFunctionsDefault = true

export const HogFlowsInvocationsCreateBody = /* @__PURE__ */ zod.object({
    configuration: zod
        .object({
            id: zod.uuid(),
            name: zod
                .string()
                .max(hogFlowsInvocationsCreateBodyConfigurationOneNameMax)
                .nullish()
                .describe('Human-readable name for the workflow.'),
            description: zod
                .string()
                .default(hogFlowsInvocationsCreateBodyConfigurationOneDescriptionDefault)
                .describe("Optional description of the workflow's purpose."),
            version: zod.number(),
            status: zod
                .enum(['draft', 'active', 'archived'])
                .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived')
                .optional()
                .describe(
                    'Workflow state: draft (editing), active (live and processing events), or archived (soft-deleted).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
                ),
            created_at: zod.iso.datetime({}),
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
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            updated_at: zod.iso.datetime({}),
            trigger: zod.unknown(),
            trigger_masking: zod
                .object({
                    ttl: zod
                        .number()
                        .min(hogFlowsInvocationsCreateBodyConfigurationOneTriggerMaskingOneTtlMin)
                        .max(hogFlowsInvocationsCreateBodyConfigurationOneTriggerMaskingOneTtlMax)
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
                        .describe(
                            "HogQL template expression used as the masking key (e.g. '{person.properties.email}')."
                        ),
                    bytecode: zod
                        .unknown()
                        .nullish()
                        .describe('Compiled bytecode for the hash template. Auto-generated server-side.'),
                })
                .nullish()
                .describe(
                    'Optional masking/deduplication configuration. Prevents the same entity from entering the workflow multiple times within a TTL window.'
                ),
            conversion: zod
                .unknown()
                .nullish()
                .describe(
                    'Conversion goal definition with filters and bytecode. Used with exit_on_conversion exit condition.'
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
                            .max(hogFlowsInvocationsCreateBodyConfigurationOneActionsItemNameMax)
                            .describe('Human-readable name for the action node.'),
                        description: zod
                            .string()
                            .default(hogFlowsInvocationsCreateBodyConfigurationOneActionsItemDescriptionDefault)
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
                            .describe(
                                'Unix epoch milliseconds when the action was added. Auto-managed by the frontend.'
                            ),
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
                                    .default(
                                        hogFlowsInvocationsCreateBodyConfigurationOneActionsItemFiltersOneSourceDefault
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
                            .nullish()
                            .describe('Property filters that gate execution of this action.'),
                        type: zod
                            .string()
                            .max(hogFlowsInvocationsCreateBodyConfigurationOneActionsItemTypeMax)
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
                            .describe(
                                "Variable definition to store this action's output for use by downstream actions."
                            ),
                    })
                )
                .describe(
                    "Ordered list of action nodes in the workflow. Must include exactly one action with type='trigger'."
                ),
            abort_action: zod.string().nullable(),
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
            billable_action_types: zod.unknown().nullable(),
        })
        .optional()
        .describe(
            'Optional workflow configuration override for the test run. If omitted, uses the saved workflow definition.'
        ),
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

/**
 * Replay all blocked runs in a single bulk call to Node.
 */
export const hogFlowsReplayAllBlockedRunsCreateBodyNameMax = 400

export const hogFlowsReplayAllBlockedRunsCreateBodyDescriptionDefault = ``
export const hogFlowsReplayAllBlockedRunsCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsReplayAllBlockedRunsCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsReplayAllBlockedRunsCreateBodyActionsItemNameMax = 400

export const hogFlowsReplayAllBlockedRunsCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsReplayAllBlockedRunsCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsReplayAllBlockedRunsCreateBodyActionsItemTypeMax = 100

export const HogFlowsReplayAllBlockedRunsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(hogFlowsReplayAllBlockedRunsCreateBodyNameMax)
        .nullish()
        .describe('Human-readable name for the workflow.'),
    description: zod
        .string()
        .default(hogFlowsReplayAllBlockedRunsCreateBodyDescriptionDefault)
        .describe("Optional description of the workflow's purpose."),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived')
        .optional()
        .describe(
            'Workflow state: draft (editing), active (live and processing events), or archived (soft-deleted).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
        ),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsReplayAllBlockedRunsCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsReplayAllBlockedRunsCreateBodyTriggerMaskingOneTtlMax)
                .nullish()
                .describe('Time-to-live in seconds for the masking hash. Min 60s, max 3 years.'),
            threshold: zod
                .number()
                .nullish()
                .describe('Minimum number of matching events before the workflow triggers (k-anonymity threshold).'),
            hash: zod
                .string()
                .describe("HogQL template expression used as the masking key (e.g. '{person.properties.email}')."),
            bytecode: zod
                .unknown()
                .nullish()
                .describe('Compiled bytecode for the hash template. Auto-generated server-side.'),
        })
        .nullish()
        .describe(
            'Optional masking/deduplication configuration. Prevents the same entity from entering the workflow multiple times within a TTL window.'
        ),
    conversion: zod
        .unknown()
        .nullish()
        .describe('Conversion goal definition with filters and bytecode. Used with exit_on_conversion exit condition.'),
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
                    .max(hogFlowsReplayAllBlockedRunsCreateBodyActionsItemNameMax)
                    .describe('Human-readable name for the action node.'),
                description: zod
                    .string()
                    .default(hogFlowsReplayAllBlockedRunsCreateBodyActionsItemDescriptionDefault)
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
                            .default(hogFlowsReplayAllBlockedRunsCreateBodyActionsItemFiltersOneSourceDefault),
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
                    .max(hogFlowsReplayAllBlockedRunsCreateBodyActionsItemTypeMax)
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

/**
 * Replay a single blocked run. Django fetches the event, Node creates the invocation and writes the log.
 */
export const hogFlowsReplayBlockedRunCreateBodyNameMax = 400

export const hogFlowsReplayBlockedRunCreateBodyDescriptionDefault = ``
export const hogFlowsReplayBlockedRunCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsReplayBlockedRunCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsReplayBlockedRunCreateBodyActionsItemNameMax = 400

export const hogFlowsReplayBlockedRunCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsReplayBlockedRunCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsReplayBlockedRunCreateBodyActionsItemTypeMax = 100

export const HogFlowsReplayBlockedRunCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(hogFlowsReplayBlockedRunCreateBodyNameMax)
        .nullish()
        .describe('Human-readable name for the workflow.'),
    description: zod
        .string()
        .default(hogFlowsReplayBlockedRunCreateBodyDescriptionDefault)
        .describe("Optional description of the workflow's purpose."),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived')
        .optional()
        .describe(
            'Workflow state: draft (editing), active (live and processing events), or archived (soft-deleted).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
        ),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsReplayBlockedRunCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsReplayBlockedRunCreateBodyTriggerMaskingOneTtlMax)
                .nullish()
                .describe('Time-to-live in seconds for the masking hash. Min 60s, max 3 years.'),
            threshold: zod
                .number()
                .nullish()
                .describe('Minimum number of matching events before the workflow triggers (k-anonymity threshold).'),
            hash: zod
                .string()
                .describe("HogQL template expression used as the masking key (e.g. '{person.properties.email}')."),
            bytecode: zod
                .unknown()
                .nullish()
                .describe('Compiled bytecode for the hash template. Auto-generated server-side.'),
        })
        .nullish()
        .describe(
            'Optional masking/deduplication configuration. Prevents the same entity from entering the workflow multiple times within a TTL window.'
        ),
    conversion: zod
        .unknown()
        .nullish()
        .describe('Conversion goal definition with filters and bytecode. Used with exit_on_conversion exit condition.'),
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
                    .max(hogFlowsReplayBlockedRunCreateBodyActionsItemNameMax)
                    .describe('Human-readable name for the action node.'),
                description: zod
                    .string()
                    .default(hogFlowsReplayBlockedRunCreateBodyActionsItemDescriptionDefault)
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
                            .default(hogFlowsReplayBlockedRunCreateBodyActionsItemFiltersOneSourceDefault),
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
                    .max(hogFlowsReplayBlockedRunCreateBodyActionsItemTypeMax)
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

export const hogFlowsSchedulesCreateBodyNameMax = 400

export const hogFlowsSchedulesCreateBodyDescriptionDefault = ``
export const hogFlowsSchedulesCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsSchedulesCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsSchedulesCreateBodyActionsItemNameMax = 400

export const hogFlowsSchedulesCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsSchedulesCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsSchedulesCreateBodyActionsItemTypeMax = 100

export const HogFlowsSchedulesCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(hogFlowsSchedulesCreateBodyNameMax)
        .nullish()
        .describe('Human-readable name for the workflow.'),
    description: zod
        .string()
        .default(hogFlowsSchedulesCreateBodyDescriptionDefault)
        .describe("Optional description of the workflow's purpose."),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived')
        .optional()
        .describe(
            'Workflow state: draft (editing), active (live and processing events), or archived (soft-deleted).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
        ),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsSchedulesCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsSchedulesCreateBodyTriggerMaskingOneTtlMax)
                .nullish()
                .describe('Time-to-live in seconds for the masking hash. Min 60s, max 3 years.'),
            threshold: zod
                .number()
                .nullish()
                .describe('Minimum number of matching events before the workflow triggers (k-anonymity threshold).'),
            hash: zod
                .string()
                .describe("HogQL template expression used as the masking key (e.g. '{person.properties.email}')."),
            bytecode: zod
                .unknown()
                .nullish()
                .describe('Compiled bytecode for the hash template. Auto-generated server-side.'),
        })
        .nullish()
        .describe(
            'Optional masking/deduplication configuration. Prevents the same entity from entering the workflow multiple times within a TTL window.'
        ),
    conversion: zod
        .unknown()
        .nullish()
        .describe('Conversion goal definition with filters and bytecode. Used with exit_on_conversion exit condition.'),
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
                    .max(hogFlowsSchedulesCreateBodyActionsItemNameMax)
                    .describe('Human-readable name for the action node.'),
                description: zod
                    .string()
                    .default(hogFlowsSchedulesCreateBodyActionsItemDescriptionDefault)
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
                            .default(hogFlowsSchedulesCreateBodyActionsItemFiltersOneSourceDefault),
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
                    .max(hogFlowsSchedulesCreateBodyActionsItemTypeMax)
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

export const hogFlowsSchedulesPartialUpdateBodyNameMax = 400

export const hogFlowsSchedulesPartialUpdateBodyDescriptionDefault = ``
export const hogFlowsSchedulesPartialUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsSchedulesPartialUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsSchedulesPartialUpdateBodyActionsItemNameMax = 400

export const hogFlowsSchedulesPartialUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowsSchedulesPartialUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsSchedulesPartialUpdateBodyActionsItemTypeMax = 100

export const HogFlowsSchedulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(hogFlowsSchedulesPartialUpdateBodyNameMax)
        .nullish()
        .describe('Human-readable name for the workflow.'),
    description: zod
        .string()
        .default(hogFlowsSchedulesPartialUpdateBodyDescriptionDefault)
        .describe("Optional description of the workflow's purpose."),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived')
        .optional()
        .describe(
            'Workflow state: draft (editing), active (live and processing events), or archived (soft-deleted).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
        ),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsSchedulesPartialUpdateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsSchedulesPartialUpdateBodyTriggerMaskingOneTtlMax)
                .nullish()
                .describe('Time-to-live in seconds for the masking hash. Min 60s, max 3 years.'),
            threshold: zod
                .number()
                .nullish()
                .describe('Minimum number of matching events before the workflow triggers (k-anonymity threshold).'),
            hash: zod
                .string()
                .describe("HogQL template expression used as the masking key (e.g. '{person.properties.email}')."),
            bytecode: zod
                .unknown()
                .nullish()
                .describe('Compiled bytecode for the hash template. Auto-generated server-side.'),
        })
        .nullish()
        .describe(
            'Optional masking/deduplication configuration. Prevents the same entity from entering the workflow multiple times within a TTL window.'
        ),
    conversion: zod
        .unknown()
        .nullish()
        .describe('Conversion goal definition with filters and bytecode. Used with exit_on_conversion exit condition.'),
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
                    .max(hogFlowsSchedulesPartialUpdateBodyActionsItemNameMax)
                    .describe('Human-readable name for the action node.'),
                description: zod
                    .string()
                    .default(hogFlowsSchedulesPartialUpdateBodyActionsItemDescriptionDefault)
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
                            .default(hogFlowsSchedulesPartialUpdateBodyActionsItemFiltersOneSourceDefault),
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
                    .max(hogFlowsSchedulesPartialUpdateBodyActionsItemTypeMax)
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

export const hogFlowsBulkDeleteCreateBodyNameMax = 400

export const hogFlowsBulkDeleteCreateBodyDescriptionDefault = ``
export const hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsBulkDeleteCreateBodyActionsItemNameMax = 400

export const hogFlowsBulkDeleteCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsBulkDeleteCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsBulkDeleteCreateBodyActionsItemTypeMax = 100

export const HogFlowsBulkDeleteCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(hogFlowsBulkDeleteCreateBodyNameMax)
        .nullish()
        .describe('Human-readable name for the workflow.'),
    description: zod
        .string()
        .default(hogFlowsBulkDeleteCreateBodyDescriptionDefault)
        .describe("Optional description of the workflow's purpose."),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived')
        .optional()
        .describe(
            'Workflow state: draft (editing), active (live and processing events), or archived (soft-deleted).\n\n* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'
        ),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMax)
                .nullish()
                .describe('Time-to-live in seconds for the masking hash. Min 60s, max 3 years.'),
            threshold: zod
                .number()
                .nullish()
                .describe('Minimum number of matching events before the workflow triggers (k-anonymity threshold).'),
            hash: zod
                .string()
                .describe("HogQL template expression used as the masking key (e.g. '{person.properties.email}')."),
            bytecode: zod
                .unknown()
                .nullish()
                .describe('Compiled bytecode for the hash template. Auto-generated server-side.'),
        })
        .nullish()
        .describe(
            'Optional masking/deduplication configuration. Prevents the same entity from entering the workflow multiple times within a TTL window.'
        ),
    conversion: zod
        .unknown()
        .nullish()
        .describe('Conversion goal definition with filters and bytecode. Used with exit_on_conversion exit condition.'),
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
                    .max(hogFlowsBulkDeleteCreateBodyActionsItemNameMax)
                    .describe('Human-readable name for the action node.'),
                description: zod
                    .string()
                    .default(hogFlowsBulkDeleteCreateBodyActionsItemDescriptionDefault)
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
                    .nullish()
                    .describe('Property filters that gate execution of this action.'),
                type: zod
                    .string()
                    .max(hogFlowsBulkDeleteCreateBodyActionsItemTypeMax)
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

export const HogFlowsUserBlastRadiusCreateBody = /* @__PURE__ */ zod.object({
    filters: zod.record(zod.string(), zod.unknown()).describe('Property filters to apply'),
    group_type_index: zod.number().nullish().describe('Group type index for group-based targeting'),
})
