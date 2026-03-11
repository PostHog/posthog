/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 7 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Create a new evaluation run.

This endpoint validates the request and enqueues a Temporal workflow
to asynchronously execute the evaluation.
 */
export const EvaluationRunsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EvaluationRunsCreateBody = zod.object({
    evaluation_id: zod.string().describe('UUID of the evaluation to run.'),
    target_event_id: zod.string().describe('UUID of the $ai_generation event to evaluate.'),
    timestamp: zod
        .string()
        .datetime({})
        .describe('ISO 8601 timestamp of the target event (needed for efficient ClickHouse lookup).'),
    event: zod.string().describe('Event name. Use "$ai_generation" for LLM generation events.'),
    distinct_id: zod.string().nullish().describe('Distinct ID of the event (optional, improves lookup performance).'),
})

export const EvaluationsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EvaluationsListQueryParams = zod.object({
    enabled: zod.boolean().optional().describe('Filter by enabled status'),
    id__in: zod.array(zod.string()).optional().describe('Multiple values may be separated by commas.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .array(zod.enum(['-created_at', '-name', '-updated_at', 'created_at', 'name', 'updated_at']))
        .optional()
        .describe(
            'Ordering\n\n* `created_at` - Created At\n* `-created_at` - Created At (descending)\n* `updated_at` - Updated At\n* `-updated_at` - Updated At (descending)\n* `name` - Name\n* `-name` - Name (descending)'
        ),
    search: zod.string().optional().describe('Search in name or description'),
})

export const evaluationsListResponseResultsItemNameMax = 400

export const evaluationsListResponseResultsItemModelConfigurationOneModelMax = 100

export const evaluationsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const evaluationsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const evaluationsListResponseResultsItemCreatedByOneLastNameMax = 150

export const evaluationsListResponseResultsItemCreatedByOneEmailMax = 254

export const EvaluationsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string(),
            name: zod.string().max(evaluationsListResponseResultsItemNameMax),
            description: zod.string().optional(),
            enabled: zod.boolean().optional(),
            evaluation_type: zod.enum(['llm_judge', 'hog']).describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog'),
            evaluation_config: zod.unknown().optional(),
            output_type: zod.enum(['boolean']).describe('* `boolean` - Boolean (Pass/Fail)'),
            output_config: zod.unknown().optional(),
            conditions: zod.unknown().optional(),
            model_configuration: zod
                .object({
                    provider: zod
                        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                        .describe(
                            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                        ),
                    model: zod.string().max(evaluationsListResponseResultsItemModelConfigurationOneModelMax),
                    provider_key_id: zod.string().nullish(),
                    provider_key_name: zod.string().nullable(),
                })
                .describe('Nested serializer for model configuration.')
                .nullish(),
            created_at: zod.string().datetime({}),
            updated_at: zod.string().datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.string(),
                distinct_id: zod.string().max(evaluationsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(evaluationsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(evaluationsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.string().email().max(evaluationsListResponseResultsItemCreatedByOneEmailMax),
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
            deleted: zod.boolean().optional(),
        })
    ),
})

export const EvaluationsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const evaluationsCreateBodyNameMax = 400

export const evaluationsCreateBodyModelConfigurationOneModelMax = 100

export const EvaluationsCreateBody = zod.object({
    name: zod.string().max(evaluationsCreateBodyNameMax),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    evaluation_type: zod.enum(['llm_judge', 'hog']).describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog'),
    evaluation_config: zod.unknown().optional(),
    output_type: zod.enum(['boolean']).describe('* `boolean` - Boolean (Pass/Fail)'),
    output_config: zod.unknown().optional(),
    conditions: zod.unknown().optional(),
    model_configuration: zod
        .object({
            provider: zod
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                ),
            model: zod.string().max(evaluationsCreateBodyModelConfigurationOneModelMax),
            provider_key_id: zod.string().nullish(),
            provider_key_name: zod.string().nullable(),
        })
        .describe('Nested serializer for model configuration.')
        .nullish(),
    deleted: zod.boolean().optional(),
})

export const EvaluationsRetrieveParams = zod.object({
    id: zod.string().describe('A UUID string identifying this evaluation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const evaluationsRetrieveResponseNameMax = 400

export const evaluationsRetrieveResponseModelConfigurationOneModelMax = 100

export const evaluationsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const evaluationsRetrieveResponseCreatedByOneFirstNameMax = 150

export const evaluationsRetrieveResponseCreatedByOneLastNameMax = 150

export const evaluationsRetrieveResponseCreatedByOneEmailMax = 254

export const EvaluationsRetrieveResponse = zod.object({
    id: zod.string(),
    name: zod.string().max(evaluationsRetrieveResponseNameMax),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    evaluation_type: zod.enum(['llm_judge', 'hog']).describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog'),
    evaluation_config: zod.unknown().optional(),
    output_type: zod.enum(['boolean']).describe('* `boolean` - Boolean (Pass/Fail)'),
    output_config: zod.unknown().optional(),
    conditions: zod.unknown().optional(),
    model_configuration: zod
        .object({
            provider: zod
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                ),
            model: zod.string().max(evaluationsRetrieveResponseModelConfigurationOneModelMax),
            provider_key_id: zod.string().nullish(),
            provider_key_name: zod.string().nullable(),
        })
        .describe('Nested serializer for model configuration.')
        .nullish(),
    created_at: zod.string().datetime({}),
    updated_at: zod.string().datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.string(),
        distinct_id: zod.string().max(evaluationsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(evaluationsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(evaluationsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.string().email().max(evaluationsRetrieveResponseCreatedByOneEmailMax),
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
    deleted: zod.boolean().optional(),
})

export const EvaluationsUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this evaluation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const evaluationsUpdateBodyNameMax = 400

export const evaluationsUpdateBodyModelConfigurationOneModelMax = 100

export const EvaluationsUpdateBody = zod.object({
    name: zod.string().max(evaluationsUpdateBodyNameMax),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    evaluation_type: zod.enum(['llm_judge', 'hog']).describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog'),
    evaluation_config: zod.unknown().optional(),
    output_type: zod.enum(['boolean']).describe('* `boolean` - Boolean (Pass/Fail)'),
    output_config: zod.unknown().optional(),
    conditions: zod.unknown().optional(),
    model_configuration: zod
        .object({
            provider: zod
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                ),
            model: zod.string().max(evaluationsUpdateBodyModelConfigurationOneModelMax),
            provider_key_id: zod.string().nullish(),
            provider_key_name: zod.string().nullable(),
        })
        .describe('Nested serializer for model configuration.')
        .nullish(),
    deleted: zod.boolean().optional(),
})

export const evaluationsUpdateResponseNameMax = 400

export const evaluationsUpdateResponseModelConfigurationOneModelMax = 100

export const evaluationsUpdateResponseCreatedByOneDistinctIdMax = 200

export const evaluationsUpdateResponseCreatedByOneFirstNameMax = 150

export const evaluationsUpdateResponseCreatedByOneLastNameMax = 150

export const evaluationsUpdateResponseCreatedByOneEmailMax = 254

export const EvaluationsUpdateResponse = zod.object({
    id: zod.string(),
    name: zod.string().max(evaluationsUpdateResponseNameMax),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    evaluation_type: zod.enum(['llm_judge', 'hog']).describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog'),
    evaluation_config: zod.unknown().optional(),
    output_type: zod.enum(['boolean']).describe('* `boolean` - Boolean (Pass/Fail)'),
    output_config: zod.unknown().optional(),
    conditions: zod.unknown().optional(),
    model_configuration: zod
        .object({
            provider: zod
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                ),
            model: zod.string().max(evaluationsUpdateResponseModelConfigurationOneModelMax),
            provider_key_id: zod.string().nullish(),
            provider_key_name: zod.string().nullable(),
        })
        .describe('Nested serializer for model configuration.')
        .nullish(),
    created_at: zod.string().datetime({}),
    updated_at: zod.string().datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.string(),
        distinct_id: zod.string().max(evaluationsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(evaluationsUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(evaluationsUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.string().email().max(evaluationsUpdateResponseCreatedByOneEmailMax),
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
    deleted: zod.boolean().optional(),
})

export const EvaluationsPartialUpdateParams = zod.object({
    id: zod.string().describe('A UUID string identifying this evaluation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const evaluationsPartialUpdateBodyNameMax = 400

export const evaluationsPartialUpdateBodyModelConfigurationOneModelMax = 100

export const EvaluationsPartialUpdateBody = zod.object({
    name: zod.string().max(evaluationsPartialUpdateBodyNameMax).optional(),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    evaluation_type: zod
        .enum(['llm_judge', 'hog'])
        .optional()
        .describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog'),
    evaluation_config: zod.unknown().optional(),
    output_type: zod.enum(['boolean']).optional().describe('* `boolean` - Boolean (Pass/Fail)'),
    output_config: zod.unknown().optional(),
    conditions: zod.unknown().optional(),
    model_configuration: zod
        .object({
            provider: zod
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                ),
            model: zod.string().max(evaluationsPartialUpdateBodyModelConfigurationOneModelMax),
            provider_key_id: zod.string().nullish(),
            provider_key_name: zod.string().nullable(),
        })
        .describe('Nested serializer for model configuration.')
        .nullish(),
    deleted: zod.boolean().optional(),
})

export const evaluationsPartialUpdateResponseNameMax = 400

export const evaluationsPartialUpdateResponseModelConfigurationOneModelMax = 100

export const evaluationsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const evaluationsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const evaluationsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const evaluationsPartialUpdateResponseCreatedByOneEmailMax = 254

export const EvaluationsPartialUpdateResponse = zod.object({
    id: zod.string(),
    name: zod.string().max(evaluationsPartialUpdateResponseNameMax),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    evaluation_type: zod.enum(['llm_judge', 'hog']).describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog'),
    evaluation_config: zod.unknown().optional(),
    output_type: zod.enum(['boolean']).describe('* `boolean` - Boolean (Pass/Fail)'),
    output_config: zod.unknown().optional(),
    conditions: zod.unknown().optional(),
    model_configuration: zod
        .object({
            provider: zod
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                ),
            model: zod.string().max(evaluationsPartialUpdateResponseModelConfigurationOneModelMax),
            provider_key_id: zod.string().nullish(),
            provider_key_name: zod.string().nullable(),
        })
        .describe('Nested serializer for model configuration.')
        .nullish(),
    created_at: zod.string().datetime({}),
    updated_at: zod.string().datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.string(),
        distinct_id: zod.string().max(evaluationsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(evaluationsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(evaluationsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.string().email().max(evaluationsPartialUpdateResponseCreatedByOneEmailMax),
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
    deleted: zod.boolean().optional(),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const EvaluationsDestroyParams = zod.object({
    id: zod.string().describe('A UUID string identifying this evaluation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
