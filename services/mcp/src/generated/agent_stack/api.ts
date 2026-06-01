/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 30 enabled ops
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
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
export const agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigMentionOnlyDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigTimezoneDefault = `UTC`
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFourConfigRequireAuthDefault = true
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFiveConfigDefault = {}
export const agentApplicationsRevisionsCreateBodySpecTriggersDefault = []

export const agentApplicationsRevisionsCreateBodySpecToolsItemThreeArgsSchemaDefault = {}
export const agentApplicationsRevisionsCreateBodySpecToolsItemThreeRequiredDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemThreeTimeoutMsDefault = 5000
export const agentApplicationsRevisionsCreateBodySpecToolsItemThreeTimeoutMsMax = 60000

export const agentApplicationsRevisionsCreateBodySpecToolsDefault = []
export const agentApplicationsRevisionsCreateBodySpecMcpsDefault = []
export const agentApplicationsRevisionsCreateBodySpecSkillsDefault = []
export const agentApplicationsRevisionsCreateBodySpecIntegrationsDefault = []
export const agentApplicationsRevisionsCreateBodySpecSecretsDefault = []
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxTurnsDefault = 50
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxTurnsExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxTurnsMax = 2147483647

export const agentApplicationsRevisionsCreateBodySpecLimitsMaxToolCallsDefault = 200
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxToolCallsExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxToolCallsMax = 2147483647

export const agentApplicationsRevisionsCreateBodySpecLimitsMaxWallSecondsDefault = 900
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxWallSecondsExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxWallSecondsMax = 2147483647

export const agentApplicationsRevisionsCreateBodySpecLimitsDefault = {
    max_turns: 50,
    max_tool_calls: 200,
    max_wall_seconds: 900,
}
export const agentApplicationsRevisionsCreateBodySpecEntrypointDefault = `agent.md`
export const agentApplicationsRevisionsCreateBodySpecAuthModeDefault = `public`
export const agentApplicationsRevisionsCreateBodySpecAuthDefault = { mode: 'public' }

export const AgentApplicationsRevisionsCreateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().default(agentApplicationsRevisionsCreateBodyBundleUriDefault),
    spec: zod
        .object({
            model: zod.string().min(1),
            triggers: zod
                .array(
                    zod.union([
                        zod.object({
                            type: zod.literal('slack'),
                            config: zod.object({
                                channel_id: zod.string().optional(),
                                mention_only: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigMentionOnlyDefault
                                    ),
                                trusted_workspaces: zod.union([zod.array(zod.string()).min(1), zod.literal('*')]),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('webhook'),
                            config: zod.object({
                                path: zod.string(),
                                secret: zod.string().optional(),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('cron'),
                            config: zod.object({
                                schedule: zod.string(),
                                timezone: zod
                                    .string()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigTimezoneDefault
                                    ),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('chat'),
                            config: zod.object({
                                require_auth: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemFourConfigRequireAuthDefault
                                    ),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('mcp'),
                            config: zod
                                .object({})
                                .default(agentApplicationsRevisionsCreateBodySpecTriggersItemFiveConfigDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsCreateBodySpecTriggersDefault),
            tools: zod
                .array(
                    zod.union([
                        zod.object({
                            kind: zod.literal('native'),
                            id: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('custom'),
                            id: zod.string(),
                            path: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('client'),
                            id: zod.string().min(1),
                            description: zod.string().min(1),
                            args_schema: zod
                                .looseObject({})
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemThreeArgsSchemaDefault),
                            required: zod
                                .boolean()
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemThreeRequiredDefault),
                            timeout_ms: zod
                                .number()
                                .min(1)
                                .max(agentApplicationsRevisionsCreateBodySpecToolsItemThreeTimeoutMsMax)
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemThreeTimeoutMsDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsCreateBodySpecToolsDefault),
            mcps: zod
                .array(
                    zod.union([
                        zod.object({
                            kind: zod.literal('agent'),
                            slug: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('external'),
                            url: zod.url(),
                            auth: zod
                                .object({
                                    integration: zod.string().optional(),
                                })
                                .optional(),
                            allowlist: zod.array(zod.string()).optional(),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsCreateBodySpecMcpsDefault),
            skills: zod
                .array(
                    zod.object({
                        id: zod.string(),
                        path: zod.string(),
                        description: zod.string().optional(),
                    })
                )
                .default(agentApplicationsRevisionsCreateBodySpecSkillsDefault),
            integrations: zod.array(zod.string()).default(agentApplicationsRevisionsCreateBodySpecIntegrationsDefault),
            secrets: zod.array(zod.string()).default(agentApplicationsRevisionsCreateBodySpecSecretsDefault),
            limits: zod
                .object({
                    max_turns: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecLimitsMaxTurnsExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecLimitsMaxTurnsMax)
                        .default(agentApplicationsRevisionsCreateBodySpecLimitsMaxTurnsDefault),
                    max_tool_calls: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecLimitsMaxToolCallsExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecLimitsMaxToolCallsMax)
                        .default(agentApplicationsRevisionsCreateBodySpecLimitsMaxToolCallsDefault),
                    max_wall_seconds: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecLimitsMaxWallSecondsExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecLimitsMaxWallSecondsMax)
                        .default(agentApplicationsRevisionsCreateBodySpecLimitsMaxWallSecondsDefault),
                })
                .default(agentApplicationsRevisionsCreateBodySpecLimitsDefault),
            entrypoint: zod.string().default(agentApplicationsRevisionsCreateBodySpecEntrypointDefault),
            auth: zod
                .object({
                    mode: zod
                        .enum(['public', 'pat', 'posthog_internal', 'shared_secret'])
                        .default(agentApplicationsRevisionsCreateBodySpecAuthModeDefault),
                    header: zod.string().optional(),
                })
                .default(agentApplicationsRevisionsCreateBodySpecAuthDefault),
            reasoning: zod.enum(['minimal', 'low', 'medium', 'high', 'xhigh']).optional(),
        })
        .optional(),
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

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigMentionOnlyDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigTimezoneDefault = `UTC`
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourConfigRequireAuthDefault = true
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveConfigDefault = {}
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersDefault = []

export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemThreeArgsSchemaDefault = {}
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemThreeRequiredDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemThreeTimeoutMsDefault = 5000
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemThreeTimeoutMsMax = 60000

export const agentApplicationsRevisionsPartialUpdateBodySpecToolsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecSkillsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecIntegrationsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecSecretsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxTurnsDefault = 50
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxTurnsExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxTurnsMax = 2147483647

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxToolCallsDefault = 200
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxToolCallsExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxToolCallsMax = 2147483647

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxWallSecondsDefault = 900
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxWallSecondsExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxWallSecondsMax = 2147483647

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsDefault = {
    max_turns: 50,
    max_tool_calls: 200,
    max_wall_seconds: 900,
}
export const agentApplicationsRevisionsPartialUpdateBodySpecEntrypointDefault = `agent.md`
export const agentApplicationsRevisionsPartialUpdateBodySpecAuthModeDefault = `public`
export const agentApplicationsRevisionsPartialUpdateBodySpecAuthDefault = { mode: 'public' }

export const AgentApplicationsRevisionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    parent_revision: zod.uuid().nullish(),
    bundle_uri: zod.string().optional(),
    spec: zod
        .object({
            model: zod.string().min(1),
            triggers: zod
                .array(
                    zod.union([
                        zod.object({
                            type: zod.literal('slack'),
                            config: zod.object({
                                channel_id: zod.string().optional(),
                                mention_only: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigMentionOnlyDefault
                                    ),
                                trusted_workspaces: zod.union([zod.array(zod.string()).min(1), zod.literal('*')]),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('webhook'),
                            config: zod.object({
                                path: zod.string(),
                                secret: zod.string().optional(),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('cron'),
                            config: zod.object({
                                schedule: zod.string(),
                                timezone: zod
                                    .string()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigTimezoneDefault
                                    ),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('chat'),
                            config: zod.object({
                                require_auth: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourConfigRequireAuthDefault
                                    ),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('mcp'),
                            config: zod
                                .object({})
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveConfigDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecTriggersDefault),
            tools: zod
                .array(
                    zod.union([
                        zod.object({
                            kind: zod.literal('native'),
                            id: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('custom'),
                            id: zod.string(),
                            path: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('client'),
                            id: zod.string().min(1),
                            description: zod.string().min(1),
                            args_schema: zod
                                .looseObject({})
                                .default(
                                    agentApplicationsRevisionsPartialUpdateBodySpecToolsItemThreeArgsSchemaDefault
                                ),
                            required: zod
                                .boolean()
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecToolsItemThreeRequiredDefault),
                            timeout_ms: zod
                                .number()
                                .min(1)
                                .max(agentApplicationsRevisionsPartialUpdateBodySpecToolsItemThreeTimeoutMsMax)
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecToolsItemThreeTimeoutMsDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecToolsDefault),
            mcps: zod
                .array(
                    zod.union([
                        zod.object({
                            kind: zod.literal('agent'),
                            slug: zod.string(),
                        }),
                        zod.object({
                            kind: zod.literal('external'),
                            url: zod.url(),
                            auth: zod
                                .object({
                                    integration: zod.string().optional(),
                                })
                                .optional(),
                            allowlist: zod.array(zod.string()).optional(),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecMcpsDefault),
            skills: zod
                .array(
                    zod.object({
                        id: zod.string(),
                        path: zod.string(),
                        description: zod.string().optional(),
                    })
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecSkillsDefault),
            integrations: zod
                .array(zod.string())
                .default(agentApplicationsRevisionsPartialUpdateBodySpecIntegrationsDefault),
            secrets: zod.array(zod.string()).default(agentApplicationsRevisionsPartialUpdateBodySpecSecretsDefault),
            limits: zod
                .object({
                    max_turns: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxTurnsExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxTurnsMax)
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxTurnsDefault),
                    max_tool_calls: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxToolCallsExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxToolCallsMax)
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxToolCallsDefault),
                    max_wall_seconds: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxWallSecondsExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxWallSecondsMax)
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxWallSecondsDefault),
                })
                .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsDefault),
            entrypoint: zod.string().default(agentApplicationsRevisionsPartialUpdateBodySpecEntrypointDefault),
            auth: zod
                .object({
                    mode: zod
                        .enum(['public', 'pat', 'posthog_internal', 'shared_secret'])
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecAuthModeDefault),
                    header: zod.string().optional(),
                })
                .default(agentApplicationsRevisionsPartialUpdateBodySpecAuthDefault),
            reasoning: zod.enum(['minimal', 'low', 'medium', 'high', 'xhigh']).optional(),
        })
        .optional(),
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

export const agentApplicationsRevisionsBundleUpdateBodyModeDefault = `replace`

export const AgentApplicationsRevisionsBundleUpdateBody = /* @__PURE__ */ zod
    .object({
        files: zod.record(zod.string(), zod.string()),
        mode: zod
            .enum(['replace', 'merge'])
            .describe('* `replace` - replace\n* `merge` - merge')
            .default(agentApplicationsRevisionsBundleUpdateBodyModeDefault),
    })
    .describe(
        "Body shape for PUT /revisions/<id>/bundle/ — the bulk upload.\n\n`files` is a `{path: utf-8 content}` map. `mode='replace'` wipes the\nexisting bundle before writing the new set; `'merge'` upserts."
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

export const AgentApplicationsRevisionsFileRetrieveQueryParams = /* @__PURE__ */ zod.object({
    path: zod.string().describe('Bundle-relative file path, e.g. `agent.md` or `skills/research.md`.'),
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

export const AgentApplicationsRevisionsFileUpdateQueryParams = /* @__PURE__ */ zod.object({
    path: zod.string().describe('Bundle-relative file path, e.g. `agent.md` or `skills/research.md`.'),
})

export const AgentApplicationsRevisionsFileUpdateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string(),
    })
    .describe(
        'Body shape for PUT /revisions/<id>/file/. `path` lives in the query\nstring (matches the janitor wire format); `content` is the new file body.'
    )

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

export const AgentApplicationsRevisionsFileDestroyQueryParams = /* @__PURE__ */ zod.object({
    path: zod.string().describe('Bundle-relative file path, e.g. `agent.md` or `skills/research.md`.'),
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
 * Return the fully-assembled system prompt for this revision.

Authoring tools call this to preview what the model will actually
see at session start — the platform framework preamble plus the
bundle's `agent.md` plus the skills index. Useful for debugging
author-vs-framework precedence conflicts and verifying
`spec.framework_prompt.omit` overrides took effect.
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

URLs:
    GET    /api/projects/<team>/agent_applications/             list
    POST   /api/projects/<team>/agent_applications/             create
    GET    /api/projects/<team>/agent_applications/<id|slug>/   retrieve
    PATCH  /api/projects/<team>/agent_applications/<id|slug>/   update
    DELETE /api/projects/<team>/agent_applications/<id|slug>/   archive
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
    POST   /api/projects/<team>/agent_applications/<id|slug>/set_env/        bulk replace env
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/        list set keys
    GET    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  is one key set?
    PUT    /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  set one key
    DELETE /api/projects/<team>/agent_applications/<id|slug>/env_keys/<KEY>/  clear one key
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
 * List the names of secrets currently set on the application.

Returns names only — values stay server-side under
`EncryptedTextField`. Use this to drive the "set / unset" badge
next to a declared secret in the editor UI.
 */
export const AgentApplicationsEnvKeysListParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * GET / PUT / DELETE one secret by name.

- `GET`    → `{ key, is_set }` (never returns the value).
- `PUT`    → upserts `{ value }` into the env block.
- `DELETE` → removes the key. No-op when it wasn't set.

Per-method scope: GET is treated as a write action so the
single action name maps to one consistent scope; reading whether
a secret is set is restricted to writers in any case.
 */
export const AgentApplicationsEnvKeysGetParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
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
 * GET / PUT / DELETE one secret by name.

- `GET`    → `{ key, is_set }` (never returns the value).
- `PUT`    → upserts `{ value }` into the env block.
- `DELETE` → removes the key. No-op when it wasn't set.

Per-method scope: GET is treated as a write action so the
single action name maps to one consistent scope; reading whether
a secret is set is restricted to writers in any case.
 */
export const AgentApplicationsEnvKeysClearParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this agent application.'),
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
 * Authoring-side proxy for invoking a *draft* (or any non-live) revision.

Closes the anonymous-draft-invoke gap: the public ingress URL refuses
non-live invokes that don't carry the `x-agent-preview-secret` header;
this proxy attaches it after authenticating the Django caller. See
docs/agent-platform/plans/draft-preview-auth.md.

URL: `/api/projects/<team>/agent_applications/<app>/preview-proxy/<rest>`
Auth: standard PAT / session — `agent_application:read` scope.
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

/**
 * List sessions for this application, newest first. Strips the
conversation transcript from each summary, but includes a `preview`
(last assistant text, ~120 chars) and `usage_total` (token + cost
aggregate). Use `agent-applications-sessions-retrieve` for the full
transcript of a single session.
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
the trailing N messages with `?last_n=`. Always returns a
`usage_total` block aggregated over the entire session, regardless of
trim. The runner-side queue DB is the source of truth.
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

export const AgentApplicationsSetEnvCreateBody = /* @__PURE__ */ zod
    .object({
        env: zod.record(zod.string(), zod.string()),
    })
    .describe(
        'Body shape for AgentApplicationViewSet.set_env.\n\n`env` is a JSON object of string→string. The view encrypts it via the\nsame Fernet schedule the worker uses to decrypt.'
    )

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
