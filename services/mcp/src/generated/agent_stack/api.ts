/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 23 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Agent applications — the deployable unit of the platform.

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
 */
export const AgentApplicationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Agent applications — the deployable unit of the platform.

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
 */
export const AgentApplicationsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentApplicationsCreateBodyNameMax = 255

export const agentApplicationsCreateBodySlugMax = 63

export const agentApplicationsCreateBodyArchivedDefault = false

export const AgentApplicationsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsCreateBodyNameMax),
    slug: zod.string().max(agentApplicationsCreateBodySlugMax),
    description: zod.string().optional(),
    archived: zod.boolean().default(agentApplicationsCreateBodyArchivedDefault),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
`ready → live` once the bundle has been uploaded + frozen.

URLs (nested under an application):

    Model CRUD:
        GET   .../revisions/                       list
        POST  .../revisions/                       create draft
        GET   .../revisions/<id>/                  retrieve
        PATCH .../revisions/<id>/                  update spec (draft only)

    Lifecycle:
        POST  .../revisions/<id>/promote/          ready → live
        POST  .../revisions/<id>/archive/          → archived
        POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
        POST  .../revisions/<id>/clone_from/       copy bundle from another rev
        POST  .../revisions/new_draft/             create draft + clone_from atomically

    Bundle authoring (proxied to the janitor):
        GET    .../revisions/<id>/manifest/        list paths + sha256
        GET    .../revisions/<id>/file/?path=…     read one file
        PUT    .../revisions/<id>/file/?path=…     write one file (draft)
        DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
        GET    .../revisions/<id>/bundle/          bulk pull all files
        PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const AgentApplicationsRevisionsListParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsRevisionsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
`ready → live` once the bundle has been uploaded + frozen.

URLs (nested under an application):

    Model CRUD:
        GET   .../revisions/                       list
        POST  .../revisions/                       create draft
        GET   .../revisions/<id>/                  retrieve
        PATCH .../revisions/<id>/                  update spec (draft only)

    Lifecycle:
        POST  .../revisions/<id>/promote/          ready → live
        POST  .../revisions/<id>/archive/          → archived
        POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
        POST  .../revisions/<id>/clone_from/       copy bundle from another rev
        POST  .../revisions/new_draft/             create draft + clone_from atomically

    Bundle authoring (proxied to the janitor):
        GET    .../revisions/<id>/manifest/        list paths + sha256
        GET    .../revisions/<id>/file/?path=…     read one file
        PUT    .../revisions/<id>/file/?path=…     write one file (draft)
        DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
        GET    .../revisions/<id>/bundle/          bulk pull all files
        PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const AgentApplicationsRevisionsCreateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentApplicationsRevisionsCreateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsCreateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
`ready → live` once the bundle has been uploaded + frozen.

URLs (nested under an application):

    Model CRUD:
        GET   .../revisions/                       list
        POST  .../revisions/                       create draft
        GET   .../revisions/<id>/                  retrieve
        PATCH .../revisions/<id>/                  update spec (draft only)

    Lifecycle:
        POST  .../revisions/<id>/promote/          ready → live
        POST  .../revisions/<id>/archive/          → archived
        POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
        POST  .../revisions/<id>/clone_from/       copy bundle from another rev
        POST  .../revisions/new_draft/             create draft + clone_from atomically

    Bundle authoring (proxied to the janitor):
        GET    .../revisions/<id>/manifest/        list paths + sha256
        GET    .../revisions/<id>/file/?path=…     read one file
        PUT    .../revisions/<id>/file/?path=…     write one file (draft)
        DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
        GET    .../revisions/<id>/bundle/          bulk pull all files
        PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const AgentApplicationsRevisionsRetrieveParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
`ready → live` once the bundle has been uploaded + frozen.

URLs (nested under an application):

    Model CRUD:
        GET   .../revisions/                       list
        POST  .../revisions/                       create draft
        GET   .../revisions/<id>/                  retrieve
        PATCH .../revisions/<id>/                  update spec (draft only)

    Lifecycle:
        POST  .../revisions/<id>/promote/          ready → live
        POST  .../revisions/<id>/archive/          → archived
        POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
        POST  .../revisions/<id>/clone_from/       copy bundle from another rev
        POST  .../revisions/new_draft/             create draft + clone_from atomically

    Bundle authoring (proxied to the janitor):
        GET    .../revisions/<id>/manifest/        list paths + sha256
        GET    .../revisions/<id>/file/?path=…     read one file
        PUT    .../revisions/<id>/file/?path=…     write one file (draft)
        DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
        GET    .../revisions/<id>/bundle/          bulk pull all files
        PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const AgentApplicationsRevisionsPartialUpdateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsRevisionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().optional(),
    spec: zod.unknown().optional(),
})

/**
 * Mark a revision archived. If it was the live one, clear the
application's live_revision pointer (the app effectively has no
deployable version until another revision is promoted).
 */
export const AgentApplicationsRevisionsArchiveCreateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentApplicationsRevisionsArchiveCreateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsArchiveCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsArchiveCreateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Bulk-pull: returns `{ files: { path: content, ... }, ... }`. Use
this when the MCP wants the whole bundle to work on locally.
 */
export const AgentApplicationsRevisionsBundleRetrieveParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Bulk-push the bundle. Body `{ files, mode: replace|merge }`.
 */
export const AgentApplicationsRevisionsBundleUpdateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentApplicationsRevisionsBundleUpdateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsBundleUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsBundleUpdateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Copy every file from `source_revision_id` into this revision.
 */
export const AgentApplicationsRevisionsCloneFromCreateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentApplicationsRevisionsCloneFromCreateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsCloneFromCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsCloneFromCreateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Read one file by `?path=...`. Works on any revision state.
 */
export const AgentApplicationsRevisionsFileRetrieveParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Write one file by `?path=...`. Draft-only (janitor enforces).
 */
export const AgentApplicationsRevisionsFileUpdateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentApplicationsRevisionsFileUpdateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsFileUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsFileUpdateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Delete one file by `?path=...`. Draft-only.
 */
export const AgentApplicationsRevisionsFileDestroyParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Freeze the bundle: draft → ready, stamps sha256 on the row.
The janitor computes the digest and updates the revision row in PG;
Django re-reads the row before returning so the response reflects
the persisted state.
 */
export const AgentApplicationsRevisionsFreezeCreateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentApplicationsRevisionsFreezeCreateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsFreezeCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsFreezeCreateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * List every file in this revision's bundle (path, size, sha256).
 */
export const AgentApplicationsRevisionsManifestRetrieveParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * ready → live. Sets the parent application's live_revision.
 */
export const AgentApplicationsRevisionsPromoteCreateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentApplicationsRevisionsPromoteCreateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsPromoteCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsPromoteCreateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Pre-flight checks before freeze + promote: entrypoint file exists,
every native tool id is registered, every custom tool has its
compiled.js + schema.json, every skill path exists, every declared
secret has a value set in the application's env block. Returns
`{ ok, errors: [...] }`. Works on any revision state.
 */
export const AgentApplicationsRevisionsValidateCreateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Create a fresh draft revision under `application_id` and seed it
from `source_revision_id`. Saves the MCP one round-trip vs the
explicit create + clone_from sequence.
 */
export const AgentApplicationsRevisionsNewDraftCreateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentApplicationsRevisionsNewDraftCreateBodyBundleUriDefault = ``

export const AgentApplicationsRevisionsNewDraftCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsNewDraftCreateBodyBundleUriDefault),
    spec: zod.unknown().optional(),
})

/**
 * Agent applications — the deployable unit of the platform.

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
 */
export const AgentApplicationsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Agent applications — the deployable unit of the platform.

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
 */
export const AgentApplicationsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentApplicationsPartialUpdateBodyNameMax = 255

export const agentApplicationsPartialUpdateBodySlugMax = 63

export const AgentApplicationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsPartialUpdateBodyNameMax).optional(),
    slug: zod.string().max(agentApplicationsPartialUpdateBodySlugMax).optional(),
    description: zod.string().optional(),
    archived: zod.boolean().optional(),
})

/**
 * Agent applications — the deployable unit of the platform.

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/   set env
 */
export const AgentApplicationsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Replace the agent's encrypted env block.

The body is `{ "env": { "<KEY>": "<value>", ... } }`. The encrypted
text gets stored on AgentApplication.encrypted_env; the worker
decrypts it at session start via the same Fernet schedule (see
agent-shared/src/runtime/encryption.ts).
 */
export const AgentApplicationsSetEnvCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentApplicationsSetEnvCreateBodyNameMax = 255

export const agentApplicationsSetEnvCreateBodySlugMax = 63

export const agentApplicationsSetEnvCreateBodyArchivedDefault = false

export const AgentApplicationsSetEnvCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsSetEnvCreateBodyNameMax),
    slug: zod.string().max(agentApplicationsSetEnvCreateBodySlugMax),
    description: zod.string().optional(),
    archived: zod.boolean().default(agentApplicationsSetEnvCreateBodyArchivedDefault),
})

/**
 * Read-only catalog of every @posthog/* native tool the runner knows.
 */
export const AgentNativeToolsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
