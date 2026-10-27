/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 9 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Lists the project's AEO prompt set, ordered by topic and then rank, one page at a time. Filter by topic or by on/off state. Archived prompts are left out unless include_archived is true. Each prompt carries its latest check per answer engine.
 * @summary List AEO prompts
 */
export const AeoPromptsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoPromptsListQueryIncludeArchivedDefault = false
export const aeoPromptsListQueryTopicMax = 200

export const AeoPromptsListQueryParams = () => zod.object({
    active: zod.boolean().nullish().describe('Only list prompts that are on (true) or off (false). Omit to list both.'),
    include_archived: zod
        .boolean()
        .default(aeoPromptsListQueryIncludeArchivedDefault)
        .describe('Also list archived prompts. Archived prompts are left out by default.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    topic: zod
        .string()
        .max(aeoPromptsListQueryTopicMax)
        .optional()
        .describe('Only list prompts with this topic. An empty value lists the prompts that have no topic.'),
})

/**
 * Gets one prompt from the project's AEO prompt set, archived ones included, with its latest check per answer engine.
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
 * Turns a prompt on or off, changes its topic, archives or restores it, or changes its text. A text change adds the next version and makes it current, and current_version moves back to an earlier one. The prompt keeps its id, and past checks are always kept.
 * @summary Update an AEO prompt
 */
export const AeoPromptsPartialUpdateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const aeoPromptsPartialUpdateBodyTopicMax = 200

export const aeoPromptsPartialUpdateBodyPromptMax = 10000

export const aeoPromptsPartialUpdateBodyVersionDescriptionMax = 400

export const AeoPromptsPartialUpdateBody = () => zod.object({
    active: zod.boolean().nullish().describe('Turn the prompt on or off for future runs.'),
    topic: zod
        .string()
        .max(aeoPromptsPartialUpdateBodyTopicMax)
        .optional()
        .describe(
            'New topic for the prompt. An empty string removes the topic. Past checks keep the topic they ran with.'
        ),
    prompt: zod
        .string()
        .max(aeoPromptsPartialUpdateBodyPromptMax)
        .optional()
        .describe(
            'New text for the prompt. A change adds the next version and makes it current; the prompt keeps its id and its check history, and each check records the version that ran. A change of case or whitespace only adds no version. Fails with 409 when another prompt in the set already has the text.'
        ),
    version_description: zod
        .string()
        .max(aeoPromptsPartialUpdateBodyVersionDescriptionMax)
        .optional()
        .describe("Optional note on what the text change does, stored on the new version. Send it with 'prompt'."),
    current_version: zod
        .number()
        .min(1)
        .nullish()
        .describe(
            'Make an existing version current again, for example to roll back a text change. Adds no version. Fails with 400 when the version does not exist, and with 409 when another prompt has its text.'
        ),
    archived: zod
        .boolean()
        .nullish()
        .describe(
            "True archives the prompt: it is turned off, never runs again, and keeps its check history. Send it without other fields. False restores an archived prompt. A restored prompt stays off unless 'active' is true in the same request. An archived prompt accepts no other change until it is restored."
        ),
})

/**
 * Archives a prompt: it is turned off and never runs again. Nothing is deleted, and its versions and checks are kept. Restore it with a PATCH of archived=false.
 * @summary Archive an AEO prompt
 */
export const AeoPromptsDestroyParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Lists every check of one prompt, newest first, one page at a time. Filter by engine or by prompt version. Each check has the engine's answer, the URLs it cited, the searches it ran and the prompt version it ran.
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
    version: zod.number().min(1).optional().describe('Only list checks that ran this version of the prompt.'),
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
 * Lists every version of a prompt's text, newest first. A text edit adds a version, and one of them is current.
 * @summary List an AEO prompt's versions
 */
export const AeoPromptsVersionsParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Adds prompts to the project's AEO prompt set, or updates the topic and visibility of prompts that already exist. Existing prompts keep their active state. Prompts whose text matches an archived prompt are skipped.
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
