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
                .unknown()
                .nullish()
                .describe(
                    'Filters for the cohort. Examples:\n\n        # Behavioral filter (performed event)\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "OR",\n                    "values": [{\n                        "key": "address page viewed",\n                        "type": "behavioral",\n                        "value": "performed_event",\n                        "negation": false,\n                        "event_type": "events",\n                        "time_value": "30",\n                        "time_interval": "day"\n                    }]\n                }]\n            }\n        }\n\n        # Person property filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "promoCodes",\n                        "type": "person",\n                        "value": ["1234567890"],\n                        "negation": false,\n                        "operator": "exact"\n                    }]\n                }]\n            }\n        }\n\n        # Cohort filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "id",\n                        "type": "cohort",\n                        "value": 8814,\n                        "negation": false\n                    }]\n                }]\n            }\n        }'
                ),
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

export const CohortsCreateBody = zod.object({
    name: zod.string().max(cohortsCreateBodyNameMax).nullish(),
    description: zod.string().max(cohortsCreateBodyDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .unknown()
        .nullish()
        .describe(
            'Filters for the cohort. Examples:\n\n        # Behavioral filter (performed event)\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "OR",\n                    "values": [{\n                        "key": "address page viewed",\n                        "type": "behavioral",\n                        "value": "performed_event",\n                        "negation": false,\n                        "event_type": "events",\n                        "time_value": "30",\n                        "time_interval": "day"\n                    }]\n                }]\n            }\n        }\n\n        # Person property filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "promoCodes",\n                        "type": "person",\n                        "value": ["1234567890"],\n                        "negation": false,\n                        "operator": "exact"\n                    }]\n                }]\n            }\n        }\n\n        # Cohort filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "id",\n                        "type": "cohort",\n                        "value": 8814,\n                        "negation": false\n                    }]\n                }]\n            }\n        }'
        ),
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
        .unknown()
        .nullish()
        .describe(
            'Filters for the cohort. Examples:\n\n        # Behavioral filter (performed event)\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "OR",\n                    "values": [{\n                        "key": "address page viewed",\n                        "type": "behavioral",\n                        "value": "performed_event",\n                        "negation": false,\n                        "event_type": "events",\n                        "time_value": "30",\n                        "time_interval": "day"\n                    }]\n                }]\n            }\n        }\n\n        # Person property filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "promoCodes",\n                        "type": "person",\n                        "value": ["1234567890"],\n                        "negation": false,\n                        "operator": "exact"\n                    }]\n                }]\n            }\n        }\n\n        # Cohort filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "id",\n                        "type": "cohort",\n                        "value": 8814,\n                        "negation": false\n                    }]\n                }]\n            }\n        }'
        ),
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

export const CohortsUpdateBody = zod.object({
    name: zod.string().max(cohortsUpdateBodyNameMax).nullish(),
    description: zod.string().max(cohortsUpdateBodyDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .unknown()
        .nullish()
        .describe(
            'Filters for the cohort. Examples:\n\n        # Behavioral filter (performed event)\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "OR",\n                    "values": [{\n                        "key": "address page viewed",\n                        "type": "behavioral",\n                        "value": "performed_event",\n                        "negation": false,\n                        "event_type": "events",\n                        "time_value": "30",\n                        "time_interval": "day"\n                    }]\n                }]\n            }\n        }\n\n        # Person property filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "promoCodes",\n                        "type": "person",\n                        "value": ["1234567890"],\n                        "negation": false,\n                        "operator": "exact"\n                    }]\n                }]\n            }\n        }\n\n        # Cohort filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "id",\n                        "type": "cohort",\n                        "value": 8814,\n                        "negation": false\n                    }]\n                }]\n            }\n        }'
        ),
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
        .unknown()
        .nullish()
        .describe(
            'Filters for the cohort. Examples:\n\n        # Behavioral filter (performed event)\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "OR",\n                    "values": [{\n                        "key": "address page viewed",\n                        "type": "behavioral",\n                        "value": "performed_event",\n                        "negation": false,\n                        "event_type": "events",\n                        "time_value": "30",\n                        "time_interval": "day"\n                    }]\n                }]\n            }\n        }\n\n        # Person property filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "promoCodes",\n                        "type": "person",\n                        "value": ["1234567890"],\n                        "negation": false,\n                        "operator": "exact"\n                    }]\n                }]\n            }\n        }\n\n        # Cohort filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "id",\n                        "type": "cohort",\n                        "value": 8814,\n                        "negation": false\n                    }]\n                }]\n            }\n        }'
        ),
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

export const CohortsPartialUpdateBody = zod.object({
    name: zod.string().max(cohortsPartialUpdateBodyNameMax).nullish(),
    description: zod.string().max(cohortsPartialUpdateBodyDescriptionMax).optional(),
    groups: zod.unknown().optional(),
    deleted: zod.boolean().optional(),
    filters: zod
        .unknown()
        .nullish()
        .describe(
            'Filters for the cohort. Examples:\n\n        # Behavioral filter (performed event)\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "OR",\n                    "values": [{\n                        "key": "address page viewed",\n                        "type": "behavioral",\n                        "value": "performed_event",\n                        "negation": false,\n                        "event_type": "events",\n                        "time_value": "30",\n                        "time_interval": "day"\n                    }]\n                }]\n            }\n        }\n\n        # Person property filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "promoCodes",\n                        "type": "person",\n                        "value": ["1234567890"],\n                        "negation": false,\n                        "operator": "exact"\n                    }]\n                }]\n            }\n        }\n\n        # Cohort filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "id",\n                        "type": "cohort",\n                        "value": 8814,\n                        "negation": false\n                    }]\n                }]\n            }\n        }'
        ),
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
        .unknown()
        .nullish()
        .describe(
            'Filters for the cohort. Examples:\n\n        # Behavioral filter (performed event)\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "OR",\n                    "values": [{\n                        "key": "address page viewed",\n                        "type": "behavioral",\n                        "value": "performed_event",\n                        "negation": false,\n                        "event_type": "events",\n                        "time_value": "30",\n                        "time_interval": "day"\n                    }]\n                }]\n            }\n        }\n\n        # Person property filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "promoCodes",\n                        "type": "person",\n                        "value": ["1234567890"],\n                        "negation": false,\n                        "operator": "exact"\n                    }]\n                }]\n            }\n        }\n\n        # Cohort filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "id",\n                        "type": "cohort",\n                        "value": 8814,\n                        "negation": false\n                    }]\n                }]\n            }\n        }'
        ),
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
