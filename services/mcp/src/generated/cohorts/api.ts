/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 6 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const CohortsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CohortsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const CohortsCreateParams = /* @__PURE__ */ zod.object({
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
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersOneItemOneOperatorDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersOneItemTwoValueDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault = null
export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeToDefault = null
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
export const cohortsCreateBodyCreateStaticPersonIdsDefault = []

export const CohortsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(cohortsCreateBodyNameMax).nullish(),
    description: zod.string().max(cohortsCreateBodyDescriptionMax).optional(),
    filters: zod
        .union([
            zod.object({
                properties: zod
                    .object({
                        type: zod.enum(['AND', 'OR']),
                        values: zod.array(
                            zod.union([
                                zod.object({
                                    bytecode: zod
                                        .union([zod.array(zod.unknown()), zod.null()])
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault),
                                    bytecode_error: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsCreateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault
                                        ),
                                    conditionHash: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsCreateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault
                                        ),
                                    type: zod.literal('behavioral'),
                                    key: zod.union([zod.string(), zod.number()]),
                                    value: zod.string(),
                                    event_type: zod.string(),
                                    time_value: zod
                                        .union([zod.number(), zod.null()])
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault),
                                    time_interval: zod
                                        .union([zod.string(), zod.null()])
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault),
                                    negation: zod
                                        .boolean()
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                    operator: zod
                                        .union([zod.string(), zod.null()])
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneOperatorDefault),
                                    operator_value: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            cohortsCreateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault
                                        ),
                                    seq_time_interval: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault
                                        ),
                                    seq_time_value: zod
                                        .union([zod.number(), zod.null()])
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault),
                                    seq_event: zod
                                        .union([zod.string(), zod.number(), zod.null()])
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault),
                                    seq_event_type: zod
                                        .union([zod.string(), zod.null()])
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault),
                                    total_periods: zod
                                        .union([zod.number(), zod.null()])
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault),
                                    min_periods: zod
                                        .union([zod.number(), zod.null()])
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault),
                                    event_filters: zod
                                        .union([
                                            zod.array(
                                                zod.union([
                                                    zod.object({
                                                        type: zod.enum(['event', 'element']),
                                                        key: zod.string(),
                                                        value: zod.unknown(),
                                                        operator: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersOneItemOneOperatorDefault
                                                            ),
                                                    }),
                                                    zod.object({
                                                        type: zod.literal('hogql'),
                                                        key: zod.string(),
                                                        value: zod
                                                            .unknown()
                                                            .default(
                                                                cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersOneItemTwoValueDefault
                                                            ),
                                                    }),
                                                ])
                                            ),
                                            zod.null(),
                                        ])
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault),
                                    explicit_datetime: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsCreateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault
                                        ),
                                    explicit_datetime_to: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsCreateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeToDefault
                                        ),
                                }),
                                zod.object({
                                    bytecode: zod
                                        .union([zod.array(zod.unknown()), zod.null()])
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault),
                                    bytecode_error: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsCreateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault
                                        ),
                                    conditionHash: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsCreateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault
                                        ),
                                    type: zod.literal('cohort'),
                                    key: zod.literal('id'),
                                    value: zod.number(),
                                    negation: zod
                                        .boolean()
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                                }),
                                zod.object({
                                    bytecode: zod
                                        .union([zod.array(zod.unknown()), zod.null()])
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault),
                                    bytecode_error: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsCreateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault
                                        ),
                                    conditionHash: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsCreateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault
                                        ),
                                    type: zod.literal('person'),
                                    key: zod.string(),
                                    operator: zod
                                        .union([zod.string(), zod.null()])
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
            }),
            zod.null(),
        ])
        .optional(),
    query: zod.unknown().optional(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.null(),
        ])
        .optional()
        .describe(
            'Type of cohort based on filter complexity\n\n* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
        ),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod.array(zod.string()).default(cohortsCreateBodyCreateStaticPersonIdsDefault),
})

export const CohortsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this cohort.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CohortsPartialUpdateParams = /* @__PURE__ */ zod.object({
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
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersOneItemOneOperatorDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersOneItemTwoValueDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault = null
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeToDefault = null
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

export const CohortsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(cohortsPartialUpdateBodyNameMax).nullish(),
    description: zod.string().max(cohortsPartialUpdateBodyDescriptionMax).optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .union([
            zod.object({
                properties: zod
                    .object({
                        type: zod.enum(['AND', 'OR']),
                        values: zod.array(
                            zod.union([
                                zod.object({
                                    bytecode: zod
                                        .union([zod.array(zod.unknown()), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeDefault
                                        ),
                                    bytecode_error: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneBytecodeErrorDefault
                                        ),
                                    conditionHash: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneConditionHashDefault
                                        ),
                                    type: zod.literal('behavioral'),
                                    key: zod.union([zod.string(), zod.number()]),
                                    value: zod.string(),
                                    event_type: zod.string(),
                                    time_value: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTimeValueDefault
                                        ),
                                    time_interval: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTimeIntervalDefault
                                        ),
                                    negation: zod
                                        .boolean()
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault
                                        ),
                                    operator: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneOperatorDefault
                                        ),
                                    operator_value: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneOperatorValueDefault
                                        ),
                                    seq_time_interval: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeIntervalDefault
                                        ),
                                    seq_time_value: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqTimeValueDefault
                                        ),
                                    seq_event: zod
                                        .union([zod.string(), zod.number(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventDefault
                                        ),
                                    seq_event_type: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneSeqEventTypeDefault
                                        ),
                                    total_periods: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneTotalPeriodsDefault
                                        ),
                                    min_periods: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneMinPeriodsDefault
                                        ),
                                    event_filters: zod
                                        .union([
                                            zod.array(
                                                zod.union([
                                                    zod.object({
                                                        type: zod.enum(['event', 'element']),
                                                        key: zod.string(),
                                                        value: zod.unknown(),
                                                        operator: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersOneItemOneOperatorDefault
                                                            ),
                                                    }),
                                                    zod.object({
                                                        type: zod.literal('hogql'),
                                                        key: zod.string(),
                                                        value: zod
                                                            .unknown()
                                                            .default(
                                                                cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersOneItemTwoValueDefault
                                                            ),
                                                    }),
                                                ])
                                            ),
                                            zod.null(),
                                        ])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneEventFiltersDefault
                                        ),
                                    explicit_datetime: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeDefault
                                        ),
                                    explicit_datetime_to: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneExplicitDatetimeToDefault
                                        ),
                                }),
                                zod.object({
                                    bytecode: zod
                                        .union([zod.array(zod.unknown()), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeDefault
                                        ),
                                    bytecode_error: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoBytecodeErrorDefault
                                        ),
                                    conditionHash: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoConditionHashDefault
                                        ),
                                    type: zod.literal('cohort'),
                                    key: zod.literal('id'),
                                    value: zod.number(),
                                    negation: zod
                                        .boolean()
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault
                                        ),
                                }),
                                zod.object({
                                    bytecode: zod
                                        .union([zod.array(zod.unknown()), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeDefault
                                        ),
                                    bytecode_error: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeBytecodeErrorDefault
                                        ),
                                    conditionHash: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeConditionHashDefault
                                        ),
                                    type: zod.literal('person'),
                                    key: zod.string(),
                                    operator: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeOperatorDefault
                                        ),
                                    value: zod
                                        .unknown()
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeValueDefault
                                        ),
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
            }),
            zod.null(),
        ])
        .optional(),
    query: zod.unknown().optional(),
    is_static: zod.boolean().optional(),
    cohort_type: zod
        .union([
            zod
                .enum(['static', 'person_property', 'behavioral', 'realtime', 'analytical'])
                .describe(
                    '* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
                ),
            zod.enum(['']),
            zod.null(),
        ])
        .optional()
        .describe(
            'Type of cohort based on filter complexity\n\n* `static` - static\n* `person_property` - person_property\n* `behavioral` - behavioral\n* `realtime` - realtime\n* `analytical` - analytical'
        ),
    _create_in_folder: zod.string().optional(),
    _create_static_person_ids: zod.array(zod.string()).optional(),
})

export const CohortsAddPersonsToStaticCohortPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this cohort.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CohortsAddPersonsToStaticCohortPartialUpdateBody = /* @__PURE__ */ zod.object({
    person_ids: zod.array(zod.string()).optional().describe('List of person UUIDs to add to the cohort'),
})

export const CohortsRemovePersonFromStaticCohortPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this cohort.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const CohortsRemovePersonFromStaticCohortPartialUpdateBody = /* @__PURE__ */ zod.object({
    person_id: zod.string().optional().describe('Person UUID to remove from the cohort'),
})
