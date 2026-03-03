/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 13 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * This endpoint is meant for reading and deleting persons. To create or update persons, we recommend using the [capture API](https://posthog.com/docs/api/capture), the `$set` and `$unset` [properties](https://posthog.com/docs/product-analytics/user-properties), or one of our SDKs.
 * @deprecated
 */
export const EnvironmentsPersonsCohortsRetrieveParams = zod.object({
    environment_id: zod.string().describe('Deprecated. Use /api/projects/{project_id}/ instead.'),
})

export const EnvironmentsPersonsCohortsRetrieveQueryParams = zod.object({
    format: zod.enum(['csv', 'json']).optional(),
})

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

export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsListResponseResultsItemFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const cohortsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const cohortsListResponseResultsItemCreatedByOneLastNameMax = 150

export const cohortsListResponseResultsItemCreatedByOneEmailMax = 254

export const cohortsListResponseResultsItemCreateStaticPersonIdsDefault = []

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
                                        bytecode: zod.array(zod.unknown()).nullish(),
                                        bytecode_error: zod.string().nullish(),
                                        conditionHash: zod.string().nullish(),
                                        type: zod.enum(['behavioral']),
                                        key: zod.union([zod.string(), zod.number()]),
                                        value: zod.string(),
                                        event_type: zod.string(),
                                        time_value: zod.number().nullish(),
                                        time_interval: zod.string().nullish(),
                                        negation: zod
                                            .boolean()
                                            .default(
                                                cohortsListResponseResultsItemFiltersOnePropertiesValuesItemOneNegationDefault
                                            ),
                                        operator: zod.string().nullish(),
                                        operator_value: zod.number().nullish(),
                                        seq_time_interval: zod.string().nullish(),
                                        seq_time_value: zod.number().nullish(),
                                        seq_event: zod.union([zod.string(), zod.number()]).nullish(),
                                        seq_event_type: zod.string().nullish(),
                                        total_periods: zod.number().nullish(),
                                        min_periods: zod.number().nullish(),
                                        event_filters: zod
                                            .array(
                                                zod.union([
                                                    zod.object({
                                                        type: zod.enum(['event', 'element']),
                                                        key: zod.string(),
                                                        value: zod.unknown(),
                                                        operator: zod.string().nullish(),
                                                    }),
                                                    zod.object({
                                                        type: zod.enum(['hogql']),
                                                        key: zod.string(),
                                                        value: zod.unknown().nullish(),
                                                    }),
                                                ])
                                            )
                                            .nullish(),
                                        explicit_datetime: zod.string().nullish(),
                                    }),
                                    zod.object({
                                        bytecode: zod.array(zod.unknown()).nullish(),
                                        bytecode_error: zod.string().nullish(),
                                        conditionHash: zod.string().nullish(),
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
                                        bytecode: zod.array(zod.unknown()).nullish(),
                                        bytecode_error: zod.string().nullish(),
                                        conditionHash: zod.string().nullish(),
                                        type: zod.enum(['person']),
                                        key: zod.string(),
                                        operator: zod.string().nullish(),
                                        value: zod.unknown().nullish(),
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
            _create_static_person_ids: zod
                .array(zod.string())
                .default(cohortsListResponseResultsItemCreateStaticPersonIdsDefault),
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

export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsCreateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsCreateBodyCreateStaticPersonIdsDefault = []

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
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod.number().nullish(),
                                time_interval: zod.string().nullish(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod.string().nullish(),
                                operator_value: zod.number().nullish(),
                                seq_time_interval: zod.string().nullish(),
                                seq_time_value: zod.number().nullish(),
                                seq_event: zod.union([zod.string(), zod.number()]).nullish(),
                                seq_event_type: zod.string().nullish(),
                                total_periods: zod.number().nullish(),
                                min_periods: zod.number().nullish(),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod.string().nullish(),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod.unknown().nullish(),
                                            }),
                                        ])
                                    )
                                    .nullish(),
                                explicit_datetime: zod.string().nullish(),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsCreateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod.string().nullish(),
                                value: zod.unknown().nullish(),
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
    _create_static_person_ids: zod.array(zod.string()).default(cohortsCreateBodyCreateStaticPersonIdsDefault),
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

export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsRetrieveResponseFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const cohortsRetrieveResponseCreatedByOneFirstNameMax = 150

export const cohortsRetrieveResponseCreatedByOneLastNameMax = 150

export const cohortsRetrieveResponseCreatedByOneEmailMax = 254

export const cohortsRetrieveResponseCreateStaticPersonIdsDefault = []

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
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod.number().nullish(),
                                time_interval: zod.string().nullish(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod.string().nullish(),
                                operator_value: zod.number().nullish(),
                                seq_time_interval: zod.string().nullish(),
                                seq_time_value: zod.number().nullish(),
                                seq_event: zod.union([zod.string(), zod.number()]).nullish(),
                                seq_event_type: zod.string().nullish(),
                                total_periods: zod.number().nullish(),
                                min_periods: zod.number().nullish(),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod.string().nullish(),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod.unknown().nullish(),
                                            }),
                                        ])
                                    )
                                    .nullish(),
                                explicit_datetime: zod.string().nullish(),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsRetrieveResponseFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod.string().nullish(),
                                value: zod.unknown().nullish(),
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
    _create_static_person_ids: zod.array(zod.string()).default(cohortsRetrieveResponseCreateStaticPersonIdsDefault),
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

export const cohortsUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsUpdateBodyFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsUpdateBodyCreateStaticPersonIdsDefault = []

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
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod.number().nullish(),
                                time_interval: zod.string().nullish(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod.string().nullish(),
                                operator_value: zod.number().nullish(),
                                seq_time_interval: zod.string().nullish(),
                                seq_time_value: zod.number().nullish(),
                                seq_event: zod.union([zod.string(), zod.number()]).nullish(),
                                seq_event_type: zod.string().nullish(),
                                total_periods: zod.number().nullish(),
                                min_periods: zod.number().nullish(),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod.string().nullish(),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod.unknown().nullish(),
                                            }),
                                        ])
                                    )
                                    .nullish(),
                                explicit_datetime: zod.string().nullish(),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod.string().nullish(),
                                value: zod.unknown().nullish(),
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
    _create_static_person_ids: zod.array(zod.string()).default(cohortsUpdateBodyCreateStaticPersonIdsDefault),
})

export const cohortsUpdateResponseNameMax = 400

export const cohortsUpdateResponseDescriptionMax = 1000

export const cohortsUpdateResponseFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsUpdateResponseFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsUpdateResponseCreatedByOneDistinctIdMax = 200

export const cohortsUpdateResponseCreatedByOneFirstNameMax = 150

export const cohortsUpdateResponseCreatedByOneLastNameMax = 150

export const cohortsUpdateResponseCreatedByOneEmailMax = 254

export const cohortsUpdateResponseCreateStaticPersonIdsDefault = []

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
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod.number().nullish(),
                                time_interval: zod.string().nullish(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod.string().nullish(),
                                operator_value: zod.number().nullish(),
                                seq_time_interval: zod.string().nullish(),
                                seq_time_value: zod.number().nullish(),
                                seq_event: zod.union([zod.string(), zod.number()]).nullish(),
                                seq_event_type: zod.string().nullish(),
                                total_periods: zod.number().nullish(),
                                min_periods: zod.number().nullish(),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod.string().nullish(),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod.unknown().nullish(),
                                            }),
                                        ])
                                    )
                                    .nullish(),
                                explicit_datetime: zod.string().nullish(),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsUpdateResponseFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod.string().nullish(),
                                value: zod.unknown().nullish(),
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
    _create_static_person_ids: zod.array(zod.string()).default(cohortsUpdateResponseCreateStaticPersonIdsDefault),
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

export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsPartialUpdateBodyCreateStaticPersonIdsDefault = []

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
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod.number().nullish(),
                                time_interval: zod.string().nullish(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                operator: zod.string().nullish(),
                                operator_value: zod.number().nullish(),
                                seq_time_interval: zod.string().nullish(),
                                seq_time_value: zod.number().nullish(),
                                seq_event: zod.union([zod.string(), zod.number()]).nullish(),
                                seq_event_type: zod.string().nullish(),
                                total_periods: zod.number().nullish(),
                                min_periods: zod.number().nullish(),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod.string().nullish(),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod.unknown().nullish(),
                                            }),
                                        ])
                                    )
                                    .nullish(),
                                explicit_datetime: zod.string().nullish(),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['cohort']),
                                key: zod.enum(['id']),
                                value: zod.number(),
                                negation: zod
                                    .boolean()
                                    .default(cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod.string().nullish(),
                                value: zod.unknown().nullish(),
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
    _create_static_person_ids: zod.array(zod.string()).default(cohortsPartialUpdateBodyCreateStaticPersonIdsDefault),
})

export const cohortsPartialUpdateResponseNameMax = 400

export const cohortsPartialUpdateResponseDescriptionMax = 1000

export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const cohortsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const cohortsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const cohortsPartialUpdateResponseCreatedByOneEmailMax = 254

export const cohortsPartialUpdateResponseCreateStaticPersonIdsDefault = []

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
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['behavioral']),
                                key: zod.union([zod.string(), zod.number()]),
                                value: zod.string(),
                                event_type: zod.string(),
                                time_value: zod.number().nullish(),
                                time_interval: zod.string().nullish(),
                                negation: zod
                                    .boolean()
                                    .default(
                                        cohortsPartialUpdateResponseFiltersOnePropertiesValuesItemOneNegationDefault
                                    ),
                                operator: zod.string().nullish(),
                                operator_value: zod.number().nullish(),
                                seq_time_interval: zod.string().nullish(),
                                seq_time_value: zod.number().nullish(),
                                seq_event: zod.union([zod.string(), zod.number()]).nullish(),
                                seq_event_type: zod.string().nullish(),
                                total_periods: zod.number().nullish(),
                                min_periods: zod.number().nullish(),
                                event_filters: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.enum(['event', 'element']),
                                                key: zod.string(),
                                                value: zod.unknown(),
                                                operator: zod.string().nullish(),
                                            }),
                                            zod.object({
                                                type: zod.enum(['hogql']),
                                                key: zod.string(),
                                                value: zod.unknown().nullish(),
                                            }),
                                        ])
                                    )
                                    .nullish(),
                                explicit_datetime: zod.string().nullish(),
                            }),
                            zod.object({
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
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
                                bytecode: zod.array(zod.unknown()).nullish(),
                                bytecode_error: zod.string().nullish(),
                                conditionHash: zod.string().nullish(),
                                type: zod.enum(['person']),
                                key: zod.string(),
                                operator: zod.string().nullish(),
                                value: zod.unknown().nullish(),
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
    _create_static_person_ids: zod
        .array(zod.string())
        .default(cohortsPartialUpdateResponseCreateStaticPersonIdsDefault),
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
