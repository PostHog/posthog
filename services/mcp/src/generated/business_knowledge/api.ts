/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 13 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Read-only access to parsed knowledge documents. Exposes hybrid search
 * (``search``) and a drill-down window (``window``) so an agent (PHAI or
 * MCP) can find and explore business knowledge chunks.
 */
export const BusinessKnowledgeDocumentsWindowListParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this knowledge document.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const BusinessKnowledgeDocumentsWindowListQueryParams = () => zod.object({
    around_ordinal: zod.number().describe('Zero-based chunk ordinal to center the window on (from a search result).'),
    radius: zod
        .number()
        .optional()
        .describe('Number of chunks before and after the center to include. Defaults to 5, clamped to [0, 15].'),
})

/**
 * Read-only access to parsed knowledge documents. Exposes hybrid search
 * (``search``) and a drill-down window (``window``) so an agent (PHAI or
 * MCP) can find and explore business knowledge chunks.
 */
export const BusinessKnowledgeDocumentsSearchListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const BusinessKnowledgeDocumentsSearchListQueryParams = () => zod.object({
    library_id: zod
        .string()
        .optional()
        .describe(
            'Limit retrieval to sources in this library. Pass the same id to repository search and file read. Omit to search every ready source.'
        ),
    limit: zod.number().optional().describe('Maximum number of ranked chunks to return. Defaults to 10, capped at 20.'),
    query: zod
        .string()
        .describe(
            'Natural-language search query. Runs hybrid (semantic + full-text) retrieval over all SAFE, READY knowledge chunks in this project.'
        ),
    rerank: zod
        .boolean()
        .optional()
        .describe(
            'When true, rerank search results with a listwise LLM pass for better relevance. Defaults to false (RRF order only). Falls back to RRF order on rerank failure.'
        ),
})

/**
 * Libraries in this project. The default library is first.
 * @summary List business knowledge libraries
 */
export const BusinessKnowledgeLibrariesListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * @summary Create a business knowledge library
 */
export const BusinessKnowledgeLibrariesCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const businessKnowledgeLibrariesCreateBodyNameMax = 255

export const BusinessKnowledgeLibrariesCreateBody = () => zod.object({
    name: zod.string().max(businessKnowledgeLibrariesCreateBodyNameMax).describe('Name for the new library.'),
})

/**
 * @summary Get a business knowledge library
 */
export const BusinessKnowledgeLibrariesRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Send only the fields you want to change. `source_ids` replaces every source in the library. `repos` replaces this environment's repositories and leaves repositories that only another environment allows.
 * @summary Rename a library or replace its sources and repositories
 */
export const BusinessKnowledgeLibrariesPartialUpdateParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const businessKnowledgeLibrariesPartialUpdateBodyNameMax = 255

export const BusinessKnowledgeLibrariesPartialUpdateBody = () => zod.object({
    name: zod
        .string()
        .max(businessKnowledgeLibrariesPartialUpdateBodyNameMax)
        .optional()
        .describe('New name. Omit to keep the current name.'),
    source_ids: zod
        .array(zod.string())
        .optional()
        .describe(
            'Replaces every source in this library. Omit to leave sources unchanged. An empty list removes them all.'
        ),
    repos: zod
        .array(zod.string())
        .optional()
        .describe(
            "Replaces this environment's repositories in the library. Omit to leave them unchanged. Repositories only another environment allows stay."
        ),
})

/**
 * Removes the library and its links. Sources, documents, and selected repositories stay.
 * @summary Delete a business knowledge library
 */
export const BusinessKnowledgeLibrariesDestroyParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Reads one file whose path is in the cached file list, at the cached commit. The path must come from the repository search.
 * @summary Read a file from a selected GitHub repository
 */
export const BusinessKnowledgeRepositoriesFileRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const BusinessKnowledgeRepositoriesFileRetrieveQueryParams = () => zod.object({
    library_id: zod
        .string()
        .optional()
        .describe(
            'Require the repository to be in this library. Pass the same id used for document search and repository search. Omit to read any selected repository.'
        ),
    path: zod.string().min(1).describe('File path returned by the repository search.'),
    repo: zod.string().min(1).describe('owner\/repo to read. It must already be selected.'),
})

/**
 * Matches file paths and README text in the cached default-branch file list. Pass file names or identifiers, then read a file. Does not search file contents.
 * @summary Search selected GitHub repositories
 */
export const BusinessKnowledgeRepositoriesSearchParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const BusinessKnowledgeRepositoriesSearchQueryParams = () => zod.object({
    library_id: zod
        .string()
        .optional()
        .describe(
            'Limit the search to repositories in this library. Pass the same id to document search and file read. Omit to search every selected repository.'
        ),
    query: zod.string().min(1).describe('File names, path fragments, or identifiers to match. Not a full sentence.'),
    repo: zod
        .string()
        .optional()
        .describe(
            'Limit the search to this owner\/repo. It must already be selected. Omit to search every selected repository.'
        ),
})

export const BusinessKnowledgeSourcesListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const BusinessKnowledgeSourcesListQueryParams = () => zod.object({
    added_by: zod
        .enum(['human', 'learned'])
        .optional()
        .describe('Filter by who added the source: human (you added it) or learned (from a resolved support ticket).'),
    library_id: zod.string().optional().describe('Return only sources in this library. Do not combine with unfiled.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('Case-insensitive substring match against the source name and URL.'),
    source_type: zod
        .enum(['file', 'text', 'url'])
        .optional()
        .describe('Filter to a single source type (text, url, or file).'),
    unfiled: zod
        .boolean()
        .optional()
        .describe('When true, return only sources that are in no library. Do not combine with library_id.'),
})

export const BusinessKnowledgeSourcesCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const businessKnowledgeSourcesCreateBodyNameMax = 255

export const businessKnowledgeSourcesCreateBodyAlwaysIncludeDefault = false

export const BusinessKnowledgeSourcesCreateBody = () => zod.object({
    name: zod
        .string()
        .max(businessKnowledgeSourcesCreateBodyNameMax)
        .describe('Short human label for the source. Shown in the settings list and in agent citations.'),
    text: zod
        .string()
        .describe(
            'Raw text to index. Capped at 1 MB; larger payloads should be split into multiple sources or wait for URL\/file support in Stage 2\/3.'
        ),
    always_include: zod
        .boolean()
        .default(businessKnowledgeSourcesCreateBodyAlwaysIncludeDefault)
        .describe(
            "When true, this source's content is injected into every support reply prompt as general context (tone, policies, direction)."
        ),
})

export const BusinessKnowledgeSourcesRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this knowledge source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const BusinessKnowledgeSourcesPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this knowledge source.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const businessKnowledgeSourcesPartialUpdateBodyNameMax = 255

export const BusinessKnowledgeSourcesPartialUpdateBody = () => zod
    .object({
        name: zod
            .string()
            .max(businessKnowledgeSourcesPartialUpdateBodyNameMax)
            .optional()
            .describe('New human label for the source.'),
        text: zod.string().optional().describe('Replacement text. Omit to keep the existing content.'),
        always_include: zod
            .boolean()
            .optional()
            .describe(
                "When true, this source's content is injected into every support reply prompt as general context."
            ),
        library_ids: zod
            .array(zod.string())
            .optional()
            .describe(
                'Replaces the libraries this source belongs to. Omit to leave membership unchanged. An empty list removes it from every library.'
            ),
    })
    .describe(
        'PATCH payload for text sources. All fields optional, at least one\nrequired. `text` triggers a re-chunk; `name` or `always_include` alone does not.'
    )
