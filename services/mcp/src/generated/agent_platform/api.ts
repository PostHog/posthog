/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 37 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Agent applications — the deployable unit of the platform.
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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

export const agentApplicationsCreateBodySlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')

export const AgentApplicationsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsCreateBodyNameMax),
    slug: zod
        .string()
        .max(agentApplicationsCreateBodySlugMax)
        .regex(agentApplicationsCreateBodySlugRegExp)
        .optional()
        .describe(
            'Globally-unique URL identifier. Server-minted as an opaque random slug on create; only allowlisted first-party teams may set it explicitly. Slugs live in one global namespace (domain-mode ingress routing carries no team).'
        ),
    description: zod.string().optional(),
    archived: zod.boolean().optional(),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
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
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
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
    parent_revision: zod.string().nullish(),
    bundle_uri: zod
        .string()
        .default(agentApplicationsRevisionsCreateBodyBundleUriDefault)
        .describe(
            'Storage-prefix metadata for the bundle, e.g. `fs://my-agent/`. Optional — leave blank and the server fills `fs://<application-slug>/`. Bundles are addressed by revision id regardless, so this is only a prefix hint.'
        ),
    spec: zod.unknown().optional(),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
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
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
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
    parent_revision: zod.string().nullish(),
    bundle_uri: zod
        .string()
        .optional()
        .describe(
            'Storage-prefix metadata for the bundle, e.g. `fs://my-agent/`. Optional — leave blank and the server fills `fs://<application-slug>/`. Bundles are addressed by revision id regardless, so this is only a prefix hint.'
        ),
    spec: zod.unknown().optional(),
})

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const AgentApplicationsRevisionsAgentMdUpdateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsRevisionsAgentMdUpdateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string(),
    })
    .describe('Body shape for PUT /revisions/<id>/agent_md/.')

/**
 * Mark a revision archived. If it was the live one, clear the
 * application's live_revision pointer (the app effectively has no
 * deployable version until another revision is promoted).
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

/**
 * Read the full typed bundle: `{ agent_md, skills, tools, spec }`.
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
 * Full-replace the typed bundle. Anything not in the payload is
 * deleted. Tool sources are AST-checked + esbuild-compiled by the
 * janitor before any S3 writes.
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

export const AgentApplicationsRevisionsBundleUpdateBody = /* @__PURE__ */ zod
    .object({
        agent_md: zod.string(),
        tools: zod
            .array(
                zod
                    .object({
                        description: zod.string(),
                        args_schema: zod.record(zod.string(), zod.unknown()),
                        source: zod.string(),
                    })
                    .describe('Body shape for PUT /revisions/<id>/tools/<tool_id>/.')
            )
            .optional(),
        spec: zod.record(zod.string(), zod.unknown()),
    })
    .describe(
        'Body shape for PUT /revisions/<id>/bundle/ — the full-replace typed\npayload. Skills are not authored here: they come from the llma-skill store\nvia `skill_refs` and are materialized into the bundle at freeze.'
    )

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

export const AgentApplicationsRevisionsCloneFromCreateBody = /* @__PURE__ */ zod
    .object({
        source_revision_id: zod.string(),
    })
    .describe(
        'Body shape for POST /revisions/<id>/clone_from/ — copy every file\nfrom `source_revision_id` into this (draft) revision.'
    )

/**
 * Fire one cron job out-of-band — the same execution path the
 * scheduler walks, but on demand. Authoring UX: the user iterates on
 * a cron prompt by clicking 'Fire now' rather than waiting for the
 * next scheduled firing. Without this, 'did my prompt do the right
 * thing?' is unanswerable until the cron actually fires.
 *
 * Idempotent via `request_id`: repeat clicks with the same id resolve
 * to the same session id rather than firing N times.
 */
export const AgentApplicationsRevisionsCronFireCreateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsRevisionsCronFireCreateBody = /* @__PURE__ */ zod.object({
    cron_name: zod.string().describe('`name` of the cron trigger in `spec.triggers[]` to fire.'),
    request_id: zod
        .string()
        .nullish()
        .describe(
            "Stable client-supplied id so repeated clicks of the same UI 'Fire now' button resolve to the same session id rather than firing twice. The janitor keys dedupe off `cron-manual:<rev>:<name>:<request_id>`. Omit to fire unconditionally — every call generates a fresh UUID."
        ),
})

/**
 * List the names of secrets currently set on this revision.
 *
 * Returns names only — values stay server-side under
 * `EncryptedTextField`. Use this to drive the "set / unset" badge next to
 * a declared secret in the editor UI.
 */
export const AgentRevisionsEnvKeysListParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * GET / PUT / DELETE one secret by name on this revision.
 *
 * - `GET`    → `{ key, is_set }` (never returns the value).
 * - `PUT`    → upserts `{ value }` into the env block.
 * - `DELETE` → removes the key. No-op when it wasn't set.
 *
 * Per-method scope: GET is treated as a write action so the single action
 * name maps to one consistent scope; reading whether a secret is set is
 * restricted to writers in any case.
 */
export const AgentRevisionsEnvKeysGetParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    key: zod
        .string()
        .describe('The env variable name. Conventionally UPPER_SNAKE_CASE; the API does not enforce a shape.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * GET / PUT / DELETE one secret by name on this revision.
 *
 * - `GET`    → `{ key, is_set }` (never returns the value).
 * - `PUT`    → upserts `{ value }` into the env block.
 * - `DELETE` → removes the key. No-op when it wasn't set.
 *
 * Per-method scope: GET is treated as a write action so the single action
 * name maps to one consistent scope; reading whether a secret is set is
 * restricted to writers in any case.
 */
export const AgentRevisionsEnvKeysClearParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    key: zod
        .string()
        .describe('The env variable name. Conventionally UPPER_SNAKE_CASE; the API does not enforce a shape.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Freeze the bundle: draft → ready, stamps sha256 on the row.
 *
 * Django is a thin proxy here: resolve template refs into the
 * bundle, ask the janitor to seal it (the janitor returns the sha
 * + the spec it derived from the typed resources), then stamp the
 * row. No `transaction.atomic()` — the janitor's freeze is idempotent
 * (on retry it re-reads the existing `.frozen` marker + re-derives
 * spec), so a partial failure here is recoverable by re-calling
 * freeze, not by transactional rollback. Holding an atomic block
 * across the janitor HTTP call previously deadlocked the
 * agent_revision row against the janitor's spec write — that's
 * moved off the janitor side as part of the same fix.
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

/**
 * Full-replace the draft's store-skill references. They are resolved
 * and materialized into the bundle at freeze, not here — this only records
 * which skills (and pinned versions) the freeze should pull in.
 */
export const AgentApplicationsRevisionsSkillRefsUpdateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemFromTemplateMax = 64

export const agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemAliasMax = 64

export const agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemAliasRegExp = new RegExp(
    '^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$'
)

export const AgentApplicationsRevisionsSkillRefsUpdateBody = /* @__PURE__ */ zod
    .object({
        skill_refs: zod
            .array(
                zod
                    .object({
                        from_template: zod
                            .string()
                            .max(agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemFromTemplateMax)
                            .describe(
                                'Name of the skill in the llma-skill store to pin into this agent. Resolved at freeze to the chosen `version` and materialized into the bundle.'
                            ),
                        alias: zod
                            .string()
                            .max(agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemAliasMax)
                            .regex(agentApplicationsRevisionsSkillRefsUpdateBodySkillRefsItemAliasRegExp)
                            .describe(
                                'Folder the resolved skill is materialized under in the bundle (`skills/<alias>/`). Lowercase letters, digits, hyphens or underscores, starting and ending with a letter or digit; must be unique within the revision.'
                            ),
                        version: zod
                            .number()
                            .min(1)
                            .optional()
                            .describe(
                                "Specific published version to pin. Omit to pin the store's latest version at freeze time."
                            ),
                    })
                    .describe(
                        "One reference to a versioned skill in the llma-skill store, pinned into\nthis agent's bundle at freeze."
                    )
            )
            .describe('The complete set of store-skill references for this draft; replaces any existing references.'),
    })
    .describe("Body for PUT /revisions/<id>/skill_refs/ — full-replace the draft's references.")

/**
 * Build a Slack app manifest for this revision's slack trigger.
 *
 * Deterministic: the OAuth scopes and bot event subscriptions are derived
 * from the slack trigger config (`mention_only` / `auto_resume_threads` /
 * `ack_reaction`) and the agent's Slack tools, so the manifest already
 * subscribes to exactly the events the config needs. 400 if the revision
 * has no slack trigger.
 */
export const AgentApplicationsRevisionsSlackManifestParams = /* @__PURE__ */ zod.object({
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
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const AgentApplicationsRevisionsSpecUpdateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsRevisionsSpecUpdateBody = /* @__PURE__ */ zod
    .object({
        spec: zod.record(zod.string(), zod.unknown()),
    })
    .describe(
        "Body shape for PUT /revisions/<id>/spec/. The body's `spec` object\nis the author-facing slice (skills/tools are server-derived at freeze)."
    )

/**
 * Return the fully-assembled system prompt for this revision.
 *
 * Authoring tools call this to preview what the model will actually
 * see at session start — the platform framework preamble plus the
 * bundle's `agent.md` plus the skills index. Useful for debugging
 * author-vs-framework precedence conflicts and verifying
 * `spec.framework_prompt.omit` overrides took effect.
 */
export const AgentApplicationsRevisionsSystemPromptParams = /* @__PURE__ */ zod.object({
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
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsToolsUpdatePathToolIdRegExp = new RegExp('^[a-z0-9][a-z0-9_-]*$')

export const AgentApplicationsRevisionsToolsUpdateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    tool_id: zod.string().regex(agentApplicationsRevisionsToolsUpdatePathToolIdRegExp),
})

export const AgentApplicationsRevisionsToolsUpdateBody = /* @__PURE__ */ zod
    .object({
        description: zod.string(),
        args_schema: zod.record(zod.string(), zod.unknown()),
        source: zod.string(),
    })
    .describe('Body shape for PUT /revisions/<id>/tools/<tool_id>/.')

/**
 * Revisions of an agent. Created in `draft`, promoted through
 * `ready → live` once the bundle has been uploaded + frozen.
 *
 * URLs (nested under an application):
 *
 *     Model CRUD:
 *         GET   .../revisions/                       list
 *         POST  .../revisions/                       create draft
 *         GET   .../revisions/<id>/                  retrieve
 *         PATCH .../revisions/<id>/                  update spec (draft only)
 *
 *     Lifecycle:
 *         POST  .../revisions/<id>/promote/          ready → live
 *         POST  .../revisions/<id>/archive/          → archived
 *         POST  .../revisions/<id>/freeze/           draft → ready (stamps sha256)
 *         POST  .../revisions/<id>/clone_from/       copy bundle from another rev
 *         POST  .../revisions/new_draft/             create draft + clone_from atomically
 *
 *     Bundle authoring (proxied to the janitor):
 *         GET    .../revisions/<id>/manifest/        list paths + sha256
 *         GET    .../revisions/<id>/file/?path=…     read one file
 *         PUT    .../revisions/<id>/file/?path=…     write one file (draft)
 *         DELETE .../revisions/<id>/file/?path=…     delete one file (draft)
 *         GET    .../revisions/<id>/bundle/          bulk pull all files
 *         PUT    .../revisions/<id>/bundle/          bulk push (replace|merge)
 */
export const agentApplicationsRevisionsToolsDestroyPathToolIdRegExp = new RegExp('^[a-z0-9][a-z0-9_-]*$')

export const AgentApplicationsRevisionsToolsDestroyParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    tool_id: zod.string().regex(agentApplicationsRevisionsToolsDestroyPathToolIdRegExp),
})

/**
 * Execute one persisted custom tool in a single-shot sandbox.
 *
 * Authoring loop's "test this tool" button. The tool's source must
 * already be PUT (compiled.js is what runs); this just invokes it
 * with the caller-supplied args and a stubbed ctx. No real secrets
 * leave Django — `mock_secrets` is a `{name → placeholder}` map.
 */
export const agentApplicationsRevisionsToolsDryRunCreatePathToolIdRegExp = new RegExp('^[a-z0-9][a-z0-9_-]*$')

export const AgentApplicationsRevisionsToolsDryRunCreateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    tool_id: zod.string().regex(agentApplicationsRevisionsToolsDryRunCreatePathToolIdRegExp),
})

export const AgentApplicationsRevisionsToolsDryRunCreateBody = /* @__PURE__ */ zod
    .object({
        args: zod
            .unknown()
            .describe(
                "Synthetic args the tool's `actions.default` is called with. Free-form JSON; the sandbox doesn't validate against the tool's `args_schema` — that's the author's responsibility to keep in sync."
            ),
        mock_secrets: zod
            .record(zod.string(), zod.string())
            .optional()
            .describe(
                'Optional `{secret_name → placeholder_string}` map. The string is returned verbatim by `ctx.secrets.ref(name)` inside the tool. The real secret value never enters the sandbox.'
            ),
    })
    .describe(
        "Body shape for POST /revisions/<id>/tools/<tool_id>/dry_run/.\n\nExecutes the persisted compiled.js once in the janitor's single-shot\nsandbox with caller-supplied args + a stubbed ctx. No real secrets\nleave Django — `mock_secrets` is a `{name → opaque nonce}` map the\nsandbox plumbs into `ctx.secrets.ref(name)` so the tool body returns\nsomething deterministic to the author."
    )

/**
 * Pre-flight checks before freeze + promote: agent.md exists,
 * every native tool id is registered, every custom tool has its
 * compiled.js + schema.json, every skill path exists, every declared
 * secret has a value set in this revision's env block. Returns
 * `{ ok, errors: [...] }`. Works on any revision state.
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
 * from `source_revision_id`. Saves the MCP one round-trip vs the
 * explicit create + clone_from sequence.
 */
export const AgentApplicationsRevisionsNewDraftCreateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsRevisionsNewDraftCreateBody = /* @__PURE__ */ zod
    .object({
        application_id: zod.string(),
        source_revision_id: zod.string(),
    })
    .describe(
        'Body shape for POST /revisions/clone_from/ — atomically create a new\ndraft revision under `application_id` and clone its initial bundle from\n`source_revision_id`. Convenience for the "edit live" flow so the MCP\ndoesn\'t have to do create-then-clone-from in two calls.'
    )

/**
 * Agent applications — the deployable unit of the platform.
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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

export const agentApplicationsPartialUpdateBodySlugRegExp = new RegExp('^[-a-zA-Z0-9_]+$')

export const AgentApplicationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentApplicationsPartialUpdateBodyNameMax).optional(),
    slug: zod
        .string()
        .max(agentApplicationsPartialUpdateBodySlugMax)
        .regex(agentApplicationsPartialUpdateBodySlugRegExp)
        .optional()
        .describe(
            'Globally-unique URL identifier. Server-minted as an opaque random slug on create; only allowlisted first-party teams may set it explicitly. Slugs live in one global namespace (domain-mode ingress routing carries no team).'
        ),
    description: zod.string().optional(),
    archived: zod.boolean().optional(),
})

/**
 * Agent applications — the deployable unit of the platform.
 *
 * URLs:
 *     GET    /api/projects/<team>/agent_applications/             list
 *     POST   /api/projects/<team>/agent_applications/             create
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
 *     PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
 *     POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
 *     GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
 *     PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
 *     DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
 * Authoring-side proxy for invoking a *draft* (or any non-live) revision.
 *
 * Closes the anonymous-draft-invoke gap: the public ingress URL refuses
 * non-live invokes that don't carry the `x-agent-preview-secret` header;
 * this proxy attaches it after authenticating the Django caller.
 *
 * URL: `/api/projects/<team>/agent_applications/<app>/preview-proxy/<rest>`
 * Auth: standard PAT / session — `agents:write` scope (POST run/send/cancel
 * is a mutating invoke; the read-only `listen` GET is `agents:read`).
 */
export const AgentApplicationsPreviewProxyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    rest: zod.string().describe('Ingress sub-path under the agent slug. One of: `run`, `send`, `cancel`, `listen`.'),
})

export const AgentApplicationsPreviewProxyQueryParams = /* @__PURE__ */ zod.object({
    format: zod.enum(['json', 'sse']).optional(),
    revision_id: zod.string().describe('Target draft revision. Must belong to this application and not be live.'),
})

export const AgentApplicationsPreviewProxyBody = /* @__PURE__ */ zod
    .object({
        message: zod
            .string()
            .optional()
            .describe(
                'User message to deliver to the agent. Required for `run` (starts the session) and `send` (appends to it); ignored for `cancel` / `listen`.'
            ),
        session_id: zod
            .string()
            .optional()
            .describe(
                'Target session id for `send` — the running session to append the message to. Omit for `run` (a fresh session is created).'
            ),
    })
    .describe(
        'Body forwarded verbatim to the agent ingress for a *preview* invoke of a\nnon-live revision. The meaningful shape depends on the `rest` path segment:\n\n- `run` — `{ message }`: the user message that starts a new session.\n- `send` — `{ session_id, message }`: append a message to a running session.\n- `cancel` / `listen` — no body.\n\nDocuments `message` / `session_id` so the generated MCP tool exposes them;\nany extra keys are still forwarded as-is to ingress.'
    )

/**
 * List sessions for this application, most recently active first. Strips the
 * conversation transcript from each summary, but includes a `preview`
 * (last assistant text, ~120 chars) and `usage_total` (token + cost
 * aggregate). Use `agent-applications-sessions-retrieve` for the full
 * transcript of a single session.
 */
export const AgentApplicationsSessionsListParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsSessionsListQueryParams = /* @__PURE__ */ zod.object({
    created_after: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('ISO datetime — return sessions with created_at >= this.'),
    created_before: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('ISO datetime — return sessions with created_at <= this.'),
    limit: zod.number().optional(),
    offset: zod.number().optional(),
    revision_id: zod.string().optional().describe('Only return sessions started against this specific revision.'),
    state: zod
        .string()
        .optional()
        .describe(
            'Filter by session state. Comma-separated list accepted (e.g. `completed,failed`). Valid values: queued, running, completed, closed, cancelled, failed.'
        ),
})

/**
 * Fetch one session's state — full conversation by default, or just
 * the trailing N messages with `?last_n=`. Always returns a
 * `usage_total` block aggregated over the entire session, regardless of
 * trim. The runner-side queue DB is the source of truth.
 */
export const AgentApplicationsSessionsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    session_id: zod.string().describe('UUID of the session to fetch (must belong to this application).'),
})

export const AgentApplicationsSessionsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    last_n: zod
        .number()
        .optional()
        .describe(
            'If set, return only the most recent N messages from the conversation. `usage_total` is still computed over the full session — only the transcript is trimmed. The response includes `conversation_trimmed: true` and `conversation_total_turns` so the caller knows how much was hidden.'
        ),
})

/**
 * Read the runner's structured event log for one session from
 * ClickHouse. Filters (limit / after / before / level / search)
 * match the shared `LogEntryMixin` helper used by hog_function +
 * hog_flow.
 */
export const AgentApplicationsSessionLogsParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    session_id: zod.string().describe('UUID of the session whose logs to fetch.'),
})

export const agentApplicationsSessionLogsQueryLimitDefault = 50
export const agentApplicationsSessionLogsQueryLimitMax = 500

export const AgentApplicationsSessionLogsQueryParams = /* @__PURE__ */ zod.object({
    after: zod.iso.datetime({ offset: true }).optional().describe('Only return entries after this ISO 8601 timestamp.'),
    before: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('Only return entries before this ISO 8601 timestamp.'),
    instance_id: zod.string().min(1).optional().describe('Filter logs to a specific execution instance.'),
    level: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Comma-separated log levels to include, e.g. 'WARN,ERROR'. Valid levels: DEBUG, LOG, INFO, WARN, ERROR."
        ),
    limit: zod
        .number()
        .min(1)
        .max(agentApplicationsSessionLogsQueryLimitMax)
        .default(agentApplicationsSessionLogsQueryLimitDefault)
        .describe('Maximum number of log entries to return (1-500, default 50).'),
    search: zod.string().min(1).optional().describe('Case-insensitive substring search across log messages.'),
})

/**
 * Served-model catalog — each model's id, provider, context window, and USD-per-million-token pricing — plus the curated auto-level → model map. Project-agnostic; sourced from the AI gateway catalog. Powers the config UI model browser and the agent builder's model-choosing skill.
 */
export const AgentApplicationsModelsParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * The canonical JSON Schema for an agent `spec` — every field, type, enum, default, and the discriminated unions for `models` / `triggers[]` / `tools[]`, each with an inline description. Emitted from the same source the runner validates against (fields with a default are optional on write), so read it BEFORE composing a spec for create / revisions-spec-update instead of guessing the shape. Pass `section` to fetch just one part.
 */
export const AgentApplicationsSpecSchemaParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentApplicationsSpecSchemaQueryParams = /* @__PURE__ */ zod.object({
    section: zod
        .string()
        .optional()
        .describe(
            'Return only this top-level slice of the spec schema to save tokens — one of `models`, `triggers`, `tools`, `mcps`, `skills`, `identity_providers`, `secrets`, `limits`, `reasoning`, `framework_prompt`, `resume`. Omit for the whole spec schema.'
        ),
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
