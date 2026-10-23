/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 7 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Lists the project's AEO prompt set, ordered by topic and then rank, one page at a time. Filter by topic or by on/off state. Each prompt carries its latest check per answer engine.
 * @summary List AEO prompts
 */
export const AeoPromptsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoPromptsListQueryTopicMax = 200

export const AeoPromptsListQueryParams = () => zod.object({
    active: zod.boolean().nullish().describe('Only list prompts that are on (true) or off (false). Omit to list both.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    topic: zod
        .string()
        .max(aeoPromptsListQueryTopicMax)
        .optional()
        .describe('Only list prompts with this topic. An empty value lists the prompts that have no topic.'),
})

/**
 * Gets one prompt from the project's AEO prompt set, with its latest check per answer engine.
 * @summary Get an AEO prompt
 */
export const AeoPromptsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Turns a prompt on or off. Only active prompts run against the answer engines. Past checks are kept either way.
 * @summary Turn an AEO prompt on or off
 */
export const AeoPromptsPartialUpdateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const AeoPromptsPartialUpdateBody = () => zod.object({
    active: zod.boolean().optional().describe('Turn the prompt on or off for future runs.'),
})

/**
 * Lists every check of one prompt, newest first, one page at a time. Each check has the engine's answer, the URLs it cited and the searches it ran.
 * @summary List an AEO prompt's checks
 */
export const AeoPromptsChecksParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoPromptsChecksQueryEngineMax = 64

export const AeoPromptsChecksQueryParams = () => zod.object({
    engine: zod
        .string()
        .min(1)
        .max(aeoPromptsChecksQueryEngineMax)
        .optional()
        .describe("Only list checks from this answer engine, for example 'claude-web-search'."),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Gets citation totals per answer engine for one prompt, plus per-day counts for the last 30 days in the project's timezone.
 * @summary Get an AEO prompt's citation stats
 */
export const AeoPromptsStatsParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Adds prompts to the project's AEO prompt set, or updates the topic and visibility of prompts that already exist. Existing prompts keep their active state.
 * @summary Import AEO prompts
 */
export const AeoPromptsBulkImportParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoPromptsBulkImportBodyPromptsItemPromptMax = 10000

export const aeoPromptsBulkImportBodyPromptsItemTopicMax = 200

export const aeoPromptsBulkImportBodyPromptsItemExternalVisibilityMin = 0
export const aeoPromptsBulkImportBodyPromptsItemExternalVisibilityMax = 100

export const aeoPromptsBulkImportBodyPromptsMax = 2000

export const AeoPromptsBulkImportBody = () => zod.object({
    prompts: zod
        .array(
            zod.object({
                prompt: zod
                    .string()
                    .max(aeoPromptsBulkImportBodyPromptsItemPromptMax)
                    .describe(
                        'The question to ask the answer engines, as a user would phrase it. Matching ignores case and whitespace, so a re-import updates the existing prompt.'
                    ),
                topic: zod
                    .string()
                    .max(aeoPromptsBulkImportBodyPromptsItemTopicMax)
                    .optional()
                    .describe('Theme the prompt belongs to. The runner alternates between topics on each run.'),
                external_visibility: zod
                    .number()
                    .min(aeoPromptsBulkImportBodyPromptsItemExternalVisibilityMin)
                    .max(aeoPromptsBulkImportBodyPromptsItemExternalVisibilityMax)
                    .nullish()
                    .describe(
                        'Share of answers (0-100) that mention the brand for this prompt, as reported by the tool the prompt set came from. Kept to benchmark against our own citation rate.'
                    ),
            })
        )
        .min(1)
        .max(aeoPromptsBulkImportBodyPromptsMax)
        .describe('Prompts to add or update, at most 2000 per request.'),
})

/**
 * Lists the topics in the project's AEO prompt set, with the number of prompts in each.
 * @summary List AEO prompt topics
 */
export const AeoPromptsTopicsParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})
