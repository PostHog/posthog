/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 4 ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const LlmPromptsListParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmPromptsListQueryParams = zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('Optional substring filter applied to prompt names and prompt content.'),
})

export const llmPromptsListResponseResultsItemNameMax = 255

export const llmPromptsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const llmPromptsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const llmPromptsListResponseResultsItemCreatedByOneLastNameMax = 150

export const llmPromptsListResponseResultsItemCreatedByOneEmailMax = 254

export const LlmPromptsListResponse = zod.object({
    count: zod.number(),
    next: zod.string().url().nullish(),
    previous: zod.string().url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.string().optional(),
            name: zod
                .string()
                .max(llmPromptsListResponseResultsItemNameMax)
                .describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
            prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
            version: zod.number().optional(),
            created_by: zod
                .object({
                    id: zod.number().optional(),
                    uuid: zod.string().optional(),
                    distinct_id: zod.string().max(llmPromptsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                    first_name: zod.string().max(llmPromptsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                    last_name: zod.string().max(llmPromptsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                    email: zod.string().email().max(llmPromptsListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
                })
                .optional(),
            created_at: zod.string().datetime({}).optional(),
            updated_at: zod.string().datetime({}).optional(),
            deleted: zod.boolean().optional(),
            is_latest: zod.boolean().optional(),
            latest_version: zod.number().optional(),
            version_count: zod.number().optional(),
            first_version_created_at: zod.string().optional(),
        })
    ),
})

export const LlmPromptsCreateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmPromptsCreateBodyNameMax = 255

export const LlmPromptsCreateBody = zod.object({
    name: zod
        .string()
        .max(llmPromptsCreateBodyNameMax)
        .describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
    prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
})

export const llmPromptsNameRetrievePathPromptNameRegExp = new RegExp('^[^/]+$')

export const LlmPromptsNameRetrieveParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    prompt_name: zod.string().regex(llmPromptsNameRetrievePathPromptNameRegExp),
})

export const LlmPromptsNameRetrieveQueryParams = zod.object({
    version: zod
        .number()
        .min(1)
        .optional()
        .describe('Specific prompt version to fetch. If omitted, the latest version is returned.'),
})

export const LlmPromptsNameRetrieveResponse = zod.object({
    id: zod.string(),
    name: zod.string(),
    prompt: zod.unknown(),
    version: zod.number(),
    created_at: zod.string().datetime({}),
    updated_at: zod.string().datetime({}),
    deleted: zod.boolean(),
    is_latest: zod.boolean(),
    latest_version: zod.number(),
    version_count: zod.number(),
    first_version_created_at: zod.string().datetime({}),
})

export const llmPromptsNamePartialUpdatePathPromptNameRegExp = new RegExp('^[^/]+$')

export const LlmPromptsNamePartialUpdateParams = zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    prompt_name: zod.string().regex(llmPromptsNamePartialUpdatePathPromptNameRegExp),
})

export const LlmPromptsNamePartialUpdateBody = zod.object({
    prompt: zod.unknown().optional().describe('Prompt payload to publish as a new version.'),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe('Latest version you are editing from. Used for optimistic concurrency checks.'),
})

export const llmPromptsNamePartialUpdateResponseNameMax = 255

export const llmPromptsNamePartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const llmPromptsNamePartialUpdateResponseCreatedByOneFirstNameMax = 150

export const llmPromptsNamePartialUpdateResponseCreatedByOneLastNameMax = 150

export const llmPromptsNamePartialUpdateResponseCreatedByOneEmailMax = 254

export const LlmPromptsNamePartialUpdateResponse = zod.object({
    id: zod.string().optional(),
    name: zod
        .string()
        .max(llmPromptsNamePartialUpdateResponseNameMax)
        .describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
    prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
    version: zod.number().optional(),
    created_by: zod
        .object({
            id: zod.number().optional(),
            uuid: zod.string().optional(),
            distinct_id: zod.string().max(llmPromptsNamePartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(llmPromptsNamePartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(llmPromptsNamePartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.string().email().max(llmPromptsNamePartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
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
        })
        .optional(),
    created_at: zod.string().datetime({}).optional(),
    updated_at: zod.string().datetime({}).optional(),
    deleted: zod.boolean().optional(),
    is_latest: zod.boolean().optional(),
    latest_version: zod.number().optional(),
    version_count: zod.number().optional(),
    first_version_created_at: zod.string().optional(),
})
