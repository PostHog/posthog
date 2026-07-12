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
    basic: zod
        .boolean()
        .optional()
        .describe(
            'Return a basic payload that omits the heavy `filters`, `query`, and `groups` fields. Useful for pickers that only need id/name/count.'
        ),
    hide_behavioral_cohorts: zod
        .boolean()
        .optional()
        .describe(
            "Set true to exclude behavioral (event-based) cohorts, which can't be used in feature flags or batch workflow audiences."
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod
        .string()
        .optional()
        .describe(
            "Optional. Match against cohort `name`. Returns exact (case-insensitive substring) matches only; if no exact match exists, returns similar (fuzzy trigram — typos, transpositions, prefix-as-you-type) matches instead. Each result's `search_match_type` is `exact` or `similar`. Results are ordered by relevance. When omitted, cohorts are ordered newest-first. Capped at 200 characters; longer queries return a 400 error."
        ),
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

export const cohortsCreateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsCreateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsCreateBodyFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsCreateBodyFiltersOnePropertiesValuesItemFourNegationDefault = false
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
                                    bytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
                                    bytecode_error: zod.union([zod.string(), zod.null()]).optional(),
                                    conditionHash: zod.union([zod.string(), zod.null()]).optional(),
                                    type: zod.literal('behavioral'),
                                    key: zod.union([zod.string(), zod.number()]),
                                    value: zod.string(),
                                    event_type: zod.string(),
                                    time_value: zod.union([zod.number(), zod.null()]).optional(),
                                    time_interval: zod.union([zod.string(), zod.null()]).optional(),
                                    negation: zod
                                        .boolean()
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemOneNegationDefault),
                                    operator: zod.union([zod.string(), zod.null()]).optional(),
                                    operator_value: zod.union([zod.number(), zod.null()]).optional(),
                                    seq_time_interval: zod.union([zod.string(), zod.null()]).optional(),
                                    seq_time_value: zod.union([zod.number(), zod.null()]).optional(),
                                    seq_event: zod.union([zod.string(), zod.number(), zod.null()]).optional(),
                                    seq_event_type: zod.union([zod.string(), zod.null()]).optional(),
                                    total_periods: zod.union([zod.number(), zod.null()]).optional(),
                                    min_periods: zod.union([zod.number(), zod.null()]).optional(),
                                    event_filters: zod
                                        .union([
                                            zod.array(
                                                zod.union([
                                                    zod.object({
                                                        type: zod.enum(['event', 'element']),
                                                        key: zod.string(),
                                                        value: zod.unknown(),
                                                        operator: zod.union([zod.string(), zod.null()]).optional(),
                                                    }),
                                                    zod.object({
                                                        type: zod.literal('hogql'),
                                                        key: zod.string(),
                                                        value: zod.unknown().optional(),
                                                    }),
                                                ])
                                            ),
                                            zod.null(),
                                        ])
                                        .optional(),
                                    explicit_datetime: zod.union([zod.string(), zod.null()]).optional(),
                                    explicit_datetime_to: zod.union([zod.string(), zod.null()]).optional(),
                                }),
                                zod.object({
                                    bytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
                                    bytecode_error: zod.union([zod.string(), zod.null()]).optional(),
                                    conditionHash: zod.union([zod.string(), zod.null()]).optional(),
                                    type: zod.literal('cohort'),
                                    key: zod.literal('id'),
                                    value: zod.number(),
                                    negation: zod
                                        .boolean()
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemTwoNegationDefault),
                                }),
                                zod.object({
                                    operator: zod.union([zod.string(), zod.null()]).optional(),
                                    value: zod.unknown().optional(),
                                    bytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
                                    bytecode_error: zod.union([zod.string(), zod.null()]).optional(),
                                    conditionHash: zod.union([zod.string(), zod.null()]).optional(),
                                    type: zod.literal('person'),
                                    key: zod.string(),
                                    negation: zod
                                        .boolean()
                                        .default(cohortsCreateBodyFiltersOnePropertiesValuesItemThreeNegationDefault),
                                }),
                                zod
                                    .object({
                                        operator: zod.union([zod.string(), zod.null()]).optional(),
                                        value: zod.unknown().optional(),
                                        bytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
                                        bytecode_error: zod.union([zod.string(), zod.null()]).optional(),
                                        conditionHash: zod.union([zod.string(), zod.null()]).optional(),
                                        type: zod.literal('person_metadata'),
                                        key: zod.string(),
                                        negation: zod
                                            .boolean()
                                            .default(
                                                cohortsCreateBodyFiltersOnePropertiesValuesItemFourNegationDefault
                                            ),
                                    })
                                    .describe(
                                        'Filter on a top-level persons-table column (e.g. created_at) rather than the\nproperties JSON. The matching key must be one of PERSON_METADATA_FIELDS.'
                                    ),
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

export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault = false
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemTwoNegationDefault = false
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeNegationDefault = false
export const cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemFourNegationDefault = false

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
                                    bytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
                                    bytecode_error: zod.union([zod.string(), zod.null()]).optional(),
                                    conditionHash: zod.union([zod.string(), zod.null()]).optional(),
                                    type: zod.literal('behavioral'),
                                    key: zod.union([zod.string(), zod.number()]),
                                    value: zod.string(),
                                    event_type: zod.string(),
                                    time_value: zod.union([zod.number(), zod.null()]).optional(),
                                    time_interval: zod.union([zod.string(), zod.null()]).optional(),
                                    negation: zod
                                        .boolean()
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemOneNegationDefault
                                        ),
                                    operator: zod.union([zod.string(), zod.null()]).optional(),
                                    operator_value: zod.union([zod.number(), zod.null()]).optional(),
                                    seq_time_interval: zod.union([zod.string(), zod.null()]).optional(),
                                    seq_time_value: zod.union([zod.number(), zod.null()]).optional(),
                                    seq_event: zod.union([zod.string(), zod.number(), zod.null()]).optional(),
                                    seq_event_type: zod.union([zod.string(), zod.null()]).optional(),
                                    total_periods: zod.union([zod.number(), zod.null()]).optional(),
                                    min_periods: zod.union([zod.number(), zod.null()]).optional(),
                                    event_filters: zod
                                        .union([
                                            zod.array(
                                                zod.union([
                                                    zod.object({
                                                        type: zod.enum(['event', 'element']),
                                                        key: zod.string(),
                                                        value: zod.unknown(),
                                                        operator: zod.union([zod.string(), zod.null()]).optional(),
                                                    }),
                                                    zod.object({
                                                        type: zod.literal('hogql'),
                                                        key: zod.string(),
                                                        value: zod.unknown().optional(),
                                                    }),
                                                ])
                                            ),
                                            zod.null(),
                                        ])
                                        .optional(),
                                    explicit_datetime: zod.union([zod.string(), zod.null()]).optional(),
                                    explicit_datetime_to: zod.union([zod.string(), zod.null()]).optional(),
                                }),
                                zod.object({
                                    bytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
                                    bytecode_error: zod.union([zod.string(), zod.null()]).optional(),
                                    conditionHash: zod.union([zod.string(), zod.null()]).optional(),
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
                                    operator: zod.union([zod.string(), zod.null()]).optional(),
                                    value: zod.unknown().optional(),
                                    bytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
                                    bytecode_error: zod.union([zod.string(), zod.null()]).optional(),
                                    conditionHash: zod.union([zod.string(), zod.null()]).optional(),
                                    type: zod.literal('person'),
                                    key: zod.string(),
                                    negation: zod
                                        .boolean()
                                        .default(
                                            cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemThreeNegationDefault
                                        ),
                                }),
                                zod
                                    .object({
                                        operator: zod.union([zod.string(), zod.null()]).optional(),
                                        value: zod.unknown().optional(),
                                        bytecode: zod.union([zod.array(zod.unknown()), zod.null()]).optional(),
                                        bytecode_error: zod.union([zod.string(), zod.null()]).optional(),
                                        conditionHash: zod.union([zod.string(), zod.null()]).optional(),
                                        type: zod.literal('person_metadata'),
                                        key: zod.string(),
                                        negation: zod
                                            .boolean()
                                            .default(
                                                cohortsPartialUpdateBodyFiltersOnePropertiesValuesItemFourNegationDefault
                                            ),
                                    })
                                    .describe(
                                        'Filter on a top-level persons-table column (e.g. created_at) rather than the\nproperties JSON. The matching key must be one of PERSON_METADATA_FIELDS.'
                                    ),
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
