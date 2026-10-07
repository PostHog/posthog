/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 12 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * @summary List streamlit apps
 */
export const StreamlitAppsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StreamlitAppsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * @summary Create a streamlit app
 */
export const StreamlitAppsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const StreamlitAppsCreateBody = () => zod.object({
    name: zod.string().describe('Name of the app.'),
    description: zod.string().optional().describe('Optional description of the app.'),
    cpu_cores: zod.number().optional().describe('CPU cores allocated to the sandbox.'),
    memory_gb: zod.number().optional().describe('Memory in GB allocated to the sandbox.'),
})

/**
 * @summary Retrieve a streamlit app
 */
export const StreamlitAppsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * @summary Partially update a streamlit app
 */
export const StreamlitAppsPartialUpdateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const StreamlitAppsPartialUpdateBody = () => zod.object({
    name: zod.string().optional().describe('New name for the app.'),
    description: zod.string().optional().describe('New description for the app.'),
    cpu_cores: zod.number().optional().describe('New CPU core allocation for the sandbox.'),
    memory_gb: zod.number().optional().describe('New memory (GB) allocation for the sandbox.'),
})

/**
 * @summary Delete a streamlit app
 */
export const StreamlitAppsDestroyParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * @summary Create an app version from source code
 */
export const StreamlitAppsCreateVersionFromSourceCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const streamlitAppsCreateVersionFromSourceCreateBodySourceMax = 1048576

export const streamlitAppsCreateVersionFromSourceCreateBodyFilesMaxOne = 1048576

export const streamlitAppsCreateVersionFromSourceCreateBodyAssetsMaxOne = 13981016

export const StreamlitAppsCreateVersionFromSourceCreateBody = () => zod.object({
    source: zod
        .string()
        .max(streamlitAppsCreateVersionFromSourceCreateBodySourceMax)
        .describe(
            "Full Python source for the Streamlit app's root app.py file, as free text (max 1 MB). Becomes a new version and is set as the active version."
        ),
    files: zod
        .record(zod.string(), zod.string().max(streamlitAppsCreateVersionFromSourceCreateBodyFilesMaxOne))
        .optional()
        .describe(
            "Extra text files to ship next to app.py, keyed by project-relative path (for example 'utils.py' or 'data\/config.json'), each as plain text (max 1 MB)."
        ),
    assets: zod
        .record(zod.string(), zod.string().max(streamlitAppsCreateVersionFromSourceCreateBodyAssetsMaxOne))
        .optional()
        .describe(
            "Extra binary files to ship next to app.py, keyed by project-relative path (for example 'data\/events.parquet'), each as standard base64 text."
        ),
})

/**
 * Applies exact text edits, file creations, and file deletions to base_version, then stores the result as a new active version. Files that no change touches stay byte-for-byte the same.
 * @summary Create an app version by editing an existing version
 */
export const StreamlitAppsEditSourceCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const streamlitAppsEditSourceCreateBodyCreateFilesMaxOne = 1048576

export const StreamlitAppsEditSourceCreateBody = () => zod.object({
    base_version: zod
        .number()
        .min(1)
        .describe(
            'Version number that the changes apply to. Must be the active version of the app, otherwise the request fails with 409 and returns the active version number.'
        ),
    file_edits: zod
        .array(
            zod.object({
                path: zod.string().describe("Path of an existing text file in the base version, for example 'app.py'."),
                edits: zod
                    .array(
                        zod.object({
                            old: zod.string().describe('Exact text to find in the file. Must match exactly once.'),
                            new: zod.string().describe('Replacement text.'),
                        })
                    )
                    .describe(
                        "Find-and-replace operations, applied in order to the file's text. At most 100 edits per request across all files."
                    ),
            })
        )
        .optional()
        .describe('Exact text edits to existing text files. Files that no change touches stay byte-for-byte the same.'),
    create_files: zod
        .record(zod.string(), zod.string().max(streamlitAppsEditSourceCreateBodyCreateFilesMaxOne))
        .optional()
        .describe(
            "New text files keyed by project-relative path, each value the file's full text (max 1 MB). The path must not exist in the base version."
        ),
    delete_files: zod
        .array(zod.string())
        .optional()
        .describe('Paths of files to remove from the base version. app.py cannot be removed.'),
})

/**
 * Returns the file manifest of a version and the text of each text file. Binary files appear in the manifest without content.
 * @summary Read the source of an app version
 */
export const StreamlitAppsSourceRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

export const StreamlitAppsSourceRetrieveQueryParams = () => zod.object({
    paths: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Comma-separated file paths whose content to return, for example 'app.py,utils.py'. Other files appear in the manifest without content. Defaults to all text files."
        ),
    version_number: zod.number().min(1).optional().describe('Version number to read. Defaults to the active version.'),
})

/**
 * @summary Start the app sandbox
 */
export const StreamlitAppsStartCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * @summary Get app sandbox status
 */
export const StreamlitAppsStatusRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * @summary Stop the app sandbox
 */
export const StreamlitAppsStopCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})

/**
 * @summary List app versions
 */
export const StreamlitAppsVersionsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    short_id: zod.string(),
})
