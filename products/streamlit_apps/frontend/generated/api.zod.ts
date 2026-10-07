/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * @summary Create a streamlit app
 */
export const StreamlitAppsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().describe('Name of the app.'),
    description: zod.string().optional().describe('Optional description of the app.'),
    cpu_cores: zod.number().optional().describe('CPU cores allocated to the sandbox.'),
    memory_gb: zod.number().optional().describe('Memory in GB allocated to the sandbox.'),
})

/**
 * @summary Update a streamlit app
 */
export const StreamlitAppsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().optional().describe('New name for the app.'),
    description: zod.string().optional().describe('New description for the app.'),
    cpu_cores: zod.number().optional().describe('New CPU core allocation for the sandbox.'),
    memory_gb: zod.number().optional().describe('New memory (GB) allocation for the sandbox.'),
})

/**
 * @summary Partially update a streamlit app
 */
export const StreamlitAppsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().optional().describe('New name for the app.'),
    description: zod.string().optional().describe('New description for the app.'),
    cpu_cores: zod.number().optional().describe('New CPU core allocation for the sandbox.'),
    memory_gb: zod.number().optional().describe('New memory (GB) allocation for the sandbox.'),
})

/**
 * @summary Activate an existing app version
 */
export const StreamlitAppsActivateVersionCreateBody = /* @__PURE__ */ zod.object({
    version_number: zod
        .number()
        .describe('Version number to activate. Must reference an existing version of this app.'),
})

/**
 * @summary Create an app version from source code
 */
export const streamlitAppsCreateVersionFromSourceCreateBodySourceMax = 1048576

export const streamlitAppsCreateVersionFromSourceCreateBodyFilesMaxOne = 1048576

export const streamlitAppsCreateVersionFromSourceCreateBodyAssetsMaxOne = 13981016

export const StreamlitAppsCreateVersionFromSourceCreateBody = /* @__PURE__ */ zod.object({
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

export const streamlitAppsEditSourceCreateBodyCreateFilesMaxOne = 1048576

export const StreamlitAppsEditSourceCreateBody = /* @__PURE__ */ zod.object({
    base_version: zod
        .number()
        .min(1)
        .describe(
            'Version number that the changes apply to. Must be the latest version of the app, otherwise the request fails with 409 and returns the current version number.'
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
 * @summary Upload a new app version
 */
export const StreamlitAppsUploadVersionCreateBody = /* @__PURE__ */ zod.object({
    file: zod.url().describe('Zip archive containing the Streamlit app sources (max 10 MB).'),
})
