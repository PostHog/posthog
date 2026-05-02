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
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().nullish(),
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
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesUpdateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesUpdateBodyTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().nullish(),
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
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesPartialUpdateBodyTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesPartialUpdateBodyTriggerMaskingOneTtlMax)
                    .nullish(),
                threshold: zod.number().nullish(),
                hash: zod.string(),
                bytecode: zod.unknown().nullish(),
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
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsCreateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
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
            created_at: zod.number().optional(),
            updated_at: zod.number().optional(),
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
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
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
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsUpdateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsUpdateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
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
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsUpdateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsUpdateBodyActionsItemDescriptionDefault),
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
                .nullish(),
            type: zod.string().max(hogFlowsUpdateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
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
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsPartialUpdateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
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
                created_at: zod.number().optional(),
                updated_at: zod.number().optional(),
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
                config: zod.unknown(),
                output_variable: zod.unknown().nullish(),
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
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsBatchJobsCreateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
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
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsBatchJobsCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsBatchJobsCreateBodyActionsItemDescriptionDefault),
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
                .nullish(),
            type: zod.string().max(hogFlowsBatchJobsCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
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
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsInvocationsCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsInvocationsCreateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
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
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsInvocationsCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsInvocationsCreateBodyActionsItemDescriptionDefault),
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
                        .default(hogFlowsInvocationsCreateBodyActionsItemFiltersOneSourceDefault),
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
            type: zod.string().max(hogFlowsInvocationsCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

/**
 * Replay all blocked runs in a single bulk call to Node.
 */
export const hogFlowsReplayAllBlockedRunsCreateBodyNameMax = 400

export const hogFlowsReplayAllBlockedRunsCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsReplayAllBlockedRunsCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsReplayAllBlockedRunsCreateBodyActionsItemNameMax = 400

export const hogFlowsReplayAllBlockedRunsCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsReplayAllBlockedRunsCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsReplayAllBlockedRunsCreateBodyActionsItemTypeMax = 100

export const HogFlowsReplayAllBlockedRunsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsReplayAllBlockedRunsCreateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsReplayAllBlockedRunsCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsReplayAllBlockedRunsCreateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
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
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsReplayAllBlockedRunsCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsReplayAllBlockedRunsCreateBodyActionsItemDescriptionDefault),
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
                .nullish(),
            type: zod.string().max(hogFlowsReplayAllBlockedRunsCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

/**
 * Replay a single blocked run. Django fetches the event, Node creates the invocation and writes the log.
 */
export const hogFlowsReplayBlockedRunCreateBodyNameMax = 400

export const hogFlowsReplayBlockedRunCreateBodyTriggerMaskingOneTtlMin = 60
export const hogFlowsReplayBlockedRunCreateBodyTriggerMaskingOneTtlMax = 94608000

export const hogFlowsReplayBlockedRunCreateBodyActionsItemNameMax = 400

export const hogFlowsReplayBlockedRunCreateBodyActionsItemDescriptionDefault = ``
export const hogFlowsReplayBlockedRunCreateBodyActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsReplayBlockedRunCreateBodyActionsItemTypeMax = 100

export const HogFlowsReplayBlockedRunCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(hogFlowsReplayBlockedRunCreateBodyNameMax).nullish(),
    description: zod.string().optional(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsReplayBlockedRunCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsReplayBlockedRunCreateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
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
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsReplayBlockedRunCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsReplayBlockedRunCreateBodyActionsItemDescriptionDefault),
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
                .nullish(),
            type: zod.string().max(hogFlowsReplayBlockedRunCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

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
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsSchedulesCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsSchedulesCreateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
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
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsSchedulesCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsSchedulesCreateBodyActionsItemDescriptionDefault),
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
                .nullish(),
            type: zod.string().max(hogFlowsSchedulesCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
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
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsSchedulesPartialUpdateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsSchedulesPartialUpdateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
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
            zod.object({
                id: zod.string(),
                name: zod.string().max(hogFlowsSchedulesPartialUpdateBodyActionsItemNameMax),
                description: zod.string().default(hogFlowsSchedulesPartialUpdateBodyActionsItemDescriptionDefault),
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
                    .nullish(),
                type: zod.string().max(hogFlowsSchedulesPartialUpdateBodyActionsItemTypeMax),
                config: zod.unknown(),
                output_variable: zod.unknown().nullish(),
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
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMin)
                .max(hogFlowsBulkDeleteCreateBodyTriggerMaskingOneTtlMax)
                .nullish(),
            threshold: zod.number().nullish(),
            hash: zod.string(),
            bytecode: zod.unknown().nullish(),
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
        zod.object({
            id: zod.string(),
            name: zod.string().max(hogFlowsBulkDeleteCreateBodyActionsItemNameMax),
            description: zod.string().default(hogFlowsBulkDeleteCreateBodyActionsItemDescriptionDefault),
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
                .nullish(),
            type: zod.string().max(hogFlowsBulkDeleteCreateBodyActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
})

export const HogFlowsUserBlastRadiusCreateBody = /* @__PURE__ */ zod.object({
    filters: zod.record(zod.string(), zod.unknown()).describe('Property filters to apply'),
    group_type_index: zod.number().nullish().describe('Group type index for group-based targeting'),
})
