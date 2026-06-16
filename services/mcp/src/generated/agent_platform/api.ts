/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 34 enabled ops
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
export const agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigMentionOnlyDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigAutoResumeThreadsDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigAllowWorkspaceParticipantsDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigAllowDirectMessagesDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemTwoAuthModesItemTwoScopesDefault = []

export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigTimezoneDefault = `UTC`
export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigPromptMax = 4096

export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigCatchUpDefault = `most_recent`
export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsDefault = 3600
export const agentApplicationsRevisionsCreateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsMax = 604800

export const agentApplicationsRevisionsCreateBodySpecTriggersItemFourConfigAllowRestartDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFourConfigDefault = { allow_restart: false }
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFourAuthModesItemTwoScopesDefault = []

export const agentApplicationsRevisionsCreateBodySpecTriggersItemFiveConfigAllowRestartDefault = false
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFiveConfigDefault = { allow_restart: false }
export const agentApplicationsRevisionsCreateBodySpecTriggersItemFiveAuthModesItemTwoScopesDefault = []

export const agentApplicationsRevisionsCreateBodySpecTriggersDefault = []
export const agentApplicationsRevisionsCreateBodySpecToolsItemOneRequiresApprovalDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyAllowAgentApproverDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemTwoRequiresApprovalDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyAllowAgentApproverDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemThreeVersionMin = 0

export const agentApplicationsRevisionsCreateBodySpecToolsItemFourArgsSchemaDefault = {}
export const agentApplicationsRevisionsCreateBodySpecToolsItemFourRequiredDefault = false
export const agentApplicationsRevisionsCreateBodySpecToolsItemFourTimeoutMsDefault = 5000
export const agentApplicationsRevisionsCreateBodySpecToolsItemFourTimeoutMsMax = 600000

export const agentApplicationsRevisionsCreateBodySpecToolsItemFourInteractiveDefault = false
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

export const agentApplicationsRevisionsCreateBodySpecLimitsMaxOutputTokensExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxOutputTokensMax = 200000

export const agentApplicationsRevisionsCreateBodySpecLimitsMaxMemoryMbDefault = 512
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxMemoryMbExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxMemoryMbMax = 2147483647

export const agentApplicationsRevisionsCreateBodySpecLimitsMaxCpuCoresDefault = 0.25
export const agentApplicationsRevisionsCreateBodySpecLimitsMaxCpuCoresExclusiveMin = 0

export const agentApplicationsRevisionsCreateBodySpecLimitsDefault = {
    max_turns: 50,
    max_tool_calls: 200,
    max_wall_seconds: 900,
    max_memory_mb: 512,
    max_cpu_cores: 0.25,
}
export const agentApplicationsRevisionsCreateBodySpecEntrypointDefault = `agent.md`
export const agentApplicationsRevisionsCreateBodySpecFrameworkPromptOmitDefault = []
export const agentApplicationsRevisionsCreateBodySpecFrameworkPromptVersionPinExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecFrameworkPromptVersionPinMax = 2147483647

export const agentApplicationsRevisionsCreateBodySpecResumeEnabledDefault = false
export const agentApplicationsRevisionsCreateBodySpecResumeMaxCompletedAgeMsDefault = 604800000
export const agentApplicationsRevisionsCreateBodySpecResumeMaxCompletedAgeMsExclusiveMin = 0
export const agentApplicationsRevisionsCreateBodySpecResumeMaxCompletedAgeMsMax = 2147483647

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
                                auto_resume_threads: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigAutoResumeThreadsDefault
                                    ),
                                allow_workspace_participants: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigAllowWorkspaceParticipantsDefault
                                    ),
                                ack_reaction: zod.string().optional(),
                                allow_direct_messages: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsCreateBodySpecTriggersItemOneConfigAllowDirectMessagesDefault
                                    ),
                                trusted_workspaces: zod.union([zod.array(zod.string()).min(1), zod.literal('*')]),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('webhook'),
                            config: zod.object({
                                path: zod.string(),
                            }),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecTriggersItemTwoAuthModesItemTwoScopesDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
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
                            config: zod
                                .object({
                                    allow_restart: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecTriggersItemFourConfigAllowRestartDefault
                                        ),
                                })
                                .default(agentApplicationsRevisionsCreateBodySpecTriggersItemFourConfigDefault),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecTriggersItemFourAuthModesItemTwoScopesDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('mcp'),
                            config: zod
                                .object({
                                    allow_restart: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecTriggersItemFiveConfigAllowRestartDefault
                                        ),
                                })
                                .default(agentApplicationsRevisionsCreateBodySpecTriggersItemFiveConfigDefault),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsCreateBodySpecTriggersItemFiveAuthModesItemTwoScopesDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
                            }),
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
                            requires_approval: zod
                                .boolean()
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemOneRequiresApprovalDefault),
                            approval_policy: zod
                                .object({
                                    approvers: zod
                                        .array(zod.enum(['team_admins', 'session_principal']))
                                        .min(1)
                                        .default([`team_admins`]),
                                    allow_edit: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyAllowEditDefault
                                        ),
                                    ttl_ms: zod
                                        .number()
                                        .min(agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTtlMsMin)
                                        .max(agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTtlMsMax)
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyTtlMsDefault
                                        ),
                                    allow_agent_approver: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecToolsItemOneApprovalPolicyAllowAgentApproverDefault
                                        ),
                                })
                                .optional(),
                        }),
                        zod.object({
                            kind: zod.literal('custom'),
                            id: zod.string(),
                            path: zod.string(),
                            requires_approval: zod
                                .boolean()
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemTwoRequiresApprovalDefault),
                            approval_policy: zod
                                .object({
                                    approvers: zod
                                        .array(zod.enum(['team_admins', 'session_principal']))
                                        .min(1)
                                        .default([`team_admins`]),
                                    allow_edit: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyAllowEditDefault
                                        ),
                                    ttl_ms: zod
                                        .number()
                                        .min(agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTtlMsMin)
                                        .max(agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTtlMsMax)
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyTtlMsDefault
                                        ),
                                    allow_agent_approver: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsCreateBodySpecToolsItemTwoApprovalPolicyAllowAgentApproverDefault
                                        ),
                                })
                                .optional(),
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
                            interactive: zod
                                .boolean()
                                .default(agentApplicationsRevisionsCreateBodySpecToolsItemFourInteractiveDefault),
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
                    max_output_tokens: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecLimitsMaxOutputTokensExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecLimitsMaxOutputTokensMax)
                        .optional(),
                    max_memory_mb: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecLimitsMaxMemoryMbExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecLimitsMaxMemoryMbMax)
                        .default(agentApplicationsRevisionsCreateBodySpecLimitsMaxMemoryMbDefault),
                    max_cpu_cores: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecLimitsMaxCpuCoresExclusiveMin)
                        .default(agentApplicationsRevisionsCreateBodySpecLimitsMaxCpuCoresDefault),
                })
                .default(agentApplicationsRevisionsCreateBodySpecLimitsDefault),
            entrypoint: zod.string().default(agentApplicationsRevisionsCreateBodySpecEntrypointDefault),
            reasoning: zod.enum(['minimal', 'low', 'medium', 'high', 'xhigh']).optional(),
            framework_prompt: zod
                .object({
                    omit: zod
                        .array(
                            zod.enum([
                                'meta_tool_guidance',
                                'state_contract',
                                'tool_failure_guidance',
                                'approval_guidance',
                                'reasoning_hint',
                            ])
                        )
                        .default(agentApplicationsRevisionsCreateBodySpecFrameworkPromptOmitDefault),
                    version_pin: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecFrameworkPromptVersionPinExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecFrameworkPromptVersionPinMax)
                        .optional(),
                })
                .optional(),
            resume: zod
                .object({
                    enabled: zod.boolean().default(agentApplicationsRevisionsCreateBodySpecResumeEnabledDefault),
                    max_completed_age_ms: zod
                        .number()
                        .gt(agentApplicationsRevisionsCreateBodySpecResumeMaxCompletedAgeMsExclusiveMin)
                        .max(agentApplicationsRevisionsCreateBodySpecResumeMaxCompletedAgeMsMax)
                        .default(agentApplicationsRevisionsCreateBodySpecResumeMaxCompletedAgeMsDefault),
                })
                .optional(),
        })
        .optional(),
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

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigMentionOnlyDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigAutoResumeThreadsDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigAllowWorkspaceParticipantsDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigAllowDirectMessagesDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemTwoAuthModesItemTwoScopesDefault = []

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigTimezoneDefault = `UTC`
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigPromptMax = 4096

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigCatchUpDefault = `most_recent`
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsDefault = 3600
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemThreeConfigMaxCatchUpAgeSecondsMax = 604800

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourConfigAllowRestartDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourConfigDefault = { allow_restart: false }
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourAuthModesItemTwoScopesDefault = []

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveConfigAllowRestartDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveConfigDefault = { allow_restart: false }
export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveAuthModesItemTwoScopesDefault = []

export const agentApplicationsRevisionsPartialUpdateBodySpecTriggersDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneRequiresApprovalDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyAllowAgentApproverDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoRequiresApprovalDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyAllowEditDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsDefault = 86400000
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsMin = 60000
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsMax = 604800000

export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyAllowAgentApproverDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemThreeVersionMin = 0

export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourArgsSchemaDefault = {}
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourRequiredDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourTimeoutMsDefault = 5000
export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourTimeoutMsMax = 600000

export const agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourInteractiveDefault = false
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

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxOutputTokensExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxOutputTokensMax = 200000

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxMemoryMbDefault = 512
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxMemoryMbExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxMemoryMbMax = 2147483647

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxCpuCoresDefault = 0.25
export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxCpuCoresExclusiveMin = 0

export const agentApplicationsRevisionsPartialUpdateBodySpecLimitsDefault = {
    max_turns: 50,
    max_tool_calls: 200,
    max_wall_seconds: 900,
    max_memory_mb: 512,
    max_cpu_cores: 0.25,
}
export const agentApplicationsRevisionsPartialUpdateBodySpecEntrypointDefault = `agent.md`
export const agentApplicationsRevisionsPartialUpdateBodySpecFrameworkPromptOmitDefault = []
export const agentApplicationsRevisionsPartialUpdateBodySpecFrameworkPromptVersionPinExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecFrameworkPromptVersionPinMax = 2147483647

export const agentApplicationsRevisionsPartialUpdateBodySpecResumeEnabledDefault = false
export const agentApplicationsRevisionsPartialUpdateBodySpecResumeMaxCompletedAgeMsDefault = 604800000
export const agentApplicationsRevisionsPartialUpdateBodySpecResumeMaxCompletedAgeMsExclusiveMin = 0
export const agentApplicationsRevisionsPartialUpdateBodySpecResumeMaxCompletedAgeMsMax = 2147483647

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
                                auto_resume_threads: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigAutoResumeThreadsDefault
                                    ),
                                allow_workspace_participants: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigAllowWorkspaceParticipantsDefault
                                    ),
                                ack_reaction: zod.string().optional(),
                                allow_direct_messages: zod
                                    .boolean()
                                    .default(
                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemOneConfigAllowDirectMessagesDefault
                                    ),
                                trusted_workspaces: zod.union([zod.array(zod.string()).min(1), zod.literal('*')]),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('webhook'),
                            config: zod.object({
                                path: zod.string(),
                            }),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemTwoAuthModesItemTwoScopesDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
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
                            config: zod
                                .object({
                                    allow_restart: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourConfigAllowRestartDefault
                                        ),
                                })
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourConfigDefault),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFourAuthModesItemTwoScopesDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
                            }),
                        }),
                        zod.object({
                            type: zod.literal('mcp'),
                            config: zod
                                .object({
                                    allow_restart: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveConfigAllowRestartDefault
                                        ),
                                })
                                .default(agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveConfigDefault),
                            auth: zod.object({
                                modes: zod
                                    .array(
                                        zod.union([
                                            zod.object({
                                                type: zod.literal('public'),
                                                acknowledge_public_exposure: zod.boolean(),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog'),
                                                scopes: zod
                                                    .array(zod.string())
                                                    .default(
                                                        agentApplicationsRevisionsPartialUpdateBodySpecTriggersItemFiveAuthModesItemTwoScopesDefault
                                                    ),
                                            }),
                                            zod.object({
                                                type: zod.literal('jwt'),
                                                issuer_secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('shared_secret'),
                                                header: zod.string().min(1),
                                                secret_ref: zod.string().min(1),
                                            }),
                                            zod.object({
                                                type: zod.literal('posthog_internal'),
                                            }),
                                        ])
                                    )
                                    .optional(),
                            }),
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
                            requires_approval: zod
                                .boolean()
                                .default(
                                    agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneRequiresApprovalDefault
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
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyAllowEditDefault
                                        ),
                                    ttl_ms: zod
                                        .number()
                                        .min(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTtlMsMin
                                        )
                                        .max(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTtlMsMax
                                        )
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyTtlMsDefault
                                        ),
                                    allow_agent_approver: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemOneApprovalPolicyAllowAgentApproverDefault
                                        ),
                                })
                                .optional(),
                        }),
                        zod.object({
                            kind: zod.literal('custom'),
                            id: zod.string(),
                            path: zod.string(),
                            requires_approval: zod
                                .boolean()
                                .default(
                                    agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoRequiresApprovalDefault
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
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyAllowEditDefault
                                        ),
                                    ttl_ms: zod
                                        .number()
                                        .min(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsMin
                                        )
                                        .max(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsMax
                                        )
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyTtlMsDefault
                                        ),
                                    allow_agent_approver: zod
                                        .boolean()
                                        .default(
                                            agentApplicationsRevisionsPartialUpdateBodySpecToolsItemTwoApprovalPolicyAllowAgentApproverDefault
                                        ),
                                })
                                .optional(),
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
                            interactive: zod
                                .boolean()
                                .default(
                                    agentApplicationsRevisionsPartialUpdateBodySpecToolsItemFourInteractiveDefault
                                ),
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
                    max_output_tokens: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxOutputTokensExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxOutputTokensMax)
                        .optional(),
                    max_memory_mb: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxMemoryMbExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxMemoryMbMax)
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxMemoryMbDefault),
                    max_cpu_cores: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxCpuCoresExclusiveMin)
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsMaxCpuCoresDefault),
                })
                .default(agentApplicationsRevisionsPartialUpdateBodySpecLimitsDefault),
            entrypoint: zod.string().default(agentApplicationsRevisionsPartialUpdateBodySpecEntrypointDefault),
            reasoning: zod.enum(['minimal', 'low', 'medium', 'high', 'xhigh']).optional(),
            framework_prompt: zod
                .object({
                    omit: zod
                        .array(
                            zod.enum([
                                'meta_tool_guidance',
                                'state_contract',
                                'tool_failure_guidance',
                                'approval_guidance',
                                'reasoning_hint',
                            ])
                        )
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecFrameworkPromptOmitDefault),
                    version_pin: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecFrameworkPromptVersionPinExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecFrameworkPromptVersionPinMax)
                        .optional(),
                })
                .optional(),
            resume: zod
                .object({
                    enabled: zod.boolean().default(agentApplicationsRevisionsPartialUpdateBodySpecResumeEnabledDefault),
                    max_completed_age_ms: zod
                        .number()
                        .gt(agentApplicationsRevisionsPartialUpdateBodySpecResumeMaxCompletedAgeMsExclusiveMin)
                        .max(agentApplicationsRevisionsPartialUpdateBodySpecResumeMaxCompletedAgeMsMax)
                        .default(agentApplicationsRevisionsPartialUpdateBodySpecResumeMaxCompletedAgeMsDefault),
                })
                .optional(),
        })
        .optional(),
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
        skills: zod
            .array(
                zod
                    .object({
                        description: zod
                            .string()
                            .describe(
                                'One-line summary shown in the skill index; the model uses it to decide when to load the skill.'
                            ),
                        body: zod
                            .string()
                            .describe("The skill's full markdown body, stored at `skills/<skill_id>/SKILL.md`."),
                    })
                    .describe(
                        'Body shape for PUT /revisions/<id>/skills/<skill_id>/. The body is stored\nat the canonical `skills/<skill_id>/SKILL.md` path in the bundle.'
                    )
            )
            .optional(),
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
    .describe('Body shape for PUT /revisions/<id>/bundle/ — the full-replace typed\npayload.')

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
export const agentApplicationsRevisionsSkillsUpdatePathSkillIdRegExp = new RegExp('^[a-z0-9][a-z0-9_-]*$')

export const AgentApplicationsRevisionsSkillsUpdateParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    skill_id: zod.string().regex(agentApplicationsRevisionsSkillsUpdatePathSkillIdRegExp),
})

export const AgentApplicationsRevisionsSkillsUpdateBody = /* @__PURE__ */ zod
    .object({
        description: zod
            .string()
            .describe('One-line summary shown in the skill index; the model uses it to decide when to load the skill.'),
        body: zod.string().describe("The skill's full markdown body, stored at `skills/<skill_id>/SKILL.md`."),
    })
    .describe(
        'Body shape for PUT /revisions/<id>/skills/<skill_id>/. The body is stored\nat the canonical `skills/<skill_id>/SKILL.md` path in the bundle.'
    )

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
export const agentApplicationsRevisionsSkillsDestroyPathSkillIdRegExp = new RegExp('^[a-z0-9][a-z0-9_-]*$')

export const AgentApplicationsRevisionsSkillsDestroyParams = /* @__PURE__ */ zod.object({
    application_id: zod.string(),
    id: zod.string().describe('A UUID string identifying this agent revision.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    skill_id: zod.string().regex(agentApplicationsRevisionsSkillsDestroyPathSkillIdRegExp),
})

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
 * Pre-flight checks before freeze + promote: entrypoint file exists,
 * every native tool id is registered, every custom tool has its
 * compiled.js + schema.json, every skill path exists, every declared
 * secret has a value set in the application's env block. Returns
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
 * List the names of secrets currently set on the application.
 *
 * Returns names only — values stay server-side under
 * `EncryptedTextField`. Use this to drive the "set / unset" badge
 * next to a declared secret in the editor UI.
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
 *
 * - `GET`    → `{ key, is_set }` (never returns the value).
 * - `PUT`    → upserts `{ value }` into the env block.
 * - `DELETE` → removes the key. No-op when it wasn't set.
 *
 * Per-method scope: GET is treated as a write action so the
 * single action name maps to one consistent scope; reading whether
 * a secret is set is restricted to writers in any case.
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
 *
 * - `GET`    → `{ key, is_set }` (never returns the value).
 * - `PUT`    → upserts `{ value }` into the env block.
 * - `DELETE` → removes the key. No-op when it wasn't set.
 *
 * Per-method scope: GET is treated as a write action so the
 * single action name maps to one consistent scope; reading whether
 * a secret is set is restricted to writers in any case.
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
 *
 * Closes the anonymous-draft-invoke gap: the public ingress URL refuses
 * non-live invokes that don't carry the `x-agent-preview-secret` header;
 * this proxy attaches it after authenticating the Django caller.
 *
 * URL: `/api/projects/<team>/agent_applications/<app>/preview-proxy/<rest>`
 * Auth: standard PAT / session — `agents:read` scope.
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
 * Read-only catalog of every @posthog/* native tool the runner knows.
 */
export const AgentNativeToolsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
