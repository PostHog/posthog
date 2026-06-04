/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 50 enabled ops
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
export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigPromptMax = 4096

export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigCatchUpDefault = `most_recent`
export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsDefault = 3600
export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsMax = 604800

export const agentApplicationsRevisionsCreateBodySpecTriggersItemFourConfigRequireAuthDefault = true
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFiveConfigDefault = {}
export const agentApplicationsRevisionsCreateBodySpecTriggersDefault = []
export const agentApplicationsRevisionsCreateBodySpecToolsItemThreeVersionMin = 0

export const agentApplicationsRevisionsCreateBodySpecToolsItemFourArgsSchemaDefault = {}
export const agentApplicationsRevisionsCreateBodySpecToolsItemFourRequiredDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemFourTimeoutMsDefault = 5000
export const agentApplicationsRevisionsCreateBodySpecToolsItemFourTimeoutMsMax = 60000

export const agentApplicationsRevisionsCreateBodySpecToolsDefault = []
export const agentApplicationsRevisionsCreateBodySpecMcpsItemSecretsDefault = []

export const agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoRequiresApprovalDefault = false
export const agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowAgentApproverDefault = false
export const agentApplicationsRevisionsCreateBodySpecMcpsDefault = []
export const agentApplicationsRevisionsCreateBodySpecSkillsItemVersionMin = 0

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
export const agentApplicationsRevisionsCreateBodySpecAuthModesItemTwoScopesDefault = []

export const agentApplicationsRevisionsCreateBodySpecAuthModesDefault = [{ type: `public` }]

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
                                name: zod.string().min(1),
                                schedule: zod.string().min(1),
                                timezone: zod
                                    .string()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigTimezoneDefault
                                    ),
                                prompt: zod
                                    .string()
                                    .min(1)
                                    .max(agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigPromptMax),
                                external_key: zod.string().optional(),
                                catch_up: zod
                                    .enum(['all', 'most_recent', 'skip'])
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigCatchUpDefault
                                    ),
                                max_catch_up_age_seconds: zod
                                    .number()
                                    .min(1)
                                    .max(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsMax
                                    )
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsDefault
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
                            kind: zod.literal('custom_template'),
                            from_template: zod.string(),
                            alias: zod.string(),
                            version: zod
                                .number()
                                .min(agentApplicationsRevisionsCreateBodySpecToolsItemThreeVersionMin)
                                .optional(),
                        }),
                        zod.object({
                            kind: zod.literal('client'),
                            id: zod.string().min(1),
                            description: zod.string().min(1),
                            args_schema: zod
                                .looseObject({})
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemFourArgsSchemaDefault),
                            required: zod
                                .boolean()
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemFourRequiredDefault),
                            timeout_ms: zod
                                .number()
                                .min(1)
                                .max(agentApplicationsRevisionsCreateBodySpecToolsItemFourTimeoutMsMax)
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemFourTimeoutMsDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsCreateBodySpecToolsDefault),
            mcps: zod
                .array(
                    zod.object({
                        id: zod.string().min(1),
                        url: zod.url(),
                        auth: zod
                            .object({
                                integration: zod.string().optional(),
                            })
                            .optional(),
                        secrets: zod
                            .array(zod.string())
                            .default(agentApplicationsRevisionsCreateBodySpecMcpsItemSecretsDefault),
                        headers: zod.record(zod.string(), zod.string()).optional(),
                        tools: zod
                            .array(
                                zod.union([
                                    zod.string().min(1),
                                    zod.object({
                                        name: zod.string().min(1),
                                        requires_approval: zod
                                            .boolean()
                                            .default(
                                                agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoRequiresApprovalDefault
                                            ),
                                        approval_policy: zod
                                            .object({
                                                approvers: zod
                                                    .array(zod.enum(['team_admins', 'session_principal']))
                                                    .min(1)
                                                    .default([`team_admins`]),
                                                allow_edit: zod
                                                    .boolean()
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowEditDefault
                                                    ),
                                                ttl_ms: zod
                                                    .number()
                                                    .min(
                                                        agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMin
                                                    )
                                                    .max(
                                                        agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMax
                                                    )
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsDefault
                                                    ),
                                                allow_agent_approver: zod
                                                    .boolean()
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowAgentApproverDefault
                                                    ),
                                            })
                                            .optional(),
                                    }),
                                ])
                            )
                            .optional(),
                    })
                )
                .default(agentApplicationsRevisionsCreateBodySpecMcpsDefault),
            skills: zod
                .array(
                    zod.object({
                        id: zod.string(),
                        path: zod.string(),
                        description: zod.string().optional(),
                        from_template: zod.string().optional(),
                        alias: zod.string().optional(),
                        version: zod
                            .number()
                            .min(agentApplicationsRevisionsCreateBodySpecSkillsItemVersionMin)
                            .optional(),
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
            auth: zod.object({
                modes: zod
                    .array(
                        zod.union([
                            zod.object({
                                type: zod.literal('public'),
                            }),
                            zod.object({
                                type: zod.literal('oauth'),
                                issuer: zod.string().min(1),
                                scopes: zod
                                    .array(zod.string())
                                    .default(agentApplicationsRevisionsCreateBodySpecAuthModesItemTwoScopesDefault),
                            }),
                            zod.object({
                                type: zod.literal('pat'),
                            }),
                            zod.object({
                                type: zod.literal('jwt'),
                                issuer_secret_ref: zod.string().min(1),
                            }),
                            zod.object({
                                type: zod.literal('shared_secret'),
                                header: zod.string().min(1),
                            }),
                            zod.object({
                                type: zod.literal('posthog_internal'),
                            }),
                        ])
                    )
                    .default(agentApplicationsRevisionsCreateBodySpecAuthModesDefault),
            }),
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
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigPromptMax = 4096

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigCatchUpDefault = `most_recent`
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsDefault = 3600
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsMax = 604800

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourConfigRequireAuthDefault = true
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveConfigDefault = {}
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemThreeVersionMin = 0

export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourArgsSchemaDefault = {}
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourRequiredDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourTimeoutMsDefault = 5000
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourTimeoutMsMax = 60000

export const agentApplicationsRevisionsPartialUpdateBodySpecToolsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemSecretsDefault = []

export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoRequiresApprovalDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowAgentApproverDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecMcpsDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecSkillsItemVersionMin = 0

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
export const agentApplicationsRevisionsPartialUpdateBodySpecAuthModesItemTwoScopesDefault = []

export const agentApplicationsRevisionsPartialUpdateBodySpecAuthModesDefault = [{ type: `public` }]

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
                                name: zod.string().min(1),
                                schedule: zod.string().min(1),
                                timezone: zod
                                    .string()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigTimezoneDefault
                                    ),
                                prompt: zod
                                    .string()
                                    .min(1)
                                    .max(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigPromptMax
                                    ),
                                external_key: zod.string().optional(),
                                catch_up: zod
                                    .enum(['all', 'most_recent', 'skip'])
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigCatchUpDefault
                                    ),
                                max_catch_up_age_seconds: zod
                                    .number()
                                    .min(1)
                                    .max(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsMax
                                    )
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsDefault
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
                            kind: zod.literal('custom_template'),
                            from_template: zod.string(),
                            alias: zod.string(),
                            version: zod
                                .number()
                                .min(agentApplicationsRevisionsPartialUpdateBodySpecToolsItemThreeVersionMin)
                                .optional(),
                        }),
                        zod.object({
                            kind: zod.literal('client'),
                            id: zod.string().min(1),
                            description: zod.string().min(1),
                            args_schema: zod
                                .looseObject({})
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourArgsSchemaDefault),
                            required: zod
                                .boolean()
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourRequiredDefault),
                            timeout_ms: zod
                                .number()
                                .min(1)
                                .max(agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourTimeoutMsMax)
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourTimeoutMsDefault),
                        }),
                    ])
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecToolsDefault),
            mcps: zod
                .array(
                    zod.object({
                        id: zod.string().min(1),
                        url: zod.url(),
                        auth: zod
                            .object({
                                integration: zod.string().optional(),
                            })
                            .optional(),
                        secrets: zod
                            .array(zod.string())
                            .default(agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemSecretsDefault),
                        headers: zod.record(zod.string(), zod.string()).optional(),
                        tools: zod
                            .array(
                                zod.union([
                                    zod.string().min(1),
                                    zod.object({
                                        name: zod.string().min(1),
                                        requires_approval: zod
                                            .boolean()
                                            .default(
                                                agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoRequiresApprovalDefault
                                            ),
                                        approval_policy: zod
                                            .object({
                                                approvers: zod
                                                    .array(zod.enum(['team_admins', 'session_principal']))
                                                    .min(1)
                                                    .default([`team_admins`]),
                                                allow_edit: zod
                                                    .boolean()
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowEditDefault
                                                    ),
                                                ttl_ms: zod
                                                    .number()
                                                    .min(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMin
                                                    )
                                                    .max(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsMax
                                                    )
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyTtlMsDefault
                                                    ),
                                                allow_agent_approver: zod
                                                    .boolean()
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecMcpsItemToolsItemTwoApprovalPolicyAllowAgentApproverDefault
                                                    ),
                                            })
                                            .optional(),
                                    }),
                                ])
                            )
                            .optional(),
                    })
                )
                .default(agentApplicationsRevisionsPartialUpdateBodySpecMcpsDefault),
            skills: zod
                .array(
                    zod.object({
                        id: zod.string(),
                        path: zod.string(),
                        description: zod.string().optional(),
                        from_template: zod.string().optional(),
                        alias: zod.string().optional(),
                        version: zod
                            .number()
                            .min(agentApplicationsRevisionsPartialUpdateBodySpecSkillsItemVersionMin)
                            .optional(),
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
            auth: zod.object({
                modes: zod
                    .array(
                        zod.union([
                            zod.object({
                                type: zod.literal('public'),
                            }),
                            zod.object({
                                type: zod.literal('oauth'),
                                issuer: zod.string().min(1),
                                scopes: zod
                                    .array(zod.string())
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecAuthModesItemTwoScopesDefault
                                    ),
                            }),
                            zod.object({
                                type: zod.literal('pat'),
                            }),
                            zod.object({
                                type: zod.literal('jwt'),
                                issuer_secret_ref: zod.string().min(1),
                            }),
                            zod.object({
                                type: zod.literal('shared_secret'),
                                header: zod.string().min(1),
                            }),
                            zod.object({
                                type: zod.literal('posthog_internal'),
                            }),
                        ])
                    )
                    .default(agentApplicationsRevisionsPartialUpdateBodySpecAuthModesDefault),
            }),
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
 * Fire one cron job out-of-band — the same execution path the
scheduler walks, but on demand. Authoring UX: the user iterates on
a cron prompt by clicking 'Fire now' rather than waiting for the
next scheduled firing. Without this, 'did my prompt do the right
thing?' is unanswerable until the cron actually fires.

Idempotent via `request_id`: repeat clicks with the same id resolve
to the same session id rather than firing N times. See
`docs/agent-platform/plans/cron-trigger-scheduler.md` §9.
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

Single atomic block now that the janitor's freeze endpoint is
side-effect-free w.r.t. `agent_revision`: (1) resolve
`spec.skills[].from_template` / `spec.tools[].from_template` refs
into the bundle (copies content, stamps versions, inserts join
rows); (2) call the janitor to compute the bundle sha (writes the
S3 `.frozen` marker, returns the sha); (3) stamp `state='ready'`
+ `bundle_sha256` on the revision row from Django. Django is the
sole writer to `agent_revision.state`, so there's no cross-process
row contention on the same row to deadlock against. Any failure
leaves the revision in `draft`; the next freeze re-runs all three
phases idempotently.
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
Auth: standard PAT / session — `agents:read` scope.
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
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary List the latest version of every custom tool template visible to the team.
 */
export const AgentCustomToolTemplatesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentCustomToolTemplatesListQueryParams = /* @__PURE__ */ zod.object({
    search: zod.string().optional().describe('Optional substring filter against name + description.'),
})

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Create a new custom tool template — produces v1.
 */
export const AgentCustomToolTemplatesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentCustomToolTemplatesCreateBodyNameMax = 128

export const agentCustomToolTemplatesCreateBodyDescriptionDefault = ``
export const agentCustomToolTemplatesCreateBodyDescriptionMax = 4096

export const agentCustomToolTemplatesCreateBodySourceDefault = ``
export const agentCustomToolTemplatesCreateBodyCompiledJsDefault = ``
export const agentCustomToolTemplatesCreateBodyRequiresSecretsItemMax = 128

export const AgentCustomToolTemplatesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentCustomToolTemplatesCreateBodyNameMax).describe('Slug-shaped name unique per team.'),
    description: zod
        .string()
        .max(agentCustomToolTemplatesCreateBodyDescriptionMax)
        .default(agentCustomToolTemplatesCreateBodyDescriptionDefault)
        .describe('One-line description.'),
    source: zod.string().default(agentCustomToolTemplatesCreateBodySourceDefault).describe('TypeScript source.'),
    compiled_js: zod
        .string()
        .default(agentCustomToolTemplatesCreateBodyCompiledJsDefault)
        .describe('Bundler output. The publisher (UI or MCP) computes this client-side.'),
    args_schema: zod.unknown().optional().describe('TypeBox / JSON Schema for tool args.'),
    returns_schema: zod.unknown().optional().describe('Optional TypeBox / JSON Schema for the return value.'),
    requires_secrets: zod
        .array(zod.string().max(agentCustomToolTemplatesCreateBodyRequiresSecretsItemMax))
        .optional()
        .describe('Names of secrets the tool reads via `ctx.secret(...)`.'),
})

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Retrieve a custom tool template's latest version, or a specific version with `?version=N`.
 */
export const agentCustomToolTemplatesNameRetrievePathNameRegExp = new RegExp('^[^/]+$')

export const AgentCustomToolTemplatesNameRetrieveParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentCustomToolTemplatesNameRetrievePathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentCustomToolTemplatesNameRetrieveQueryParams = /* @__PURE__ */ zod.object({
    version: zod.number().optional().describe('Fetch a specific version.'),
})

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Soft-delete all versions of a custom tool template.
 */
export const agentCustomToolTemplatesNameArchiveCreatePathNameRegExp = new RegExp('^[^/]+$')

export const AgentCustomToolTemplatesNameArchiveCreateParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentCustomToolTemplatesNameArchiveCreatePathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentCustomToolTemplatesNameArchiveCreateBody = /* @__PURE__ */ zod.object({
    source: zod.string().describe('TypeScript source the bundler compiles to `compiled_js`.'),
    compiled_js: zod.string().describe('Last bundle output. Copied into `bundle/tools/<alias>/compiled.js` at freeze.'),
    args_schema: zod.unknown().describe('TypeBox / JSON Schema for tool args.'),
    returns_schema: zod
        .unknown()
        .optional()
        .describe('Optional TypeBox / JSON Schema for the return value (informational).'),
})

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Duplicate a custom tool template under a new name.
 */
export const agentCustomToolTemplatesNameDuplicateCreatePathNameRegExp = new RegExp('^[^/]+$')

export const AgentCustomToolTemplatesNameDuplicateCreateParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentCustomToolTemplatesNameDuplicateCreatePathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentCustomToolTemplatesNameDuplicateCreateBodyNameMax = 128

export const agentCustomToolTemplatesNameDuplicateCreateBodyDescriptionMax = 4096

export const AgentCustomToolTemplatesNameDuplicateCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(agentCustomToolTemplatesNameDuplicateCreateBodyNameMax).describe('Slug for the duplicate.'),
    description: zod
        .string()
        .max(agentCustomToolTemplatesNameDuplicateCreateBodyDescriptionMax)
        .optional()
        .describe('Description for the new template.'),
})

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary Publish a new version of the named custom tool template.
 */
export const agentCustomToolTemplatesNamePublishCreatePathNameRegExp = new RegExp('^[^/]+$')

export const AgentCustomToolTemplatesNamePublishCreateParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentCustomToolTemplatesNamePublishCreatePathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentCustomToolTemplatesNamePublishCreateBodyDescriptionMax = 4096

export const agentCustomToolTemplatesNamePublishCreateBodyRequiresSecretsItemMax = 128

export const AgentCustomToolTemplatesNamePublishCreateBody = /* @__PURE__ */ zod.object({
    description: zod
        .string()
        .max(agentCustomToolTemplatesNamePublishCreateBodyDescriptionMax)
        .optional()
        .describe('Overrides the prior description. Omit to keep the prior value.'),
    source: zod.string().optional().describe('Full new TypeScript source. Mutually exclusive with `edits`.'),
    edits: zod
        .array(
            zod
                .object({
                    old: zod.string().describe('Text to locate (must match exactly once).'),
                    new: zod.string().describe('Replacement text.'),
                })
                .describe('Structured edit applied to source.')
        )
        .optional()
        .describe('Structured edits against the current source.'),
    compiled_js: zod
        .string()
        .optional()
        .describe('Updated bundle output. Required when `source` or `edits` are supplied.'),
    args_schema: zod.unknown().optional().describe('Overrides args_schema. Omit to keep prior value.'),
    returns_schema: zod.unknown().optional().describe('Overrides returns_schema. Omit to keep prior value.'),
    requires_secrets: zod
        .array(zod.string().max(agentCustomToolTemplatesNamePublishCreateBodyRequiresSecretsItemMax))
        .optional()
        .describe('Overrides requires_secrets. Omit to keep prior value.'),
})

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary List the frozen agent revisions pinning this custom tool template.
 */
export const agentCustomToolTemplatesNameUsagesListPathNameRegExp = new RegExp('^[^/]+$')

export const AgentCustomToolTemplatesNameUsagesListParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentCustomToolTemplatesNameUsagesListPathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentCustomToolTemplatesNameUsagesListQueryParams = /* @__PURE__ */ zod.object({
    pinned_version: zod.number().optional().describe('Filter to a specific pinned version.'),
})

/**
 * Shared, versioned TypeScript custom tool templates.

URLs:
    GET    /api/projects/<team>/agent_custom_tool_templates/
    POST   /api/projects/<team>/agent_custom_tool_templates/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_custom_tool_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_custom_tool_templates/name/<name>/usages/
 * @summary List every version of the named custom tool template, newest first.
 */
export const agentCustomToolTemplatesNameVersionsListPathNameRegExp = new RegExp('^[^/]+$')

export const AgentCustomToolTemplatesNameVersionsListParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentCustomToolTemplatesNameVersionsListPathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary List the latest version of every skill template visible to the team.
 */
export const AgentSkillTemplatesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentSkillTemplatesListQueryParams = /* @__PURE__ */ zod.object({
    search: zod.string().optional().describe('Optional substring filter against name + description.'),
})

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Create a new skill template — produces v1.
 */
export const AgentSkillTemplatesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentSkillTemplatesCreateBodyNameMax = 64

export const agentSkillTemplatesCreateBodyDescriptionMax = 1024

export const agentSkillTemplatesCreateBodyBodyDefault = ``
export const agentSkillTemplatesCreateBodyLicenseDefault = ``
export const agentSkillTemplatesCreateBodyLicenseMax = 256

export const agentSkillTemplatesCreateBodyCompatibilityDefault = ``
export const agentSkillTemplatesCreateBodyCompatibilityMax = 500

export const agentSkillTemplatesCreateBodyFilesItemPathMax = 512

export const agentSkillTemplatesCreateBodyFilesItemContentTypeDefault = `text/plain`
export const agentSkillTemplatesCreateBodyFilesItemContentTypeMax = 128

export const AgentSkillTemplatesCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(agentSkillTemplatesCreateBodyNameMax)
            .describe(
                'Slug-shaped name unique per team (max 64 chars, per the Agent Skills spec). `@posthog/<slug>` is reserved for canonical templates.'
            ),
        description: zod
            .string()
            .max(agentSkillTemplatesCreateBodyDescriptionMax)
            .describe(
                'Required description (1–1024 chars, per the Agent Skills spec) — what the skill does and when to use it. Shown in the list view + system-prompt skill index.'
            ),
        body: zod
            .string()
            .default(agentSkillTemplatesCreateBodyBodyDefault)
            .describe(
                'Initial SKILL.md markdown body. Any leading YAML frontmatter is stripped at freeze — frontmatter is assembled from the structured fields.'
            ),
        license: zod
            .string()
            .max(agentSkillTemplatesCreateBodyLicenseMax)
            .default(agentSkillTemplatesCreateBodyLicenseDefault)
            .describe('Agent Skills `license` frontmatter — license name or a reference to a bundled license file.'),
        compatibility: zod
            .string()
            .max(agentSkillTemplatesCreateBodyCompatibilityMax)
            .default(agentSkillTemplatesCreateBodyCompatibilityDefault)
            .describe(
                'Agent Skills `compatibility` frontmatter — environment requirements (intended product, packages, network access). Max 500 chars.'
            ),
        files: zod
            .array(
                zod.object({
                    id: zod.string().optional(),
                    path: zod
                        .string()
                        .max(agentSkillTemplatesCreateBodyFilesItemPathMax)
                        .describe(
                            'Relative path inside the skill folder; may include subfolders (e.g. `references/api.md`, `scripts/run.py`, `assets/x/y.json`). Becomes `bundle/skills/<alias>/<path>` at freeze. No `..` traversal or absolute paths.'
                        ),
                    content: zod
                        .string()
                        .describe(
                            'File body. Plain text or markdown — companion files are not interpreted by the runner.'
                        ),
                    content_type: zod
                        .string()
                        .max(agentSkillTemplatesCreateBodyFilesItemContentTypeMax)
                        .default(agentSkillTemplatesCreateBodyFilesItemContentTypeDefault)
                        .describe("MIME type hint. Read-only at runtime; aids the registry UI's file viewer."),
                })
            )
            .optional()
            .describe(
                'Optional companion files (scripts/, references/, assets/ — arbitrarily nested) at creation time.'
            ),
        metadata: zod
            .unknown()
            .optional()
            .describe('Agent Skills `metadata` map (string → string) for non-promoted keys like author or version.'),
        allowed_tools: zod
            .unknown()
            .optional()
            .describe(
                "Optional list of tool ids the skill expects to reach for. Emitted as the spec's space-separated `allowed-tools` frontmatter at freeze."
            ),
    })
    .describe('Initial-create payload — produces v1.')

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Retrieve a skill template's latest version, or a specific version with `?version=N`.
 */
export const agentSkillTemplatesNameRetrievePathNameRegExp = new RegExp('^[^/]+$')

export const AgentSkillTemplatesNameRetrieveParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentSkillTemplatesNameRetrievePathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentSkillTemplatesNameRetrieveQueryParams = /* @__PURE__ */ zod.object({
    version: zod.number().optional().describe('Fetch a specific version. Omit for the current `is_latest=true` row.'),
})

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Soft-delete all versions of a template.
 */
export const agentSkillTemplatesNameArchiveCreatePathNameRegExp = new RegExp('^[^/]+$')

export const AgentSkillTemplatesNameArchiveCreateParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentSkillTemplatesNameArchiveCreatePathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentSkillTemplatesNameArchiveCreateBody = /* @__PURE__ */ zod
    .object({
        license: zod
            .string()
            .describe(
                'Agent Skills `license` frontmatter — license name or a reference to a bundled license file. Blank if unset.'
            ),
        compatibility: zod
            .string()
            .describe(
                'Agent Skills `compatibility` frontmatter — environment requirements (intended product, packages, network). Blank if unset.'
            ),
        body: zod.string().describe('Markdown body. The `SKILL.md` equivalent.'),
    })
    .describe('Detail shape: adds body + files. Used by the registry detail page.')

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Duplicate a template under a new name (clones the latest version's content + files).
 */
export const agentSkillTemplatesNameDuplicateCreatePathNameRegExp = new RegExp('^[^/]+$')

export const AgentSkillTemplatesNameDuplicateCreateParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentSkillTemplatesNameDuplicateCreatePathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentSkillTemplatesNameDuplicateCreateBodyNameMax = 64

export const agentSkillTemplatesNameDuplicateCreateBodyDescriptionMax = 1024

export const AgentSkillTemplatesNameDuplicateCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(agentSkillTemplatesNameDuplicateCreateBodyNameMax)
        .describe('Slug for the new duplicate (max 64 chars). Must not collide with an existing template.'),
    description: zod
        .string()
        .max(agentSkillTemplatesNameDuplicateCreateBodyDescriptionMax)
        .optional()
        .describe("Description for the new template (1–1024 chars, non-empty). Omit to keep the source's description."),
})

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Add a companion file to the latest version of the template.
 */
export const agentSkillTemplatesNameFilesCreatePathNameRegExp = new RegExp('^[^/]+$')

export const AgentSkillTemplatesNameFilesCreateParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentSkillTemplatesNameFilesCreatePathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentSkillTemplatesNameFilesCreateBodyPathMax = 512

export const agentSkillTemplatesNameFilesCreateBodyContentTypeDefault = `text/plain`
export const agentSkillTemplatesNameFilesCreateBodyContentTypeMax = 128

export const AgentSkillTemplatesNameFilesCreateBody = /* @__PURE__ */ zod.object({
    path: zod
        .string()
        .max(agentSkillTemplatesNameFilesCreateBodyPathMax)
        .describe(
            'Relative path inside the skill folder; may include subfolders (e.g. `references/api.md`, `scripts/run.py`). No `..` traversal or absolute paths.'
        ),
    content: zod.string().describe('File body.'),
    content_type: zod
        .string()
        .max(agentSkillTemplatesNameFilesCreateBodyContentTypeMax)
        .default(agentSkillTemplatesNameFilesCreateBodyContentTypeDefault)
        .describe('MIME type hint.'),
})

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Rename a companion file inside the latest version of the template.
 */
export const agentSkillTemplatesNameFilesRenameCreatePathNameRegExp = new RegExp('^[^/]+$')

export const AgentSkillTemplatesNameFilesRenameCreateParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentSkillTemplatesNameFilesRenameCreatePathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentSkillTemplatesNameFilesRenameCreateBodyFromPathMax = 512

export const agentSkillTemplatesNameFilesRenameCreateBodyToPathMax = 512

export const AgentSkillTemplatesNameFilesRenameCreateBody = /* @__PURE__ */ zod.object({
    from_path: zod
        .string()
        .max(agentSkillTemplatesNameFilesRenameCreateBodyFromPathMax)
        .describe('Existing file path inside the skill folder (subfolders allowed).'),
    to_path: zod
        .string()
        .max(agentSkillTemplatesNameFilesRenameCreateBodyToPathMax)
        .describe(
            'New path (subfolders allowed); may move the file between subfolders. Must not collide with another file.'
        ),
})

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Remove a companion file from the latest version of the template.
 */
export const agentSkillTemplatesNameFilesDestroyPathFilePathRegExp = new RegExp('^.+?$')
export const agentSkillTemplatesNameFilesDestroyPathNameRegExp = new RegExp('^[^/]+$')

export const AgentSkillTemplatesNameFilesDestroyParams = /* @__PURE__ */ zod.object({
    file_path: zod.string().regex(agentSkillTemplatesNameFilesDestroyPathFilePathRegExp),
    name: zod.string().regex(agentSkillTemplatesNameFilesDestroyPathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary Publish a new version of the named template.
 */
export const agentSkillTemplatesNamePublishCreatePathNameRegExp = new RegExp('^[^/]+$')

export const AgentSkillTemplatesNamePublishCreateParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentSkillTemplatesNamePublishCreatePathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const agentSkillTemplatesNamePublishCreateBodyDescriptionMax = 1024

export const agentSkillTemplatesNamePublishCreateBodyLicenseMax = 256

export const agentSkillTemplatesNamePublishCreateBodyCompatibilityMax = 500

export const AgentSkillTemplatesNamePublishCreateBody = /* @__PURE__ */ zod
    .object({
        description: zod
            .string()
            .max(agentSkillTemplatesNamePublishCreateBodyDescriptionMax)
            .optional()
            .describe('Overrides the prior description (1–1024 chars, non-empty). Omit to keep the prior value.'),
        body: zod.string().optional().describe('Full new body. Mutually exclusive with `edits`.'),
        edits: zod
            .array(
                zod
                    .object({
                        old: zod.string().describe('Text to locate (must match exactly once).'),
                        new: zod.string().describe('Replacement text.'),
                        file_path: zod
                            .string()
                            .nullish()
                            .describe(
                                'Apply this edit to a companion file instead of the body. Null/omitted = body edit.'
                            ),
                    })
                    .describe("A single find/replace edit applied to body or a file's content.")
            )
            .optional()
            .describe('Structured edits. Each `old` must match exactly once in the current body / file.'),
        license: zod
            .string()
            .max(agentSkillTemplatesNamePublishCreateBodyLicenseMax)
            .optional()
            .describe('Overrides the `license` frontmatter. Omit to keep the prior value.'),
        compatibility: zod
            .string()
            .max(agentSkillTemplatesNamePublishCreateBodyCompatibilityMax)
            .optional()
            .describe('Overrides the `compatibility` frontmatter (max 500 chars). Omit to keep the prior value.'),
        metadata: zod.unknown().optional().describe('Overrides the metadata map. Omit to keep the prior value.'),
        allowed_tools: zod.unknown().optional().describe('Overrides allowed_tools. Omit to keep the prior value.'),
    })
    .describe(
        'Publish a new version.\n\nSupply EITHER `body` (full overwrite) OR `edits` (structured\nfind/replace). The viewset rejects requests carrying both.'
    )

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary List the frozen agent revisions pinning this template (any version, or filtered by `pinned_version`).
 */
export const agentSkillTemplatesNameUsagesListPathNameRegExp = new RegExp('^[^/]+$')

export const AgentSkillTemplatesNameUsagesListParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentSkillTemplatesNameUsagesListPathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const AgentSkillTemplatesNameUsagesListQueryParams = /* @__PURE__ */ zod.object({
    pinned_version: zod
        .number()
        .optional()
        .describe('Filter to revisions stuck on a specific version (`/?pinned_version=3`).'),
})

/**
 * Shared, versioned markdown skill templates.

URLs:
    GET    /api/projects/<team>/agent_skill_templates/
    POST   /api/projects/<team>/agent_skill_templates/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/publish/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/archive/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/duplicate/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/versions/
    GET    /api/projects/<team>/agent_skill_templates/name/<name>/usages/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files/
    DELETE /api/projects/<team>/agent_skill_templates/name/<name>/files/<path>/
    POST   /api/projects/<team>/agent_skill_templates/name/<name>/files-rename/

Canonical (`@posthog/<name>`) templates are read-only for team
members; only PostHog-side seed commands write them.
 * @summary List every version of the named template, newest first.
 */
export const agentSkillTemplatesNameVersionsListPathNameRegExp = new RegExp('^[^/]+$')

export const AgentSkillTemplatesNameVersionsListParams = /* @__PURE__ */ zod.object({
    name: zod.string().regex(agentSkillTemplatesNameVersionsListPathNameRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
