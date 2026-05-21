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
                        .nullish(),
                    threshold: zod.number().nullish(),
                    hash: zod.string(),
                    bytecode: zod.unknown().optional(),
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
        variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
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
                        .nullish(),
                    threshold: zod.number().nullish(),
                    hash: zod.string(),
                    bytecode: zod.unknown().optional(),
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
        variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
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
                        .nullish(),
                    threshold: zod.number().nullish(),
                    hash: zod.string(),
                    bytecode: zod.unknown().optional(),
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
        variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    })
    .describe(
        'Serializer for creating hog flow templates.\nValidates and sanitizes the workflow before creating it as a template.'
    )

export const hogFlowsCreateBodyNameMax = 400

export const hogFlowsCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsCreateBodyActionsItemNameMax = 400

export const hogFlowsCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsCreateBodyActionsItemTypeMax = 100

export const HogFlowsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsCreateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsCreateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsCreateBodyTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().optional(),
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
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsCreateBodyActionsItemDescriptionDefault),
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
                .optional(),
            type: zod.string().max(hogFlowsCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().optional(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const hogFlowsUpdateBodyNameMax = 400

export const hogFlowsUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsUpdateBodyActionsItemNameMax = 400

export const hogFlowsUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowsUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsUpdateBodyActionsItemTypeMax = 100

export const HogFlowsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsUpdateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsUpdateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsUpdateBodyTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().optional(),
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
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsUpdateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsUpdateBodyActionsItemDescriptionDefault),
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
                .optional(),
            type: zod.string().max(hogFlowsUpdateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().optional(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const hogFlowsPartialUpdateBodyNameMax = 400

export const hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsPartialUpdateBodyActionsItemNameMax = 400

export const hogFlowsPartialUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowsPartialUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsPartialUpdateBodyActionsItemTypeMax = 100

export const HogFlowsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsPartialUpdateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().optional(),
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
            zod.object({
                id: zod.string(),
                name: zod.string().max(hogFlowsPartialUpdateBodyActionsItemNameMax),
                description: zod.string().default(hogFlowsPartialUpdateBodyActionsItemDescriptionDefault),
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
                    .optional(),
                type: zod.string().max(hogFlowsPartialUpdateBodyActionsItemTypeMax),
                config: zod.unknown(),
                output_variable: zod.unknown().optional(),
            })
        )
        .optional(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const hogFlowsBatchJobsCreateBodyNameMax = 400

export const hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsBatchJobsCreateBodyActionsItemNameMax = 400

export const hogFlowsBatchJobsCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsBatchJobsCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsBatchJobsCreateBodyActionsItemTypeMax = 100

export const HogFlowsBatchJobsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsBatchJobsCreateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().optional(),
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
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsBatchJobsCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsBatchJobsCreateBodyActionsItemDescriptionDefault),
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
                            .default(hogFlowsBatchJobsCreateBodyActionsItemFiltersOneSourceDefault),
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
            type: zod.string().max(hogFlowsBatchJobsCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().optional(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const hogFlowsInvocationsCreateBodyNameMax = 400

export const hogFlowsInvocationsCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsInvocationsCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsInvocationsCreateBodyActionsItemNameMax = 400

export const hogFlowsInvocationsCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsInvocationsCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsInvocationsCreateBodyActionsItemTypeMax = 100

export const HogFlowsInvocationsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsInvocationsCreateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsInvocationsCreateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsInvocationsCreateBodyTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().optional(),
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
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsInvocationsCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsInvocationsCreateBodyActionsItemDescriptionDefault),
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
                            .default(hogFlowsInvocationsCreateBodyActionsItemFiltersOneSourceDefault),
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
            type: zod.string().max(hogFlowsInvocationsCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().optional(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

/**
 * Rerun past invocations of this hog flow from their stored payloads.

Same shape and semantics as the hog function rerun endpoint —
proxies through to the CDP worker, which reads matching rows from
ClickHouse, rehydrates from `invocation_globals`, and re-enqueues
onto cyclotron with `is_retry=1`.
 */
export const hogFlowsRerunCreateBodyFilterOneMaxAttemptsMax = 255

export const hogFlowsRerunCreateBodyFilterOneMaxCountMax = 10000

export const hogFlowsRerunCreateBodyFilterOneInvocationIdsMax = 10000

export const HogFlowsRerunCreateBody = /* @__PURE__ */ zod
    .object({
        filter: zod
            .object({
                window_start: zod.iso
                    .datetime({ offset: true })
                    .describe('Inclusive lower bound on `scheduled_at` (UTC).'),
                window_end: zod.iso
                    .datetime({ offset: true })
                    .describe('Exclusive upper bound on `scheduled_at` (UTC).'),
                status: zod
                    .array(
                        zod
                            .enum(['running', 'succeeded', 'failed'])
                            .describe('\* `running` - running\n\* `succeeded` - succeeded\n\* `failed` - failed')
                    )
                    .optional()
                    .describe("Restrict to invocations whose latest status is one of these. Defaults to ['failed']."),
                error_kind: zod
                    .array(zod.string())
                    .optional()
                    .describe(
                        "Restrict to invocations whose error_kind matches one of these (e.g. 'http_5xx', 'timeout')."
                    ),
                max_attempts: zod
                    .number()
                    .min(1)
                    .max(hogFlowsRerunCreateBodyFilterOneMaxAttemptsMax)
                    .optional()
                    .describe('Skip invocations that have already been attempted this many times or more.'),
                max_count: zod
                    .number()
                    .min(1)
                    .max(hogFlowsRerunCreateBodyFilterOneMaxCountMax)
                    .optional()
                    .describe('Maximum number of invocations to rerun in this request. Server-side cap is 10000.'),
                invocation_ids: zod
                    .array(zod.string())
                    .max(hogFlowsRerunCreateBodyFilterOneInvocationIdsMax)
                    .optional()
                    .describe(
                        'Optional restriction to specific invocation IDs within the window. Capped at 10000 per request. Always combined with `window_start`\/`window_end` so the ClickHouse query can be partition-pruned.'
                    ),
            })
            .describe('Filter shape for the rerun endpoint. `window_start`\/`window_end` are required.')
            .describe(
                'Required. `window_start` \/ `window_end` pin the query to a small set of date partitions on the `hog_invocation_results` table. Optional `invocation_ids` restricts to specific invocations within that window.'
            ),
    })
    .describe('Rerun invocations of a hog function or hog flow from their stored payloads.')

export const hogFlowsSchedulesCreateBodyNameMax = 400

export const hogFlowsSchedulesCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsSchedulesCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsSchedulesCreateBodyActionsItemNameMax = 400

export const hogFlowsSchedulesCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsSchedulesCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsSchedulesCreateBodyActionsItemTypeMax = 100

export const HogFlowsSchedulesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsSchedulesCreateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsSchedulesCreateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsSchedulesCreateBodyTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().optional(),
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
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsSchedulesCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsSchedulesCreateBodyActionsItemDescriptionDefault),
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
                            .default(hogFlowsSchedulesCreateBodyActionsItemFiltersOneSourceDefault),
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
            type: zod.string().max(hogFlowsSchedulesCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().optional(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const hogFlowsSchedulesPartialUpdateBodyNameMax = 400

export const hogFlowsSchedulesPartialUpdateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsSchedulesPartialUpdateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsSchedulesPartialUpdateBodyActionsItemNameMax = 400

export const hogFlowsSchedulesPartialUpdateBodyActionsItemDescriptionDefault = ``
export const hogFlowsSchedulesPartialUpdateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsSchedulesPartialUpdateBodyActionsItemTypeMax = 100

export const HogFlowsSchedulesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsSchedulesPartialUpdateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsSchedulesPartialUpdateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsSchedulesPartialUpdateBodyTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().optional(),
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
            zod.object({
                id: zod.string(),
                name: zod.string().max(hogFlowsSchedulesPartialUpdateBodyActionsItemNameMax),
                description: zod.string().default(hogFlowsSchedulesPartialUpdateBodyActionsItemDescriptionDefault),
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
                                .default(hogFlowsSchedulesPartialUpdateBodyActionsItemFiltersOneSourceDefault),
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
                type: zod.string().max(hogFlowsSchedulesPartialUpdateBodyActionsItemTypeMax),
                config: zod.unknown(),
                output_variable: zod.unknown().optional(),
            })
        )
        .optional(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const hogFlowsBulkDeleteCreateBodyNameMax = 400

export const hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsBulkDeleteCreateBodyActionsItemNameMax = 400

export const hogFlowsBulkDeleteCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsBulkDeleteCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsBulkDeleteCreateBodyActionsItemTypeMax = 100

export const HogFlowsBulkDeleteCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsBulkDeleteCreateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('\* `draft` - Draft\n\* `active` - Active\n\* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .union([
            zod.object({
                ttl: zod
                    .number()
                    .min(hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().optional(),
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
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsBulkDeleteCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsBulkDeleteCreateBodyActionsItemDescriptionDefault),
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
                .optional(),
            type: zod.string().max(hogFlowsBulkDeleteCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().optional(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const HogFlowsUserBlastRadiusCreateBody = /* @__PURE__ */ zod.object({
    filters: zod.record(zod.string(), zod.unknown()).describe('Property filters to apply'),
    group_type_index: zod.number().nullish().describe('Group type index for group-based targeting'),
})
