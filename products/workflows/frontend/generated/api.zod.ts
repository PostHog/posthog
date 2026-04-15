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

/**
 * Override list to include global templates from files alongside team templates from DB.
 */
export const hogFlowTemplatesListResponseResultsItemNameMax = 400

export const hogFlowTemplatesListResponseResultsItemImageUrlMax = 8201

export const hogFlowTemplatesListResponseResultsItemTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesListResponseResultsItemTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesListResponseResultsItemActionsItemNameMax = 400

export const hogFlowTemplatesListResponseResultsItemActionsItemDescriptionDefault = ``
export const hogFlowTemplatesListResponseResultsItemActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesListResponseResultsItemActionsItemTypeMax = 100

export const hogFlowTemplatesListResponseResultsItemAbortActionMax = 400

export const HogFlowTemplatesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid(),
                name: zod.string().max(hogFlowTemplatesListResponseResultsItemNameMax),
                description: zod.string().optional(),
                image_url: zod.string().max(hogFlowTemplatesListResponseResultsItemImageUrlMax).nullish(),
                tags: zod.array(zod.string()).optional(),
                scope: zod
                    .enum(['team', 'organization', 'global'])
                    .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
                created_at: zod.iso.datetime({}),
                created_by: zod.object({}).nullable(),
                updated_at: zod.iso.datetime({}),
                trigger: zod.unknown().optional(),
                trigger_masking: zod
                    .object({
                        ttl: zod
                            .number()
                            .min(hogFlowTemplatesListResponseResultsItemTriggerMaskingOneTtlMin)
                            .max(hogFlowTemplatesListResponseResultsItemTriggerMaskingOneTtlMax)
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
                            name: zod.string().max(hogFlowTemplatesListResponseResultsItemActionsItemNameMax),
                            description: zod
                                .string()
                                .default(hogFlowTemplatesListResponseResultsItemActionsItemDescriptionDefault),
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
                                        .default(
                                            hogFlowTemplatesListResponseResultsItemActionsItemFiltersOneSourceDefault
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
                                .nullish(),
                            type: zod.string().max(hogFlowTemplatesListResponseResultsItemActionsItemTypeMax),
                            config: zod.unknown(),
                            output_variable: zod.unknown().nullish(),
                        })
                        .describe(
                            'Custom action serializer for templates that skips input validation\n(since templates should have default/empty values).'
                        )
                ),
                abort_action: zod.string().max(hogFlowTemplatesListResponseResultsItemAbortActionMax).nullish(),
                variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
            })
            .describe(
                'Serializer for creating hog flow templates.\nValidates and sanitizes the workflow before creating it as a template.'
            )
    ),
})

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

/**
 * Check file-based global templates first, then DB team templates.
The queryset excludes all global templates from DB, so this only returns team templates from DB.
 */
export const hogFlowTemplatesRetrieveResponseNameMax = 400

export const hogFlowTemplatesRetrieveResponseImageUrlMax = 8201

export const hogFlowTemplatesRetrieveResponseTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesRetrieveResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesRetrieveResponseActionsItemNameMax = 400

export const hogFlowTemplatesRetrieveResponseActionsItemDescriptionDefault = ``
export const hogFlowTemplatesRetrieveResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesRetrieveResponseActionsItemTypeMax = 100

export const hogFlowTemplatesRetrieveResponseAbortActionMax = 400

export const HogFlowTemplatesRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(hogFlowTemplatesRetrieveResponseNameMax),
        description: zod.string().optional(),
        image_url: zod.string().max(hogFlowTemplatesRetrieveResponseImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: zod
            .enum(['team', 'organization', 'global'])
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({}).nullable(),
        updated_at: zod.iso.datetime({}),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesRetrieveResponseTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesRetrieveResponseTriggerMaskingOneTtlMax)
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
                    name: zod.string().max(hogFlowTemplatesRetrieveResponseActionsItemNameMax),
                    description: zod.string().default(hogFlowTemplatesRetrieveResponseActionsItemDescriptionDefault),
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
                                .default(hogFlowTemplatesRetrieveResponseActionsItemFiltersOneSourceDefault),
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
                    type: zod.string().max(hogFlowTemplatesRetrieveResponseActionsItemTypeMax),
                    config: zod.unknown(),
                    output_variable: zod.unknown().nullish(),
                })
                .describe(
                    'Custom action serializer for templates that skips input validation\n(since templates should have default/empty values).'
                )
        ),
        abort_action: zod.string().max(hogFlowTemplatesRetrieveResponseAbortActionMax).nullish(),
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

export const hogFlowTemplatesUpdateResponseNameMax = 400

export const hogFlowTemplatesUpdateResponseImageUrlMax = 8201

export const hogFlowTemplatesUpdateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesUpdateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesUpdateResponseActionsItemNameMax = 400

export const hogFlowTemplatesUpdateResponseActionsItemDescriptionDefault = ``
export const hogFlowTemplatesUpdateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesUpdateResponseActionsItemTypeMax = 100

export const hogFlowTemplatesUpdateResponseAbortActionMax = 400

export const HogFlowTemplatesUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(hogFlowTemplatesUpdateResponseNameMax),
        description: zod.string().optional(),
        image_url: zod.string().max(hogFlowTemplatesUpdateResponseImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: zod
            .enum(['team', 'organization', 'global'])
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({}).nullable(),
        updated_at: zod.iso.datetime({}),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesUpdateResponseTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesUpdateResponseTriggerMaskingOneTtlMax)
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
                    name: zod.string().max(hogFlowTemplatesUpdateResponseActionsItemNameMax),
                    description: zod.string().default(hogFlowTemplatesUpdateResponseActionsItemDescriptionDefault),
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
                                .default(hogFlowTemplatesUpdateResponseActionsItemFiltersOneSourceDefault),
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
                    type: zod.string().max(hogFlowTemplatesUpdateResponseActionsItemTypeMax),
                    config: zod.unknown(),
                    output_variable: zod.unknown().nullish(),
                })
                .describe(
                    'Custom action serializer for templates that skips input validation\n(since templates should have default/empty values).'
                )
        ),
        abort_action: zod.string().max(hogFlowTemplatesUpdateResponseAbortActionMax).nullish(),
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

export const hogFlowTemplatesPartialUpdateResponseNameMax = 400

export const hogFlowTemplatesPartialUpdateResponseImageUrlMax = 8201

export const hogFlowTemplatesPartialUpdateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowTemplatesPartialUpdateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowTemplatesPartialUpdateResponseActionsItemNameMax = 400

export const hogFlowTemplatesPartialUpdateResponseActionsItemDescriptionDefault = ``
export const hogFlowTemplatesPartialUpdateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowTemplatesPartialUpdateResponseActionsItemTypeMax = 100

export const hogFlowTemplatesPartialUpdateResponseAbortActionMax = 400

export const HogFlowTemplatesPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        name: zod.string().max(hogFlowTemplatesPartialUpdateResponseNameMax),
        description: zod.string().optional(),
        image_url: zod.string().max(hogFlowTemplatesPartialUpdateResponseImageUrlMax).nullish(),
        tags: zod.array(zod.string()).optional(),
        scope: zod
            .enum(['team', 'organization', 'global'])
            .describe('* `team` - Only team\n* `organization` - Organization\n* `global` - Global'),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({}).nullable(),
        updated_at: zod.iso.datetime({}),
        trigger: zod.unknown().optional(),
        trigger_masking: zod
            .object({
                ttl: zod
                    .number()
                    .min(hogFlowTemplatesPartialUpdateResponseTriggerMaskingOneTtlMin)
                    .max(hogFlowTemplatesPartialUpdateResponseTriggerMaskingOneTtlMax)
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
                    name: zod.string().max(hogFlowTemplatesPartialUpdateResponseActionsItemNameMax),
                    description: zod
                        .string()
                        .default(hogFlowTemplatesPartialUpdateResponseActionsItemDescriptionDefault),
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
                                .default(hogFlowTemplatesPartialUpdateResponseActionsItemFiltersOneSourceDefault),
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
                    type: zod.string().max(hogFlowTemplatesPartialUpdateResponseActionsItemTypeMax),
                    config: zod.unknown(),
                    output_variable: zod.unknown().nullish(),
                })
                .describe(
                    'Custom action serializer for templates that skips input validation\n(since templates should have default/empty values).'
                )
        ),
        abort_action: zod.string().max(hogFlowTemplatesPartialUpdateResponseAbortActionMax).nullish(),
        variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    })
    .describe(
        'Serializer for creating hog flow templates.\nValidates and sanitizes the workflow before creating it as a template.'
    )

export const hogFlowsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const hogFlowsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const hogFlowsListResponseResultsItemCreatedByOneLastNameMax = 150

export const hogFlowsListResponseResultsItemCreatedByOneEmailMax = 254

export const HogFlowsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string().nullable(),
            description: zod.string(),
            version: zod.number(),
            status: zod
                .enum(['draft', 'active', 'archived'])
                .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
            created_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(hogFlowsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(hogFlowsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(hogFlowsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(hogFlowsListResponseResultsItemCreatedByOneEmailMax),
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
            trigger_masking: zod.unknown().nullable(),
            conversion: zod.unknown().nullable(),
            exit_condition: zod
                .enum([
                    'exit_on_conversion',
                    'exit_on_trigger_not_matched',
                    'exit_on_trigger_not_matched_or_conversion',
                    'exit_only_at_end',
                ])
                .describe(
                    '* `exit_on_conversion` - Conversion\n* `exit_on_trigger_not_matched` - Trigger Not Matched\n* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion\n* `exit_only_at_end` - Only At End'
                ),
            edges: zod.unknown(),
            actions: zod.unknown(),
            abort_action: zod.string().nullable(),
            variables: zod.unknown().nullable(),
            billable_action_types: zod.unknown().nullable(),
        })
    ),
})

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

export const hogFlowsRetrieveResponseNameMax = 400

export const hogFlowsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsRetrieveResponseCreatedByOneFirstNameMax = 150

export const hogFlowsRetrieveResponseCreatedByOneLastNameMax = 150

export const hogFlowsRetrieveResponseCreatedByOneEmailMax = 254

export const hogFlowsRetrieveResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsRetrieveResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsRetrieveResponseActionsItemNameMax = 400

export const hogFlowsRetrieveResponseActionsItemDescriptionDefault = ``
export const hogFlowsRetrieveResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsRetrieveResponseActionsItemTypeMax = 100

export const HogFlowsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(hogFlowsRetrieveResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(hogFlowsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFlowsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFlowsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(hogFlowsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsRetrieveResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsRetrieveResponseTriggerMaskingOneTtlMax)
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
            name: zod.string().max(hogFlowsRetrieveResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsRetrieveResponseActionsItemDescriptionDefault),
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
                        .default(hogFlowsRetrieveResponseActionsItemFiltersOneSourceDefault),
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
            type: zod.string().max(hogFlowsRetrieveResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullable(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullable(),
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

export const hogFlowsUpdateResponseNameMax = 400

export const hogFlowsUpdateResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsUpdateResponseCreatedByOneFirstNameMax = 150

export const hogFlowsUpdateResponseCreatedByOneLastNameMax = 150

export const hogFlowsUpdateResponseCreatedByOneEmailMax = 254

export const hogFlowsUpdateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsUpdateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsUpdateResponseActionsItemNameMax = 400

export const hogFlowsUpdateResponseActionsItemDescriptionDefault = ``
export const hogFlowsUpdateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsUpdateResponseActionsItemTypeMax = 100

export const HogFlowsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(hogFlowsUpdateResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(hogFlowsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFlowsUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFlowsUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(hogFlowsUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsUpdateResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsUpdateResponseTriggerMaskingOneTtlMax)
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
            name: zod.string().max(hogFlowsUpdateResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsUpdateResponseActionsItemDescriptionDefault),
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
                        .default(hogFlowsUpdateResponseActionsItemFiltersOneSourceDefault),
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
            type: zod.string().max(hogFlowsUpdateResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullable(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullable(),
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

export const hogFlowsPartialUpdateResponseNameMax = 400

export const hogFlowsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const hogFlowsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const hogFlowsPartialUpdateResponseCreatedByOneEmailMax = 254

export const hogFlowsPartialUpdateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsPartialUpdateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsPartialUpdateResponseActionsItemNameMax = 400

export const hogFlowsPartialUpdateResponseActionsItemDescriptionDefault = ``
export const hogFlowsPartialUpdateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsPartialUpdateResponseActionsItemTypeMax = 100

export const HogFlowsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(hogFlowsPartialUpdateResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(hogFlowsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFlowsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFlowsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(hogFlowsPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsPartialUpdateResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsPartialUpdateResponseTriggerMaskingOneTtlMax)
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
            name: zod.string().max(hogFlowsPartialUpdateResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsPartialUpdateResponseActionsItemDescriptionDefault),
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
                        .default(hogFlowsPartialUpdateResponseActionsItemFiltersOneSourceDefault),
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
            type: zod.string().max(hogFlowsPartialUpdateResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullable(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullable(),
})

export const hogFlowsBatchJobsRetrieveResponseNameMax = 400

export const hogFlowsBatchJobsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsBatchJobsRetrieveResponseCreatedByOneFirstNameMax = 150

export const hogFlowsBatchJobsRetrieveResponseCreatedByOneLastNameMax = 150

export const hogFlowsBatchJobsRetrieveResponseCreatedByOneEmailMax = 254

export const hogFlowsBatchJobsRetrieveResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsBatchJobsRetrieveResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsBatchJobsRetrieveResponseActionsItemNameMax = 400

export const hogFlowsBatchJobsRetrieveResponseActionsItemDescriptionDefault = ``
export const hogFlowsBatchJobsRetrieveResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsBatchJobsRetrieveResponseActionsItemTypeMax = 100

export const HogFlowsBatchJobsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(hogFlowsBatchJobsRetrieveResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(hogFlowsBatchJobsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFlowsBatchJobsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFlowsBatchJobsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(hogFlowsBatchJobsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsBatchJobsRetrieveResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsBatchJobsRetrieveResponseTriggerMaskingOneTtlMax)
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
            name: zod.string().max(hogFlowsBatchJobsRetrieveResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsBatchJobsRetrieveResponseActionsItemDescriptionDefault),
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
                        .default(hogFlowsBatchJobsRetrieveResponseActionsItemFiltersOneSourceDefault),
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
            type: zod.string().max(hogFlowsBatchJobsRetrieveResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullable(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullable(),
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

export const hogFlowsBatchJobsCreateResponseNameMax = 400

export const hogFlowsBatchJobsCreateResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsBatchJobsCreateResponseCreatedByOneFirstNameMax = 150

export const hogFlowsBatchJobsCreateResponseCreatedByOneLastNameMax = 150

export const hogFlowsBatchJobsCreateResponseCreatedByOneEmailMax = 254

export const hogFlowsBatchJobsCreateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsBatchJobsCreateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsBatchJobsCreateResponseActionsItemNameMax = 400

export const hogFlowsBatchJobsCreateResponseActionsItemDescriptionDefault = ``
export const hogFlowsBatchJobsCreateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsBatchJobsCreateResponseActionsItemTypeMax = 100

export const HogFlowsBatchJobsCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(hogFlowsBatchJobsCreateResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(hogFlowsBatchJobsCreateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFlowsBatchJobsCreateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFlowsBatchJobsCreateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(hogFlowsBatchJobsCreateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsBatchJobsCreateResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsBatchJobsCreateResponseTriggerMaskingOneTtlMax)
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
            name: zod.string().max(hogFlowsBatchJobsCreateResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsBatchJobsCreateResponseActionsItemDescriptionDefault),
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
                        .default(hogFlowsBatchJobsCreateResponseActionsItemFiltersOneSourceDefault),
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
            type: zod.string().max(hogFlowsBatchJobsCreateResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullable(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullable(),
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

export const hogFlowsInvocationsCreateResponseNameMax = 400

export const hogFlowsInvocationsCreateResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsInvocationsCreateResponseCreatedByOneFirstNameMax = 150

export const hogFlowsInvocationsCreateResponseCreatedByOneLastNameMax = 150

export const hogFlowsInvocationsCreateResponseCreatedByOneEmailMax = 254

export const hogFlowsInvocationsCreateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsInvocationsCreateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsInvocationsCreateResponseActionsItemNameMax = 400

export const hogFlowsInvocationsCreateResponseActionsItemDescriptionDefault = ``
export const hogFlowsInvocationsCreateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsInvocationsCreateResponseActionsItemTypeMax = 100

export const HogFlowsInvocationsCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(hogFlowsInvocationsCreateResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(hogFlowsInvocationsCreateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFlowsInvocationsCreateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFlowsInvocationsCreateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(hogFlowsInvocationsCreateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsInvocationsCreateResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsInvocationsCreateResponseTriggerMaskingOneTtlMax)
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
            name: zod.string().max(hogFlowsInvocationsCreateResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsInvocationsCreateResponseActionsItemDescriptionDefault),
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
                        .default(hogFlowsInvocationsCreateResponseActionsItemFiltersOneSourceDefault),
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
            type: zod.string().max(hogFlowsInvocationsCreateResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullable(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullable(),
})

export const hogFlowsSchedulesListResponseResultsItemTimezoneMax = 64

export const HogFlowsSchedulesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            rrule: zod.string(),
            starts_at: zod.iso.datetime({}),
            timezone: zod.string().max(hogFlowsSchedulesListResponseResultsItemTimezoneMax).optional(),
            variables: zod.unknown().optional(),
            status: zod
                .enum(['active', 'paused', 'completed'])
                .describe('* `active` - Active\n* `paused` - Paused\n* `completed` - Completed'),
            next_run_at: zod.iso.datetime({}).nullable(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
        })
    ),
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

export const hogFlowsSchedulesCreateResponseResultsItemTimezoneMax = 64

export const HogFlowsSchedulesCreateResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            rrule: zod.string(),
            starts_at: zod.iso.datetime({}),
            timezone: zod.string().max(hogFlowsSchedulesCreateResponseResultsItemTimezoneMax).optional(),
            variables: zod.unknown().optional(),
            status: zod
                .enum(['active', 'paused', 'completed'])
                .describe('* `active` - Active\n* `paused` - Paused\n* `completed` - Completed'),
            next_run_at: zod.iso.datetime({}).nullable(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
        })
    ),
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

export const hogFlowsSchedulesPartialUpdateResponseNameMax = 400

export const hogFlowsSchedulesPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsSchedulesPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const hogFlowsSchedulesPartialUpdateResponseCreatedByOneLastNameMax = 150

export const hogFlowsSchedulesPartialUpdateResponseCreatedByOneEmailMax = 254

export const hogFlowsSchedulesPartialUpdateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsSchedulesPartialUpdateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsSchedulesPartialUpdateResponseActionsItemNameMax = 400

export const hogFlowsSchedulesPartialUpdateResponseActionsItemDescriptionDefault = ``
export const hogFlowsSchedulesPartialUpdateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsSchedulesPartialUpdateResponseActionsItemTypeMax = 100

export const HogFlowsSchedulesPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(hogFlowsSchedulesPartialUpdateResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(hogFlowsSchedulesPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFlowsSchedulesPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFlowsSchedulesPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(hogFlowsSchedulesPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsSchedulesPartialUpdateResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsSchedulesPartialUpdateResponseTriggerMaskingOneTtlMax)
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
            name: zod.string().max(hogFlowsSchedulesPartialUpdateResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsSchedulesPartialUpdateResponseActionsItemDescriptionDefault),
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
                        .default(hogFlowsSchedulesPartialUpdateResponseActionsItemFiltersOneSourceDefault),
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
            type: zod.string().max(hogFlowsSchedulesPartialUpdateResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullable(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullable(),
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

export const hogFlowsBulkDeleteCreateResponseNameMax = 400

export const hogFlowsBulkDeleteCreateResponseCreatedByOneDistinctIdMax = 200

export const hogFlowsBulkDeleteCreateResponseCreatedByOneFirstNameMax = 150

export const hogFlowsBulkDeleteCreateResponseCreatedByOneLastNameMax = 150

export const hogFlowsBulkDeleteCreateResponseCreatedByOneEmailMax = 254

export const hogFlowsBulkDeleteCreateResponseTriggerMaskingOneTtlMin = 60
export const hogFlowsBulkDeleteCreateResponseTriggerMaskingOneTtlMax = 94608000

export const hogFlowsBulkDeleteCreateResponseActionsItemNameMax = 400

export const hogFlowsBulkDeleteCreateResponseActionsItemDescriptionDefault = ``
export const hogFlowsBulkDeleteCreateResponseActionsItemFiltersOneSourceDefault = `events`
export const hogFlowsBulkDeleteCreateResponseActionsItemTypeMax = 100

export const HogFlowsBulkDeleteCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(hogFlowsBulkDeleteCreateResponseNameMax).nullish(),
    description: zod.string().optional(),
    version: zod.number(),
    status: zod
        .enum(['draft', 'active', 'archived'])
        .optional()
        .describe('* `draft` - Draft\n* `active` - Active\n* `archived` - Archived'),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(hogFlowsBulkDeleteCreateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(hogFlowsBulkDeleteCreateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(hogFlowsBulkDeleteCreateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(hogFlowsBulkDeleteCreateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    updated_at: zod.iso.datetime({}),
    trigger: zod.unknown().optional(),
    trigger_masking: zod
        .object({
            ttl: zod
                .number()
                .min(hogFlowsBulkDeleteCreateResponseTriggerMaskingOneTtlMin)
                .max(hogFlowsBulkDeleteCreateResponseTriggerMaskingOneTtlMax)
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
            name: zod.string().max(hogFlowsBulkDeleteCreateResponseActionsItemNameMax),
            description: zod.string().default(hogFlowsBulkDeleteCreateResponseActionsItemDescriptionDefault),
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
                        .default(hogFlowsBulkDeleteCreateResponseActionsItemFiltersOneSourceDefault),
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
            type: zod.string().max(hogFlowsBulkDeleteCreateResponseActionsItemTypeMax),
            config: zod.unknown(),
            output_variable: zod.unknown().nullish(),
        })
    ),
    abort_action: zod.string().nullable(),
    variables: zod.array(zod.record(zod.string(), zod.string())).optional(),
    billable_action_types: zod.unknown().nullable(),
})

export const HogFlowsUserBlastRadiusCreateBody = /* @__PURE__ */ zod.object({
    filters: zod.record(zod.string(), zod.unknown()).describe('Property filters to apply'),
    group_type_index: zod.number().nullish().describe('Group type index for group-based targeting'),
})

export const HogFlowsUserBlastRadiusCreateResponse = /* @__PURE__ */ zod.object({
    affected: zod.number().describe('Number of users matching the filters'),
    total: zod.number().describe('Total number of users'),
})
