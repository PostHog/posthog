/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const StreamlitAppUserInfoApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().nullable(),
    first_name: zod.string(),
    last_name: zod.string(),
    email: zod.string(),
    is_email_verified: zod.boolean().nullable(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.string().nullable(),
})

export type StreamlitAppUserInfoApi = zod.input<typeof StreamlitAppUserInfoApi>
export type StreamlitAppUserInfoApiOutput = zod.output<typeof StreamlitAppUserInfoApi>

export const AppSummaryContractApi = zod.object({
    created_by: zod.union([StreamlitAppUserInfoApi, zod.null()]).optional().describe('User who created this app.'),
    id: zod.uuid(),
    short_id: zod.string(),
    name: zod.string(),
    description: zod.string(),
    cpu_cores: zod.number(),
    memory_gb: zod.number(),
    status: zod.string(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type AppSummaryContractApi = zod.input<typeof AppSummaryContractApi>
export type AppSummaryContractApiOutput = zod.output<typeof AppSummaryContractApi>

export const PaginatedAppSummaryContractListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(AppSummaryContractApi),
})

export type PaginatedAppSummaryContractListApi = zod.input<typeof PaginatedAppSummaryContractListApi>
export type PaginatedAppSummaryContractListApiOutput = zod.output<typeof PaginatedAppSummaryContractListApi>

export const CreateAppInputApi = zod.object({
    name: zod.string().describe('Name of the app.'),
    description: zod.string().optional().describe('Optional description of the app.'),
    cpu_cores: zod.number().optional().describe('CPU cores allocated to the sandbox.'),
    memory_gb: zod.number().optional().describe('Memory in GB allocated to the sandbox.'),
})

export type CreateAppInputApi = zod.input<typeof CreateAppInputApi>
export type CreateAppInputApiOutput = zod.output<typeof CreateAppInputApi>

export const AppVersionContractApi = zod.object({
    created_by: zod.union([StreamlitAppUserInfoApi, zod.null()]).optional().describe('User who uploaded this version.'),
    id: zod.uuid(),
    version_number: zod.number(),
    zip_hash: zod.string(),
    snapshot_id: zod.string().nullable(),
    created_at: zod.iso.datetime({ offset: true }),
})

export type AppVersionContractApi = zod.input<typeof AppVersionContractApi>
export type AppVersionContractApiOutput = zod.output<typeof AppVersionContractApi>

export const AppSandboxContractApi = zod.object({
    status: zod.string(),
    restart_count: zod.number(),
    last_error: zod.string(),
    started_at: zod.iso.datetime({ offset: true }).nullable(),
    last_activity_at: zod.iso.datetime({ offset: true }).nullable(),
    version_number: zod.number().nullable(),
})

export type AppSandboxContractApi = zod.input<typeof AppSandboxContractApi>
export type AppSandboxContractApiOutput = zod.output<typeof AppSandboxContractApi>

export const AppContractApi = zod.object({
    created_by: zod.union([StreamlitAppUserInfoApi, zod.null()]).optional().describe('User who created this app.'),
    active_version: zod
        .union([AppVersionContractApi, zod.null()])
        .optional()
        .describe('Currently active version, or null if none uploaded yet.'),
    sandbox: zod
        .union([AppSandboxContractApi, zod.null()])
        .optional()
        .describe('Current sandbox state, or null if the app has never started.'),
    id: zod.uuid(),
    short_id: zod.string(),
    name: zod.string(),
    description: zod.string(),
    cpu_cores: zod.number(),
    memory_gb: zod.number(),
    status: zod.string(),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }),
})

export type AppContractApi = zod.input<typeof AppContractApi>
export type AppContractApiOutput = zod.output<typeof AppContractApi>

export const UpdateAppInputApi = zod.object({
    name: zod.string().optional().describe('New name for the app.'),
    description: zod.string().optional().describe('New description for the app.'),
    cpu_cores: zod.number().optional().describe('New CPU core allocation for the sandbox.'),
    memory_gb: zod.number().optional().describe('New memory (GB) allocation for the sandbox.'),
})

export type UpdateAppInputApi = zod.input<typeof UpdateAppInputApi>
export type UpdateAppInputApiOutput = zod.output<typeof UpdateAppInputApi>

export const PatchedUpdateAppInputApi = zod.object({
    name: zod.string().optional().describe('New name for the app.'),
    description: zod.string().optional().describe('New description for the app.'),
    cpu_cores: zod.number().optional().describe('New CPU core allocation for the sandbox.'),
    memory_gb: zod.number().optional().describe('New memory (GB) allocation for the sandbox.'),
})

export type PatchedUpdateAppInputApi = zod.input<typeof PatchedUpdateAppInputApi>
export type PatchedUpdateAppInputApiOutput = zod.output<typeof PatchedUpdateAppInputApi>

export const ActivateVersionRequestApi = zod.object({
    version_number: zod
        .number()
        .describe('Version number to activate. Must reference an existing version of this app.'),
})

export type ActivateVersionRequestApi = zod.input<typeof ActivateVersionRequestApi>
export type ActivateVersionRequestApiOutput = zod.output<typeof ActivateVersionRequestApi>

export const ActivateVersionResponseApi = zod.object({
    active_version: AppVersionContractApi.describe('The version that is now active for the app.'),
})

export type ActivateVersionResponseApi = zod.input<typeof ActivateVersionResponseApi>
export type ActivateVersionResponseApiOutput = zod.output<typeof ActivateVersionResponseApi>

export const StreamlitConnectInfoApi = zod.object({
    iframe_url: zod.string().describe('Authenticated URL to embed the running app in an iframe.'),
    expires_in: zod.number().describe('Seconds until the embedded session credential expires.'),
})

export type StreamlitConnectInfoApi = zod.input<typeof StreamlitConnectInfoApi>
export type StreamlitConnectInfoApiOutput = zod.output<typeof StreamlitConnectInfoApi>

export const createVersionFromSourceInputApiSourceMax = 1048576

export const CreateVersionFromSourceInputApi = zod.object({
    source: zod
        .string()
        .max(createVersionFromSourceInputApiSourceMax)
        .describe(
            "Full Python source for the Streamlit app's root app.py file, as free text (max 1 MB). Becomes a new version and is set as the active version."
        ),
})

export type CreateVersionFromSourceInputApi = zod.input<typeof CreateVersionFromSourceInputApi>
export type CreateVersionFromSourceInputApiOutput = zod.output<typeof CreateVersionFromSourceInputApi>

export const StreamlitAppStatusApi = zod.object({
    status: zod.string().describe("Sandbox lifecycle status, or 'stopped' when no sandbox exists."),
    restart_count: zod.number().describe("Number of times the app's sandbox has been restarted."),
    last_error: zod.string().describe('Most recent sandbox error message, empty when there is none.'),
    started_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the current sandbox started, null when stopped.'),
    last_activity_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('Timestamp of the last recorded viewer activity, null when none.'),
    version_number: zod.number().nullish().describe('Version number the running sandbox was booted from.'),
})

export type StreamlitAppStatusApi = zod.input<typeof StreamlitAppStatusApi>
export type StreamlitAppStatusApiOutput = zod.output<typeof StreamlitAppStatusApi>

export const UploadVersionRequestApi = zod.object({
    file: zod.url().describe('Zip archive containing the Streamlit app sources (max 10 MB).'),
})

export type UploadVersionRequestApi = zod.input<typeof UploadVersionRequestApi>
export type UploadVersionRequestApiOutput = zod.output<typeof UploadVersionRequestApi>

export const StreamlitAppVersionListApi = zod.object({
    results: zod.array(AppVersionContractApi).describe('Most recent versions of the app, newest first (capped at 50).'),
})

export type StreamlitAppVersionListApi = zod.input<typeof StreamlitAppVersionListApi>
export type StreamlitAppVersionListApiOutput = zod.output<typeof StreamlitAppVersionListApi>
