/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 12 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const CohortsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CohortsListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const cohortsListResponseResultsItemNameMax = 400

export const cohortsListResponseResultsItemDescriptionMax = 1000

export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneBytecodeDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneBytecodeErrorDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneConditionHashDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneTimeValueDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneTimeIntervalDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneOperatorDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneOperatorValueDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneSeqTimeValueDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneSeqEventDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneSeqEventTypeDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneTotalPeriodsDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneMinPeriodsDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneEventFiltersDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemTwoBytecodeDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemTwoConditionHashDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemThreeBytecodeDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemThreeConditionHashDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemThreeOperatorDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemThreeValueDefault = null
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const cohortsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const cohortsListResponseResultsItemCreatedByOneLastNameMax = 150

export const cohortsListResponseResultsItemCreatedByOneEmailMax = 254

export const CohortsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.number(),
            name: zod.string().max(cohortsListResponseResultsItemNameMax).nullish(),
            description: zod.string().max(cohortsListResponseResultsItemDescriptionMax).optional(),
            groups: zod.unknown().optional(),
            deleted: zod.boolean().optional(),
            filters: zod
                .object({
                    properties: zod
                        .object({
                            type: zod.enum(['AND', 'OR']),
                            values: zod.array(
                                zod.union([
                                    zod.object({
                                        bytecode: zod
                                            .array(zod.unknown())
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneBytecodeDefault
                                            ),
                                        bytecode_error: zod
                                            .string()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneBytecodeErrorDefault
                                            ),
                                        conditionHash: zod
                                            .string()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneConditionHashDefault
                                            ),
                                        type: zod.enum(['behavioral']),
                                        key: zod.union([zod.string(), zod.number()]),
                                        value: zod.string(),
                                        event_type: zod.string(),
                                        time_value: zod
                                            .number()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneTimeValueDefault
                                            ),
                                        time_interval: zod
                                            .string()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneTimeIntervalDefault
                                            ),
                                        negation: zod
                                            .boolean()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneNegationDefault
                                            ),
                                        operator: zod
                                            .string()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneOperatorDefault
                                            ),
                                        operator_value: zod
                                            .number()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneOperatorValueDefault
                                            ),
                                        seq_time_interval: zod
                                            .string()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault
                                            ),
                                        seq_time_value: zod
                                            .number()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneSeqTimeValueDefault
                                            ),
                                        seq_event: zod
                                            .union([zod.string(), zod.number()])
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneSeqEventDefault
                                            ),
                                        seq_event_type: zod
                                            .string()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneSeqEventTypeDefault
                                            ),
                                        total_periods: zod
                                            .number()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneTotalPeriodsDefault
                                            ),
                                        min_periods: zod
                                            .number()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneMinPeriodsDefault
                                            ),
                                        event_filters: zod
                                            .array(
                                                zod.union([
                                                    zod.object({
                                                        type: zod.enum(['event', 'element']),
                                                        key: zod.string(),
                                                        value: zod.unknown(),
                                                        operator: zod
                                                            .string()
                                                            .default(
                                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault
                                                            ),
                                                    }),
                                                    zod.object({
                                                        type: zod.enum(['hogql']),
                                                        key: zod.string(),
                                                        value: zod
                                                            .unknown()
                                                            .default(
                                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault
                                                            ),
                                                    }),
                                                ])
                                            )
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneEventFiltersDefault
                                            ),
                                        explicit_datetime: zod
                                            .string()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault
                                            ),
                                    }),
                                    zod.object({
                                        bytecode: zod
                                            .array(zod.unknown())
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemTwoBytecodeDefault
                                            ),
                                        bytecode_error: zod
                                            .string()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault
                                            ),
                                        conditionHash: zod
                                            .string()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemTwoConditionHashDefault
                                            ),
                                        type: zod.enum(['cohort']),
                                        key: zod.enum(['id']),
                                        value: zod.number(),
                                        negation: zod
                                            .boolean()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemTwoNegationDefault
                                            ),
                                    }),
                                    zod.object({
                                        bytecode: zod
                                            .array(zod.unknown())
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemThreeBytecodeDefault
                                            ),
                                        bytecode_error: zod
                                            .string()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault
                                            ),
                                        conditionHash: zod
                                            .string()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemThreeConditionHashDefault
                                            ),
                                        type: zod.enum(['person']),
                                        key: zod.string(),
                                        operator: zod
                                            .string()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemThreeOperatorDefault
                                            ),
                                        value: zod
                                            .unknown()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemThreeValueDefault
                                            ),
                                        negation: zod
                                            .boolean()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemThreeNegationDefault
                                            ),
                                    }),
                                    zod.unknown(),
                                ])
                            ),
                        })
                        .describe(
                            'AND/OR group containing cohort filters. Named to avoid collision with analytics Group model.'
                        ),
                })
                .nullish(),
            query: zod.unknown().nullish(),
            version: zod.number().nullable(),
            pending_version: zod.number().nullable(),
            is_calculating: zod.boolean(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.string().uuid(),
                distinct_id: zod.string().max(cohortsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(cohortsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(cohortsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(cohortsListResponseResultsItemCreatedByOneEmailMax),
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
            created_at: zod.string().datetime({}).nullable(),
            last_calculation: zod.string().datetime({}).nullable(),
            errors_calculating: zod.number(),
            last_error_message: zod.string().nullable(),
            count: zod.number().nullable(),
            is_static: zod.boolean().optional(),
            cohort_type: zod
                .union([
                    zod
                        .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                        .describe(
                            '* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish()
                .describe(
                    'Type of cohort based on filter complexity\n\n* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
                ),
            experiment_set: zod.array(zod.number()),
            _create_in_folder: zod.string().optional(),
            _create_static_person_ids: zod.array(zod.string()).optional(),
        })
    ),
})

export const CohortsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const cohortsCreateBodyNameMax = 400

export const cohortsCreateBodyDescriptionMax = 1000

export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneOperatorDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeOperatorDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeValueDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeNegationDefault = false

export const CohortsCreateBody = zod.object({
    name: zod.string().max(cohortsCreateBodyNameMax).nullish(),
    description: zod.string().max(cohortsCreateBodyDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .object({
            properties: zod
                .object({
                    type: zod.enum(['AND', 'OR']),
                    values: zod.array(
                        zod.union([
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault),
                                conditionHash: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod
                                    .number()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault),
                                time_interval: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault),
                                negation: zod
                                    .boolean()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneOperatorDefault),
                                operator_value: zod
                                    .number()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault),
                                seq_time_interval: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault),
                                seq_time_value: zod
                                    .number()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault),
                                seq_event: zod
                                    .union([zod.string(), zod.number()])
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault),
                                seq_event_type: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault),
                                total_periods: zod
                                    .number()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault),
                                min_periods: zod
                                    .number()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod
                                                    .string()
                                                    .default(
                                                        cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod
                                                    .unknown()
                                                    .default(
                                                        cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault
                                                    ),
                                            }),
                                        ])
                                    )
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault),
                                explicit_datetime: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault),
                                conditionHash: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault),
                                conditionHash: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod
                                    .string()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeOperatorDefault),
                                value: zod
                                    .unknown()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeValueDefault),
                                negation: zod
                                    .boolean()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeNegationDefault),
                            }),
                            zod.unknown(),
                        ])
                    ),
                })
                .describe(
                    'AND/OR group containing cohort filters. Named to avoid collision with analytics Group model.'
                ),
        })
        .nullish(),
    query: zod.unknown().nullish(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Type of cohort based on filter complexity\n\n* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
        ),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod.array(zod.string()).optional(),
})

export const CohortsRetrieveParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this cohort.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const cohortsRetrieveResponseNameMax = 400

export const cohortsRetrieveResponseDescriptionMax = 1000

export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneBytecodeDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneBytecodeErrorDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneConditionHashDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneTimeValueDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneTimeIntervalDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneOperatorDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneOperatorValueDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneSeqTimeValueDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneSeqEventDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneSeqEventTypeDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneTotalPeriodsDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneMinPeriodsDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneEventFiltersDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemTwoBytecodeDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemTwoConditionHashDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemThreeBytecodeDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemThreeConditionHashDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemThreeOperatorDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemThreeValueDefault = null
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const cohortsRetrieveResponseCreatedByOneFirstNameMax = 150

export const cohortsRetrieveResponseCreatedByOneLastNameMax = 150

export const cohortsRetrieveResponseCreatedByOneEmailMax = 254

export const CohortsRetrieveResponse = zod.object({
    id: zod.number(),
    name: zod.string().max(cohortsRetrieveResponseNameMax).nullish(),
    description: zod.string().max(cohortsRetrieveResponseDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .object({
            properties: zod
                .object({
                    type: zod.enum(['AND', 'OR']),
                    values: zod.array(
                        zod.union([
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneConditionHashDefault
                                    ),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod
                                    .number()
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneTimeValueDefault),
                                time_interval: zod
                                    .string()
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneTimeIntervalDefault
                                    ),
                                negation: zod
                                    .boolean()
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod
                                    .string()
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneOperatorDefault),
                                operator_value: zod
                                    .number()
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneOperatorValueDefault
                                    ),
                                seq_time_interval: zod
                                    .string()
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault
                                    ),
                                seq_time_value: zod
                                    .number()
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneSeqTimeValueDefault
                                    ),
                                seq_event: zod
                                    .union([zod.string(), zod.number()])
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneSeqEventDefault),
                                seq_event_type: zod
                                    .string()
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneSeqEventTypeDefault
                                    ),
                                total_periods: zod
                                    .number()
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneTotalPeriodsDefault
                                    ),
                                min_periods: zod
                                    .number()
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneMinPeriodsDefault),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod
                                                    .string()
                                                    .default(
                                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod
                                                    .unknown()
                                                    .default(
                                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault
                                                    ),
                                            }),
                                        ])
                                    )
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneEventFiltersDefault
                                    ),
                                explicit_datetime: zod
                                    .string()
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault
                                    ),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemTwoBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemTwoConditionHashDefault
                                    ),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemThreeBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsRetrieveResponseFiltersOnePropertiesValuesItemThreeConditionHashDefault
                                    ),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod
                                    .string()
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemThreeOperatorDefault),
                                value: zod
                                    .unknown()
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemThreeValueDefault),
                                negation: zod
                                    .boolean()
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemThreeNegationDefault),
                            }),
                            zod.unknown(),
                        ])
                    ),
                })
                .describe(
                    'AND/OR group containing cohort filters. Named to avoid collision with analytics Group model.'
                ),
        })
        .nullish(),
    query: zod.unknown().nullish(),
    version: zod.number().nullable(),
    pending_version: zod.number().nullable(),
    is_calculating: zod.boolean(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.string().uuid(),
        distinct_id: zod.string().max(cohortsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(cohortsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(cohortsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.string().email().max(cohortsRetrieveResponseCreatedByOneEmailMax),
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
    created_at: zod.string().datetime({}).nullable(),
    last_calculation: zod.string().datetime({}).nullable(),
    errors_calculating: zod.number(),
    last_error_message: zod.string().nullable(),
    count: zod.number().nullable(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Type of cohort based on filter complexity\n\n* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
        ),
    experiment_set: zod.array(zod.number()),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod.array(zod.string()).optional(),
})

export const CohortsUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this cohort.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const cohortsUpdateBodyNameMax = 400

export const cohortsUpdateBodyDescriptionMax = 1000

export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneOperatorDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeOperatorDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeValueDefault = null
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeNegationDefault = false

export const CohortsUpdateBody = zod.object({
    name: zod.string().max(cohortsUpdateBodyNameMax).nullish(),
    description: zod.string().max(cohortsUpdateBodyDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .object({
            properties: zod
                .object({
                    type: zod.enum(['AND', 'OR']),
                    values: zod.array(
                        zod.union([
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault),
                                conditionHash: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod
                                    .number()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault),
                                time_interval: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneOperatorDefault),
                                operator_value: zod
                                    .number()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault),
                                seq_time_interval: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault),
                                seq_time_value: zod
                                    .number()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault),
                                seq_event: zod
                                    .union([zod.string(), zod.number()])
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault),
                                seq_event_type: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault),
                                total_periods: zod
                                    .number()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault),
                                min_periods: zod
                                    .number()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod
                                                    .string()
                                                    .default(
                                                        cohortsUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod
                                                    .unknown()
                                                    .default(
                                                        cohortsUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault
                                                    ),
                                            }),
                                        ])
                                    )
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault),
                                explicit_datetime: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault),
                                conditionHash: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault),
                                conditionHash: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod
                                    .string()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeOperatorDefault),
                                value: zod
                                    .unknown()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeValueDefault),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeNegationDefault),
                            }),
                            zod.unknown(),
                        ])
                    ),
                })
                .describe(
                    'AND/OR group containing cohort filters. Named to avoid collision with analytics Group model.'
                ),
        })
        .nullish(),
    query: zod.unknown().nullish(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Type of cohort based on filter complexity\n\n* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
        ),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod.array(zod.string()).optional(),
})

export const cohortsUpdateResponseNameMax = 400

export const cohortsUpdateResponseDescriptionMax = 1000

export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneBytecodeDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneBytecodeErrorDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneConditionHashDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneTimeValueDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneTimeIntervalDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneOperatorDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneOperatorValueDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneSeqTimeValueDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneSeqEventDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneSeqEventTypeDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneTotalPeriodsDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneMinPeriodsDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneEventFiltersDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemTwoBytecodeDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemTwoConditionHashDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemThreeBytecodeDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemThreeConditionHashDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemThreeOperatorDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemThreeValueDefault = null
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsUpdateResponseCreatedByOneDistinctIdMax = 200

export const cohortsUpdateResponseCreatedByOneFirstNameMax = 150

export const cohortsUpdateResponseCreatedByOneLastNameMax = 150

export const cohortsUpdateResponseCreatedByOneEmailMax = 254

export const CohortsUpdateResponse = zod.object({
    id: zod.number(),
    name: zod.string().max(cohortsUpdateResponseNameMax).nullish(),
    description: zod.string().max(cohortsUpdateResponseDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .object({
            properties: zod
                .object({
                    type: zod.enum(['AND', 'OR']),
                    values: zod.array(
                        zod.union([
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemOneBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsUpdateResponseFiltersOnePropertiesValuesItemOneBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsUpdateResponseFiltersOnePropertiesValuesItemOneConditionHashDefault
                                    ),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod
                                    .number()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemOneTimeValueDefault),
                                time_interval: zod
                                    .string()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemOneTimeIntervalDefault),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod
                                    .string()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemOneOperatorDefault),
                                operator_value: zod
                                    .number()
                                    .default(
                                        cohortsUpdateResponseFiltersOnePropertiesValuesItemOneOperatorValueDefault
                                    ),
                                seq_time_interval: zod
                                    .string()
                                    .default(
                                        cohortsUpdateResponseFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault
                                    ),
                                seq_time_value: zod
                                    .number()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemOneSeqTimeValueDefault),
                                seq_event: zod
                                    .union([zod.string(), zod.number()])
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemOneSeqEventDefault),
                                seq_event_type: zod
                                    .string()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemOneSeqEventTypeDefault),
                                total_periods: zod
                                    .number()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemOneTotalPeriodsDefault),
                                min_periods: zod
                                    .number()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemOneMinPeriodsDefault),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod
                                                    .string()
                                                    .default(
                                                        cohortsUpdateResponseFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod
                                                    .unknown()
                                                    .default(
                                                        cohortsUpdateResponseFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault
                                                    ),
                                            }),
                                        ])
                                    )
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemOneEventFiltersDefault),
                                explicit_datetime: zod
                                    .string()
                                    .default(
                                        cohortsUpdateResponseFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault
                                    ),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemTwoBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsUpdateResponseFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsUpdateResponseFiltersOnePropertiesValuesItemTwoConditionHashDefault
                                    ),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemThreeBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsUpdateResponseFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsUpdateResponseFiltersOnePropertiesValuesItemThreeConditionHashDefault
                                    ),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod
                                    .string()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemThreeOperatorDefault),
                                value: zod
                                    .unknown()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemThreeValueDefault),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemThreeNegationDefault),
                            }),
                            zod.unknown(),
                        ])
                    ),
                })
                .describe(
                    'AND/OR group containing cohort filters. Named to avoid collision with analytics Group model.'
                ),
        })
        .nullish(),
    query: zod.unknown().nullish(),
    version: zod.number().nullable(),
    pending_version: zod.number().nullable(),
    is_calculating: zod.boolean(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.string().uuid(),
        distinct_id: zod.string().max(cohortsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(cohortsUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(cohortsUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.string().email().max(cohortsUpdateResponseCreatedByOneEmailMax),
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
    created_at: zod.string().datetime({}).nullable(),
    last_calculation: zod.string().datetime({}).nullable(),
    errors_calculating: zod.number(),
    last_error_message: zod.string().nullable(),
    count: zod.number().nullable(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Type of cohort based on filter complexity\n\n* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
        ),
    experiment_set: zod.array(zod.number()),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod.array(zod.string()).optional(),
})

export const CohortsPartialUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this cohort.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const cohortsPartialUpdateBodyNameMax = 400

export const cohortsPartialUpdateBodyDescriptionMax = 1000

export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneOperatorDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeOperatorDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeValueDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeNegationDefault = false

export const CohortsPartialUpdateBody = zod.object({
    name: zod.string().max(cohortsPartialUpdateBodyNameMax).nullish(),
    description: zod.string().max(cohortsPartialUpdateBodyDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .object({
            properties: zod
                .object({
                    type: zod.enum(['AND', 'OR']),
                    values: zod.array(
                        zod.union([
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault
                                    ),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod
                                    .number()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault),
                                time_interval: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault
                                    ),
                                negation: zod
                                    .boolean()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod
                                    .string()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneOperatorDefault),
                                operator_value: zod
                                    .number()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault
                                    ),
                                seq_time_interval: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault
                                    ),
                                seq_time_value: zod
                                    .number()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault
                                    ),
                                seq_event: zod
                                    .union([zod.string(), zod.number()])
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault),
                                seq_event_type: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault
                                    ),
                                total_periods: zod
                                    .number()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault
                                    ),
                                min_periods: zod
                                    .number()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault
                                    ),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod
                                                    .string()
                                                    .default(
                                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod
                                                    .unknown()
                                                    .default(
                                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault
                                                    ),
                                            }),
                                        ])
                                    )
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault
                                    ),
                                explicit_datetime: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault
                                    ),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault
                                    ),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault
                                    ),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault
                                    ),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeOperatorDefault
                                    ),
                                value: zod
                                    .unknown()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeValueDefault),
                                negation: zod
                                    .boolean()
                                    .default(
                                        cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeNegationDefault
                                    ),
                            }),
                            zod.unknown(),
                        ])
                    ),
                })
                .describe(
                    'AND/OR group containing cohort filters. Named to avoid collision with analytics Group model.'
                ),
        })
        .nullish(),
    query: zod.unknown().nullish(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Type of cohort based on filter complexity\n\n* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
        ),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod.array(zod.string()).optional(),
})

export const cohortsPartialUpdateResponseNameMax = 400

export const cohortsPartialUpdateResponseDescriptionMax = 1000

export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneBytecodeDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneBytecodeErrorDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneConditionHashDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneTimeValueDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneTimeIntervalDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneOperatorDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneOperatorValueDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneSeqTimeValueDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneSeqEventDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneSeqEventTypeDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneTotalPeriodsDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneMinPeriodsDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneEventFiltersDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemTwoBytecodeDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemTwoConditionHashDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemThreeBytecodeDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemThreeConditionHashDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemThreeOperatorDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemThreeValueDefault = null
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const cohortsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const cohortsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const cohortsPartialUpdateResponseCreatedByOneEmailMax = 254

export const CohortsPartialUpdateResponse = zod.object({
    id: zod.number(),
    name: zod.string().max(cohortsPartialUpdateResponseNameMax).nullish(),
    description: zod.string().max(cohortsPartialUpdateResponseDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .object({
            properties: zod
                .object({
                    type: zod.enum(['AND', 'OR']),
                    values: zod.array(
                        zod.union([
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneBytecodeDefault
                                    ),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneConditionHashDefault
                                    ),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod
                                    .number()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneTimeValueDefault
                                    ),
                                time_interval: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneTimeIntervalDefault
                                    ),
                                negation: zod
                                    .boolean()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneNegationDefault
                                    ),
                                operator: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneOperatorDefault
                                    ),
                                operator_value: zod
                                    .number()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneOperatorValueDefault
                                    ),
                                seq_time_interval: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault
                                    ),
                                seq_time_value: zod
                                    .number()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneSeqTimeValueDefault
                                    ),
                                seq_event: zod
                                    .union([zod.string(), zod.number()])
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneSeqEventDefault
                                    ),
                                seq_event_type: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneSeqEventTypeDefault
                                    ),
                                total_periods: zod
                                    .number()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneTotalPeriodsDefault
                                    ),
                                min_periods: zod
                                    .number()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneMinPeriodsDefault
                                    ),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod
                                                    .string()
                                                    .default(
                                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneEventFiltersItemOneOperatorDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod
                                                    .unknown()
                                                    .default(
                                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneEventFiltersItemTwoValueDefault
                                                    ),
                                            }),
                                        ])
                                    )
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneEventFiltersDefault
                                    ),
                                explicit_datetime: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault
                                    ),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemTwoBytecodeDefault
                                    ),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemTwoConditionHashDefault
                                    ),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemTwoNegationDefault
                                    ),
                            }),
                            zod.object({
                                bytecode: zod
                                    .array(zod.unknown())
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemThreeBytecodeDefault
                                    ),
                                bytecode_error: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault
                                    ),
                                conditionHash: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemThreeConditionHashDefault
                                    ),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod
                                    .string()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemThreeOperatorDefault
                                    ),
                                value: zod
                                    .unknown()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemThreeValueDefault
                                    ),
                                negation: zod
                                    .boolean()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemThreeNegationDefault
                                    ),
                            }),
                            zod.unknown(),
                        ])
                    ),
                })
                .describe(
                    'AND/OR group containing cohort filters. Named to avoid collision with analytics Group model.'
                ),
        })
        .nullish(),
    query: zod.unknown().nullish(),
    version: zod.number().nullable(),
    pending_version: zod.number().nullable(),
    is_calculating: zod.boolean(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.string().uuid(),
        distinct_id: zod.string().max(cohortsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(cohortsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(cohortsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.string().email().max(cohortsPartialUpdateResponseCreatedByOneEmailMax),
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
    created_at: zod.string().datetime({}).nullable(),
    last_calculation: zod.string().datetime({}).nullable(),
    errors_calculating: zod.number(),
    last_error_message: zod.string().nullable(),
    count: zod.number().nullable(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'Type of cohort based on filter complexity\n\n* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
        ),
    experiment_set: zod.array(zod.number()),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod.array(zod.string()).optional(),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const CohortsDestroyParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this cohort.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CohortsAddPersonsToStaticCohortPartialUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this cohort.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CohortsAddPersonsToStaticCohortPartialUpdateBody = zod.object({
    person_ids: zod.array(zod.string().uuid()).optional().describe('List of person UUIDs to add to the cohort'),
})

export const CohortsCalculationHistoryRetrieveParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this cohort.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CohortsPersonsRetrieveParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this cohort.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CohortsPersonsRetrieveQueryParams = zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

export const CohortsRemovePersonFromStaticCohortPartialUpdateParams = zod.object({
    id: zod.number().describe('A unique integer value identifying this cohort.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CohortsRemovePersonFromStaticCohortPartialUpdateBody = zod.object({
    person_id: zod.string().uuid().optional().describe('Person UUID to remove from the cohort'),
})

export const CohortsActivityRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 */
export const PersonsCohortsRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const PersonsCohortsRetrieveQueryParams = zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})
