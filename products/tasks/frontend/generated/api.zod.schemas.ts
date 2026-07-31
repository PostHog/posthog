/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export const codeInviteRedeemRequestApiCodeMax = 50

export const CodeInviteRedeemRequestApi = zod.object({
    code: zod.string().max(codeInviteRedeemRequestApiCodeMax),
})

export type CodeInviteRedeemRequestApi = zod.input<typeof CodeInviteRedeemRequestApi>
export type CodeInviteRedeemRequestApiOutput = zod.output<typeof CodeInviteRedeemRequestApi>

export const LimitTypeEnumApi = zod
    .enum(['burst', 'sustained'])
    .describe('\* `burst` - burst\n\* `sustained` - sustained')

export type LimitTypeEnumApi = zod.input<typeof LimitTypeEnumApi>
export type LimitTypeEnumApiOutput = zod.output<typeof LimitTypeEnumApi>

export const TaskRunErrorResponseApi = zod.object({
    detail: zod.string().optional().describe('Human-readable validation error'),
    error: zod.string().optional().describe('Human-readable error message'),
    type: zod.string().optional().describe('Machine-readable error type'),
    code: zod.string().optional().describe('Machine-readable error code'),
    attr: zod.string().optional().describe('Request field associated with the error'),
    missing_artifact_ids: zod
        .array(zod.string())
        .optional()
        .describe('Artifact ids that could not be resolved for the run'),
    limit_type: LimitTypeEnumApi.optional().describe(
        "Which usage limit was hit on a rate_limited error: 'burst' (daily) or 'sustained' (monthly)\n\n\* `burst` - burst\n\* `sustained` - sustained"
    ),
    reset_at: zod.string().optional().describe('ISO 8601 timestamp when the hit usage limit resets, when known'),
    is_pro: zod.boolean().optional().describe('Whether the team is on a Pro plan (drives the upgrade-prompt copy)'),
})

export type TaskRunErrorResponseApi = zod.input<typeof TaskRunErrorResponseApi>
export type TaskRunErrorResponseApiOutput = zod.output<typeof TaskRunErrorResponseApi>

export const LoopRepositoryEntryDTOApi = zod.object({
    github_integration_id: zod.number(),
    full_name: zod.string(),
})

export type LoopRepositoryEntryDTOApi = zod.input<typeof LoopRepositoryEntryDTOApi>
export type LoopRepositoryEntryDTOApiOutput = zod.output<typeof LoopRepositoryEntryDTOApi>

export const LoopBehaviorsDTOApi = zod.object({
    create_prs: zod.boolean().optional(),
    watch_ci: zod.boolean().optional(),
    fix_review_comments: zod.boolean().optional(),
    max_fix_iterations: zod.number().optional(),
})

export type LoopBehaviorsDTOApi = zod.input<typeof LoopBehaviorsDTOApi>
export type LoopBehaviorsDTOApiOutput = zod.output<typeof LoopBehaviorsDTOApi>

export const LoopConnectorsDTOApi = zod.object({
    mcp_installation_ids: zod.array(zod.string()).optional(),
    posthog_mcp_scopes: zod.string().optional(),
})

export type LoopConnectorsDTOApi = zod.input<typeof LoopConnectorsDTOApi>
export type LoopConnectorsDTOApiOutput = zod.output<typeof LoopConnectorsDTOApi>

export const LoopNotificationChannelDTOApi = zod.object({
    enabled: zod.boolean().optional(),
    events: zod.array(zod.string()).optional(),
    params: zod.record(zod.string(), zod.unknown()).optional(),
})

export type LoopNotificationChannelDTOApi = zod.input<typeof LoopNotificationChannelDTOApi>
export type LoopNotificationChannelDTOApiOutput = zod.output<typeof LoopNotificationChannelDTOApi>

export const LoopNotificationsDTOApi = zod.object({
    push: LoopNotificationChannelDTOApi,
    email: LoopNotificationChannelDTOApi,
    slack: LoopNotificationChannelDTOApi,
})

export type LoopNotificationsDTOApi = zod.input<typeof LoopNotificationsDTOApi>
export type LoopNotificationsDTOApiOutput = zod.output<typeof LoopNotificationsDTOApi>

export const LoopContextOutputsDTOApi = zod.object({
    post_to_feed: zod.boolean().optional(),
    update_context: zod.boolean().optional(),
    canvas_id: zod.string().nullish(),
})

export type LoopContextOutputsDTOApi = zod.input<typeof LoopContextOutputsDTOApi>
export type LoopContextOutputsDTOApiOutput = zod.output<typeof LoopContextOutputsDTOApi>

export const LoopContextTargetDTOApi = zod.object({
    outputs: LoopContextOutputsDTOApi.describe('What the loop maintains in this context each run.'),
    folder_id: zod.string(),
    name: zod.string(),
})

export type LoopContextTargetDTOApi = zod.input<typeof LoopContextTargetDTOApi>
export type LoopContextTargetDTOApiOutput = zod.output<typeof LoopContextTargetDTOApi>

export const LoopTriggerDTOApi = zod
    .object({
        id: zod.uuid(),
        loop_id: zod.uuid(),
        type: zod.string(),
        enabled: zod.boolean(),
        config: zod.record(zod.string(), zod.unknown()),
        schedule_sync_status: zod.string().nullable(),
        last_fired_at: zod.iso.datetime({ offset: true }).nullable(),
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
    })
    .describe('Read response for a single loop trigger.')

export type LoopTriggerDTOApi = zod.input<typeof LoopTriggerDTOApi>
export type LoopTriggerDTOApiOutput = zod.output<typeof LoopTriggerDTOApi>

export const LoopSkillBundleDTOApi = zod.object({
    id: zod.string(),
    skill_name: zod.string(),
    skill_source: zod.string(),
    size: zod.number(),
    content_sha256: zod.string(),
    uploaded_at: zod.string(),
})

export type LoopSkillBundleDTOApi = zod.input<typeof LoopSkillBundleDTOApi>
export type LoopSkillBundleDTOApiOutput = zod.output<typeof LoopSkillBundleDTOApi>

export const LoopDTOApi = zod
    .object({
        id: zod.uuid(),
        team_id: zod.number(),
        created_by_id: zod.number().nullable(),
        name: zod.string(),
        description: zod.string(),
        visibility: zod.string(),
        instructions: zod.string(),
        runtime_adapter: zod.string(),
        model: zod.string(),
        reasoning_effort: zod.string().nullable(),
        repositories: zod.array(LoopRepositoryEntryDTOApi).describe('Repositories this loop operates on.'),
        sandbox_environment_id: zod.uuid().nullable(),
        enabled: zod.boolean(),
        disabled_reason: zod.string().nullable(),
        overlap_policy: zod.string(),
        behaviors: LoopBehaviorsDTOApi.describe('PR \/ CI-follow-up behavior configuration.'),
        connectors: LoopConnectorsDTOApi.describe("MCP connector configuration for this loop's runs."),
        notifications: LoopNotificationsDTOApi.describe('Per-channel notification configuration.'),
        context_target: zod
            .union([LoopContextTargetDTOApi, zod.null()])
            .optional()
            .describe('Context this loop is attached to, or null when unattached.'),
        internal: zod.boolean(),
        origin_product: zod.string(),
        last_run_at: zod.iso.datetime({ offset: true }).nullable(),
        last_run_status: zod.string().nullable(),
        last_error: zod.string().nullable(),
        consecutive_failures: zod.number(),
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
        triggers: zod.array(LoopTriggerDTOApi).describe('Triggers attached to this loop.'),
        skill_bundles: zod
            .array(LoopSkillBundleDTOApi)
            .describe('Skill bundles attached to this loop, seeded into every fired run.'),
    })
    .describe('Detail\/create\/update response for a loop, including its triggers.')

export type LoopDTOApi = zod.input<typeof LoopDTOApi>
export type LoopDTOApiOutput = zod.output<typeof LoopDTOApi>

export const PaginatedLoopDTOListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(LoopDTOApi),
    max_loops_per_team: zod
        .number()
        .optional()
        .describe(
            'Hard cap on non-deleted loops per project. Creating a loop beyond this returns a 429 with `error: loop_safety_limit`. Authoritative — read this rather than assuming a value.'
        ),
    total_loop_count: zod
        .number()
        .optional()
        .describe(
            'Current number of non-deleted, user-facing loops in this project, counted against `max_loops_per_team`. At or above the cap, creation is blocked.'
        ),
})

export type PaginatedLoopDTOListApi = zod.input<typeof PaginatedLoopDTOListApi>
export type PaginatedLoopDTOListApiOutput = zod.output<typeof PaginatedLoopDTOListApi>

export const LoopWriteVisibilityEnumApi = zod
    .enum(['personal', 'team'])
    .describe('\* `personal` - personal\n\* `team` - team')

export type LoopWriteVisibilityEnumApi = zod.input<typeof LoopWriteVisibilityEnumApi>
export type LoopWriteVisibilityEnumApiOutput = zod.output<typeof LoopWriteVisibilityEnumApi>

export const RuntimeAdapterEnumApi = zod.enum(['claude', 'codex']).describe('\* `claude` - claude\n\* `codex` - codex')

export type RuntimeAdapterEnumApi = zod.input<typeof RuntimeAdapterEnumApi>
export type RuntimeAdapterEnumApiOutput = zod.output<typeof RuntimeAdapterEnumApi>

export const ReasoningEffortEnumApi = zod
    .enum(['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'])
    .describe(
        '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
    )

export type ReasoningEffortEnumApi = zod.input<typeof ReasoningEffortEnumApi>
export type ReasoningEffortEnumApiOutput = zod.output<typeof ReasoningEffortEnumApi>

export const loopRepositoryEntryApiFullNameMax = 255

export const LoopRepositoryEntryApi = zod.object({
    github_integration_id: zod.number().describe('GitHub integration id this repository is accessed through.'),
    full_name: zod
        .string()
        .max(loopRepositoryEntryApiFullNameMax)
        .describe('Repository in `organization\/repo` format, e.g. `posthog\/posthog`.'),
})

export type LoopRepositoryEntryApi = zod.input<typeof LoopRepositoryEntryApi>
export type LoopRepositoryEntryApiOutput = zod.output<typeof LoopRepositoryEntryApi>

export const OverlapPolicyEnumApi = zod
    .enum(['skip', 'allow', 'cancel_previous'])
    .describe('\* `skip` - skip\n\* `allow` - allow\n\* `cancel_previous` - cancel_previous')

export type OverlapPolicyEnumApi = zod.input<typeof OverlapPolicyEnumApi>
export type OverlapPolicyEnumApiOutput = zod.output<typeof OverlapPolicyEnumApi>

export const loopBehaviorsApiCreatePrsDefault = false
export const loopBehaviorsApiWatchCiDefault = false
export const loopBehaviorsApiFixReviewCommentsDefault = false
export const loopBehaviorsApiMaxFixIterationsDefault = 3
export const loopBehaviorsApiMaxFixIterationsMin = 0
export const loopBehaviorsApiMaxFixIterationsMax = 10

export const LoopBehaviorsApi = zod.object({
    create_prs: zod
        .boolean()
        .default(loopBehaviorsApiCreatePrsDefault)
        .describe('Whether the agent may push branches and open PRs. False makes this a report-only loop.'),
    watch_ci: zod
        .boolean()
        .default(loopBehaviorsApiWatchCiDefault)
        .describe('Whether to watch CI on loop-created PRs and report status.'),
    fix_review_comments: zod
        .boolean()
        .default(loopBehaviorsApiFixReviewCommentsDefault)
        .describe('Whether to automatically address review comments on loop-created PRs.'),
    max_fix_iterations: zod
        .number()
        .min(loopBehaviorsApiMaxFixIterationsMin)
        .max(loopBehaviorsApiMaxFixIterationsMax)
        .default(loopBehaviorsApiMaxFixIterationsDefault)
        .describe('Ceiling on automatic CI\/review-comment fix iterations, capped at 10.'),
})

export type LoopBehaviorsApi = zod.input<typeof LoopBehaviorsApi>
export type LoopBehaviorsApiOutput = zod.output<typeof LoopBehaviorsApi>

export const PosthogMcpScopesEnumApi = zod
    .enum(['read_only', 'full'])
    .describe('\* `read_only` - read_only\n\* `full` - full')

export type PosthogMcpScopesEnumApi = zod.input<typeof PosthogMcpScopesEnumApi>
export type PosthogMcpScopesEnumApiOutput = zod.output<typeof PosthogMcpScopesEnumApi>

export const loopConnectorsApiPosthogMcpScopesDefault = `read_only`

export const LoopConnectorsApi = zod.object({
    mcp_installation_ids: zod
        .array(zod.string())
        .optional()
        .describe("MCP Store installation ids (Slack, Linear, etc.) available to this loop's runs."),
    posthog_mcp_scopes: PosthogMcpScopesEnumApi.default(loopConnectorsApiPosthogMcpScopesDefault).describe(
        "Scope of the PostHog MCP access injected into this loop's runs.\n\n\* `read_only` - read_only\n\* `full` - full"
    ),
})

export type LoopConnectorsApi = zod.input<typeof LoopConnectorsApi>
export type LoopConnectorsApiOutput = zod.output<typeof LoopConnectorsApi>

export const EventsEnumApi = zod
    .enum(['run_completed', 'run_failed', 'pr_created', 'needs_attention'])
    .describe(
        '\* `run_completed` - run_completed\n\* `run_failed` - run_failed\n\* `pr_created` - pr_created\n\* `needs_attention` - needs_attention'
    )

export type EventsEnumApi = zod.input<typeof EventsEnumApi>
export type EventsEnumApiOutput = zod.output<typeof EventsEnumApi>

export const loopNotificationChannelApiEnabledDefault = false

export const LoopNotificationChannelApi = zod.object({
    enabled: zod
        .boolean()
        .default(loopNotificationChannelApiEnabledDefault)
        .describe('Whether this channel is active.'),
    events: zod
        .array(EventsEnumApi)
        .optional()
        .describe(
            'Event kinds this channel notifies on. One or more of: run_completed, run_failed, pr_created, needs_attention.'
        ),
    params: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe("Channel-specific parameters, e.g. Slack's `integration_id` and `channel`."),
})

export type LoopNotificationChannelApi = zod.input<typeof LoopNotificationChannelApi>
export type LoopNotificationChannelApiOutput = zod.output<typeof LoopNotificationChannelApi>

export const LoopNotificationsApi = zod.object({
    push: LoopNotificationChannelApi.optional().describe('Push notification settings.'),
    email: LoopNotificationChannelApi.optional().describe('Email notification settings.'),
    slack: LoopNotificationChannelApi.optional().describe('Slack notification settings.'),
})

export type LoopNotificationsApi = zod.input<typeof LoopNotificationsApi>
export type LoopNotificationsApiOutput = zod.output<typeof LoopNotificationsApi>

export const loopContextOutputsWriteApiPostToFeedDefault = false
export const loopContextOutputsWriteApiUpdateContextDefault = false

export const LoopContextOutputsWriteApi = zod.object({
    post_to_feed: zod
        .boolean()
        .default(loopContextOutputsWriteApiPostToFeedDefault)
        .describe("Whether each run is filed into the context's feed as a card (sets the run's channel)."),
    update_context: zod
        .boolean()
        .default(loopContextOutputsWriteApiUpdateContextDefault)
        .describe("Whether each run reads and republishes the context's context.md to reflect the latest state."),
    canvas_id: zod
        .string()
        .nullish()
        .describe('Id of a canvas in this context the loop keeps up to date each run, or null to maintain none.'),
})

export type LoopContextOutputsWriteApi = zod.input<typeof LoopContextOutputsWriteApi>
export type LoopContextOutputsWriteApiOutput = zod.output<typeof LoopContextOutputsWriteApi>

export const loopContextTargetWriteApiNameMax = 128

export const LoopContextTargetWriteApi = zod.object({
    folder_id: zod.string().describe('Desktop folder id of the context this loop is attached to.'),
    name: zod
        .string()
        .max(loopContextTargetWriteApiNameMax)
        .describe('Context (channel) name, used to file runs into its feed.'),
    outputs: LoopContextOutputsWriteApi.optional().describe('What the loop maintains in this context each run.'),
})

export type LoopContextTargetWriteApi = zod.input<typeof LoopContextTargetWriteApi>
export type LoopContextTargetWriteApiOutput = zod.output<typeof LoopContextTargetWriteApi>

export const LoopTriggerTypeEnumApi = zod
    .enum(['schedule', 'github', 'api'])
    .describe('\* `schedule` - schedule\n\* `github` - github\n\* `api` - api')

export type LoopTriggerTypeEnumApi = zod.input<typeof LoopTriggerTypeEnumApi>
export type LoopTriggerTypeEnumApiOutput = zod.output<typeof LoopTriggerTypeEnumApi>

export const loopTriggerWriteApiEnabledDefault = true

export const LoopTriggerWriteApi = zod.object({
    id: zod.uuid().optional().describe('Existing trigger id to update in place. Omit to create a new trigger.'),
    type: LoopTriggerTypeEnumApi.describe(
        'Trigger type: `schedule` (cron or one-time), `github` (repo webhook events), or `api` (POST to `trigger\/`).\n\n\* `schedule` - schedule\n\* `github` - github\n\* `api` - api'
    ),
    enabled: zod
        .boolean()
        .default(loopTriggerWriteApiEnabledDefault)
        .describe('Whether this trigger is active. Disabling pauses only this trigger.'),
    config: zod
        .unknown()
        .optional()
        .describe(
            'Trigger configuration, shape validated per `type`: schedule takes `{cron_expression, timezone}` or `{run_at}` for a one-time run; github takes `{github_integration_id, repository, events, filters}` where `events` is one or more of `issues`, `issue_comment`, `pull_request`, `push` (`event.action` shorthand like `issues.opened` is folded into an `actions` filter, one event per trigger) and `filters` takes `{actions, branches, labels}`; api takes no config.'
        ),
})

export type LoopTriggerWriteApi = zod.input<typeof LoopTriggerWriteApi>
export type LoopTriggerWriteApiOutput = zod.output<typeof LoopTriggerWriteApi>

export const loopWriteApiNameMax = 400

export const loopWriteApiDescriptionDefault = ``
export const loopWriteApiTakeOwnershipDefault = false
export const loopWriteApiVisibilityDefault = `personal`
export const loopWriteApiModelDefault = ``
export const loopWriteApiRepositoriesMax = 1

export const loopWriteApiEnabledDefault = true
export const loopWriteApiOverlapPolicyDefault = `skip`

export const LoopWriteApi = zod
    .object({
        name: zod.string().max(loopWriteApiNameMax).describe('Display name for the loop.'),
        description: zod
            .string()
            .default(loopWriteApiDescriptionDefault)
            .describe('Free-form description of what this loop does.'),
        take_ownership: zod
            .boolean()
            .default(loopWriteApiTakeOwnershipDefault)
            .describe(
                'On a team loop, claim ownership as part of this update so you can edit identity-bearing config (instructions, model, triggers, ...) that only the owner may change. Ignored on personal loops and on create.'
            ),
        visibility: LoopWriteVisibilityEnumApi.default(loopWriteApiVisibilityDefault).describe(
            '`personal` (owner-only) or `team` (visible and fireable by any team member).\n\n\* `personal` - personal\n\* `team` - team'
        ),
        instructions: zod.string().describe('The prompt delivered to the agent on every run.'),
        runtime_adapter: RuntimeAdapterEnumApi.describe(
            "Runtime adapter: 'claude' or 'codex'.\n\n\* `claude` - claude\n\* `codex` - codex"
        ),
        model: zod
            .string()
            .default(loopWriteApiModelDefault)
            .describe(
                "LLM model identifier, validated against `runtime_adapter`'s catalog. Leave blank to let PostHog pick a sensible default at run time."
            ),
        reasoning_effort: zod
            .union([ReasoningEffortEnumApi, zod.null()])
            .optional()
            .describe(
                "Reasoning effort, validated against `runtime_adapter`\/`model`'s supported set.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode"
            ),
        repositories: zod
            .array(LoopRepositoryEntryApi)
            .max(loopWriteApiRepositoriesMax)
            .optional()
            .describe(
                'Repositories this loop operates on, ordered. Capped at 1 until multi-repo execution ships. May be empty for report-only loops.'
            ),
        sandbox_environment: zod
            .uuid()
            .nullish()
            .describe('Sandbox environment carrying encrypted env vars and the network allowlist into every run.'),
        enabled: zod
            .boolean()
            .default(loopWriteApiEnabledDefault)
            .describe("Whether the loop's triggers are active. Pausing disables all triggers."),
        overlap_policy: OverlapPolicyEnumApi.default(loopWriteApiOverlapPolicyDefault).describe(
            "What happens when a trigger fires while a run is already active: 'skip', 'allow', or 'cancel_previous'.\n\n\* `skip` - skip\n\* `allow` - allow\n\* `cancel_previous` - cancel_previous"
        ),
        behaviors: LoopBehaviorsApi.optional().describe('PR \/ CI-follow-up behavior configuration.'),
        connectors: LoopConnectorsApi.optional().describe("MCP connector configuration for this loop's runs."),
        notifications: LoopNotificationsApi.optional().describe('Per-channel notification configuration.'),
        context_target: zod
            .union([LoopContextTargetWriteApi, zod.null()])
            .optional()
            .describe(
                'Context (channel) this loop is attached to, or null to detach. Drives feed placement and the context.md \/ canvas it keeps up to date.'
            ),
        triggers: zod
            .array(LoopTriggerWriteApi)
            .optional()
            .describe(
                'Full desired trigger list, id-stable: entries with a matching `id` are updated in place, entries without one are created, and existing triggers absent from this list are deleted. Omit the field entirely to leave triggers untouched. At most 25 triggers per loop.'
            ),
    })
    .describe(
        'Request body for creating or updating a loop. Field required\/default semantics match\nthe `Loop` model; partial updates only touch keys present in the payload.'
    )

export type LoopWriteApi = zod.input<typeof LoopWriteApi>
export type LoopWriteApiOutput = zod.output<typeof LoopWriteApi>

export const patchedLoopWriteApiNameMax = 400

export const patchedLoopWriteApiDescriptionDefault = ``
export const patchedLoopWriteApiTakeOwnershipDefault = false
export const patchedLoopWriteApiVisibilityDefault = `personal`
export const patchedLoopWriteApiModelDefault = ``
export const patchedLoopWriteApiRepositoriesMax = 1

export const patchedLoopWriteApiEnabledDefault = true
export const patchedLoopWriteApiOverlapPolicyDefault = `skip`

export const PatchedLoopWriteApi = zod
    .object({
        name: zod.string().max(patchedLoopWriteApiNameMax).optional().describe('Display name for the loop.'),
        description: zod
            .string()
            .default(patchedLoopWriteApiDescriptionDefault)
            .describe('Free-form description of what this loop does.'),
        take_ownership: zod
            .boolean()
            .default(patchedLoopWriteApiTakeOwnershipDefault)
            .describe(
                'On a team loop, claim ownership as part of this update so you can edit identity-bearing config (instructions, model, triggers, ...) that only the owner may change. Ignored on personal loops and on create.'
            ),
        visibility: LoopWriteVisibilityEnumApi.default(patchedLoopWriteApiVisibilityDefault).describe(
            '`personal` (owner-only) or `team` (visible and fireable by any team member).\n\n\* `personal` - personal\n\* `team` - team'
        ),
        instructions: zod.string().optional().describe('The prompt delivered to the agent on every run.'),
        runtime_adapter: RuntimeAdapterEnumApi.optional().describe(
            "Runtime adapter: 'claude' or 'codex'.\n\n\* `claude` - claude\n\* `codex` - codex"
        ),
        model: zod
            .string()
            .default(patchedLoopWriteApiModelDefault)
            .describe(
                "LLM model identifier, validated against `runtime_adapter`'s catalog. Leave blank to let PostHog pick a sensible default at run time."
            ),
        reasoning_effort: zod
            .union([ReasoningEffortEnumApi, zod.null()])
            .optional()
            .describe(
                "Reasoning effort, validated against `runtime_adapter`\/`model`'s supported set.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode"
            ),
        repositories: zod
            .array(LoopRepositoryEntryApi)
            .max(patchedLoopWriteApiRepositoriesMax)
            .optional()
            .describe(
                'Repositories this loop operates on, ordered. Capped at 1 until multi-repo execution ships. May be empty for report-only loops.'
            ),
        sandbox_environment: zod
            .uuid()
            .nullish()
            .describe('Sandbox environment carrying encrypted env vars and the network allowlist into every run.'),
        enabled: zod
            .boolean()
            .default(patchedLoopWriteApiEnabledDefault)
            .describe("Whether the loop's triggers are active. Pausing disables all triggers."),
        overlap_policy: OverlapPolicyEnumApi.default(patchedLoopWriteApiOverlapPolicyDefault).describe(
            "What happens when a trigger fires while a run is already active: 'skip', 'allow', or 'cancel_previous'.\n\n\* `skip` - skip\n\* `allow` - allow\n\* `cancel_previous` - cancel_previous"
        ),
        behaviors: LoopBehaviorsApi.optional().describe('PR \/ CI-follow-up behavior configuration.'),
        connectors: LoopConnectorsApi.optional().describe("MCP connector configuration for this loop's runs."),
        notifications: LoopNotificationsApi.optional().describe('Per-channel notification configuration.'),
        context_target: zod
            .union([LoopContextTargetWriteApi, zod.null()])
            .optional()
            .describe(
                'Context (channel) this loop is attached to, or null to detach. Drives feed placement and the context.md \/ canvas it keeps up to date.'
            ),
        triggers: zod
            .array(LoopTriggerWriteApi)
            .optional()
            .describe(
                'Full desired trigger list, id-stable: entries with a matching `id` are updated in place, entries without one are created, and existing triggers absent from this list are deleted. Omit the field entirely to leave triggers untouched. At most 25 triggers per loop.'
            ),
    })
    .describe(
        'Request body for creating or updating a loop. Field required\/default semantics match\nthe `Loop` model; partial updates only touch keys present in the payload.'
    )

export type PatchedLoopWriteApi = zod.input<typeof PatchedLoopWriteApi>
export type PatchedLoopWriteApiOutput = zod.output<typeof PatchedLoopWriteApi>

export const loopPreviewRequestApiTriggerTypeDefault = `schedule`

export const LoopPreviewRequestApi = zod.object({
    trigger_type: LoopTriggerTypeEnumApi.default(loopPreviewRequestApiTriggerTypeDefault).describe(
        'Trigger type to simulate. Defaults to a synthetic schedule fire.\n\n\* `schedule` - schedule\n\* `github` - github\n\* `api` - api'
    ),
    payload: zod
        .unknown()
        .optional()
        .describe('Sample trigger payload, e.g. a GitHub webhook body or an API trigger body, to render into context.'),
})

export type LoopPreviewRequestApi = zod.input<typeof LoopPreviewRequestApi>
export type LoopPreviewRequestApiOutput = zod.output<typeof LoopPreviewRequestApi>

export const LoopPreviewDTOApi = zod.object({
    instructions: zod.string(),
    trigger_type: zod.string(),
    trigger_context: zod.string(),
})

export type LoopPreviewDTOApi = zod.input<typeof LoopPreviewDTOApi>
export type LoopPreviewDTOApiOutput = zod.output<typeof LoopPreviewDTOApi>

export const LoopFireResultReasonEnumApi = zod
    .enum([
        'created',
        'deduped',
        'overlap_skipped',
        'rate_capped',
        'team_rate_capped',
        'disabled',
        'gate_blocked',
        'owner_inactive',
        'owner_changed',
    ])
    .describe(
        '\* `created` - created\n\* `deduped` - deduped\n\* `overlap_skipped` - overlap_skipped\n\* `rate_capped` - rate_capped\n\* `team_rate_capped` - team_rate_capped\n\* `disabled` - disabled\n\* `gate_blocked` - gate_blocked\n\* `owner_inactive` - owner_inactive\n\* `owner_changed` - owner_changed'
    )

export type LoopFireResultReasonEnumApi = zod.input<typeof LoopFireResultReasonEnumApi>
export type LoopFireResultReasonEnumApiOutput = zod.output<typeof LoopFireResultReasonEnumApi>

export const LoopFireResultApi = zod
    .object({
        created: zod.boolean(),
        reason: LoopFireResultReasonEnumApi.describe(
            'Outcome of the fire attempt.\n\n\* `created` - created\n\* `deduped` - deduped\n\* `overlap_skipped` - overlap_skipped\n\* `rate_capped` - rate_capped\n\* `team_rate_capped` - team_rate_capped\n\* `disabled` - disabled\n\* `gate_blocked` - gate_blocked\n\* `owner_inactive` - owner_inactive\n\* `owner_changed` - owner_changed'
        ),
        task_id: zod.uuid().nullable().describe('Id of the created task, when `created` is true.'),
        task_run_id: zod.uuid().nullable().describe('Id of the created task run, when `created` is true.'),
    })
    .describe('Response for a manual (`run\/`) or external (`trigger\/`) fire.')

export type LoopFireResultApi = zod.input<typeof LoopFireResultApi>
export type LoopFireResultApiOutput = zod.output<typeof LoopFireResultApi>

export const LoopRunDTOApi = zod
    .object({
        id: zod.uuid(),
        task_id: zod.uuid(),
        loop_trigger_id: zod.uuid().nullable(),
        status: zod.string(),
        environment: zod.string(),
        branch: zod.string().nullable(),
        error_message: zod.string().nullable(),
        output: zod.record(zod.string(), zod.unknown()).nullable(),
        created_at: zod.iso.datetime({ offset: true }),
        completed_at: zod.iso.datetime({ offset: true }).nullable(),
    })
    .describe("A single entry in a loop's run history.")

export type LoopRunDTOApi = zod.input<typeof LoopRunDTOApi>
export type LoopRunDTOApiOutput = zod.output<typeof LoopRunDTOApi>

export const LoopRunPageApi = zod.object({
    results: zod.array(LoopRunDTOApi).describe('Run history entries, newest first.'),
    next_cursor: zod
        .string()
        .nullable()
        .describe('Opaque cursor for the next page, or null when there are no more results.'),
})

export type LoopRunPageApi = zod.input<typeof LoopRunPageApi>
export type LoopRunPageApiOutput = zod.output<typeof LoopRunPageApi>

export const SkillSourceEnumApi = zod
    .enum(['user', 'repo', 'marketplace', 'codex'])
    .describe('\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex')

export type SkillSourceEnumApi = zod.input<typeof SkillSourceEnumApi>
export type SkillSourceEnumApiOutput = zod.output<typeof SkillSourceEnumApi>

export const BundleFormatEnumApi = zod.enum(['zip']).describe('\* `zip` - zip')

export type BundleFormatEnumApi = zod.input<typeof BundleFormatEnumApi>
export type BundleFormatEnumApiOutput = zod.output<typeof BundleFormatEnumApi>

export const loopSkillBundleUploadApiFileNameMax = 255

export const loopSkillBundleUploadApiSkillNameMax = 255

export const loopSkillBundleUploadApiContentSha256RegExp = new RegExp('^[a-f0-9]{64}$')

export const LoopSkillBundleUploadApi = zod
    .object({
        file_name: zod
            .string()
            .max(loopSkillBundleUploadApiFileNameMax)
            .describe('File name for the stored bundle, e.g. `my-skill.zip`.'),
        skill_name: zod
            .string()
            .max(loopSkillBundleUploadApiSkillNameMax)
            .describe('Name of the skill inside the bundle.'),
        skill_source: SkillSourceEnumApi.describe(
            'Local source the bundle was built from, such as user or repo.\n\n\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
        ),
        content_sha256: zod
            .string()
            .regex(loopSkillBundleUploadApiContentSha256RegExp)
            .describe('SHA-256 hex digest of the bundle bytes.'),
        bundle_format: BundleFormatEnumApi.describe('Archive format used for the bundle.\n\n\* `zip` - zip'),
        content_base64: zod.string().describe('Base64-encoded bundle bytes.'),
    })
    .describe('One zipped local skill in a skill-bundle replace request.')

export type LoopSkillBundleUploadApi = zod.input<typeof LoopSkillBundleUploadApi>
export type LoopSkillBundleUploadApiOutput = zod.output<typeof LoopSkillBundleUploadApi>

export const LoopSkillBundlesWriteApi = zod
    .object({
        bundles: zod.array(LoopSkillBundleUploadApi),
    })
    .describe(
        "Request body for replacing a loop's attached skill bundles wholesale. Send an empty\nlist to detach every skill."
    )

export type LoopSkillBundlesWriteApi = zod.input<typeof LoopSkillBundlesWriteApi>
export type LoopSkillBundlesWriteApiOutput = zod.output<typeof LoopSkillBundlesWriteApi>

export const TaskUserBasicInfoApi = zod
    .object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string(),
        first_name: zod.string(),
        last_name: zod.string(),
        email: zod.string(),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
        role_at_organization: zod.string().nullish(),
    })
    .describe('Response shape for a task creator, mirroring core ``UserBasicSerializer`` output.')

export type TaskUserBasicInfoApi = zod.input<typeof TaskUserBasicInfoApi>
export type TaskUserBasicInfoApiOutput = zod.output<typeof TaskUserBasicInfoApi>

export const SandboxCustomImageDTOApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string(),
        description: zod.string(),
        repository: zod.string().optional(),
        private: zod.boolean().optional(),
        status: zod.string(),
        version: zod.number(),
        modal_image_name: zod.string(),
        spec: zod.record(zod.string(), zod.unknown()).optional(),
        spec_yaml: zod.string().optional(),
        scan_result: zod.record(zod.string(), zod.unknown()).optional(),
        build_log: zod.string().optional(),
        error: zod.string(),
        builder_task_id: zod.uuid().nullish(),
        created_by: zod.union([TaskUserBasicInfoApi, zod.null()]).optional(),
        created_at: zod.iso.datetime({ offset: true }).nullish(),
        updated_at: zod.iso.datetime({ offset: true }).nullish(),
    })
    .describe('Detail response for a custom sandbox base image.')

export type SandboxCustomImageDTOApi = zod.input<typeof SandboxCustomImageDTOApi>
export type SandboxCustomImageDTOApiOutput = zod.output<typeof SandboxCustomImageDTOApi>

export const PaginatedSandboxCustomImageDTOListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(SandboxCustomImageDTOApi),
})

export type PaginatedSandboxCustomImageDTOListApi = zod.input<typeof PaginatedSandboxCustomImageDTOListApi>
export type PaginatedSandboxCustomImageDTOListApiOutput = zod.output<typeof PaginatedSandboxCustomImageDTOListApi>

export const sandboxCustomImageWriteApiNameMax = 255

export const sandboxCustomImageWriteApiDescriptionDefault = ``
export const sandboxCustomImageWriteApiRepositoryMax = 255

export const sandboxCustomImageWriteApiPrivateDefault = false

export const SandboxCustomImageWriteApi = zod
    .object({
        name: zod.string().max(sandboxCustomImageWriteApiNameMax).describe('Display name for the custom image.'),
        description: zod
            .string()
            .default(sandboxCustomImageWriteApiDescriptionDefault)
            .describe('What should go into the image; seeds the image-builder agent conversation.'),
        repository: zod
            .string()
            .max(sandboxCustomImageWriteApiRepositoryMax)
            .nullish()
            .describe(
                "Optional 'org\/repo' the builder session clones so it can verify the image brings up that repository's dependencies."
            ),
        private: zod
            .boolean()
            .default(sandboxCustomImageWriteApiPrivateDefault)
            .describe('If true, only you can see and use this image; otherwise the whole team can.'),
    })
    .describe('Request body for creating a custom sandbox base image.')

export type SandboxCustomImageWriteApi = zod.input<typeof SandboxCustomImageWriteApi>
export type SandboxCustomImageWriteApiOutput = zod.output<typeof SandboxCustomImageWriteApi>

export const patchedSandboxCustomImageUpdateApiNameMax = 255

export const PatchedSandboxCustomImageUpdateApi = zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(patchedSandboxCustomImageUpdateApiNameMax)
            .optional()
            .describe('New display name for the custom image. Omit to leave unchanged.'),
        description: zod
            .string()
            .optional()
            .describe('New description. Omit to leave unchanged; pass an empty string to clear it.'),
    })
    .describe('Request body for renaming \/ re-describing a custom sandbox base image.')

export type PatchedSandboxCustomImageUpdateApi = zod.input<typeof PatchedSandboxCustomImageUpdateApi>
export type PatchedSandboxCustomImageUpdateApiOutput = zod.output<typeof PatchedSandboxCustomImageUpdateApi>

export const SandboxCustomImageBuildApi = zod
    .object({
        spec_yaml: zod
            .string()
            .nullish()
            .describe(
                "Image spec YAML to build. When omitted, the spec is read from the builder agent's live sandbox."
            ),
    })
    .describe('Request body for scanning and building a custom sandbox base image.')

export type SandboxCustomImageBuildApi = zod.input<typeof SandboxCustomImageBuildApi>
export type SandboxCustomImageBuildApiOutput = zod.output<typeof SandboxCustomImageBuildApi>

export const SandboxEnvironmentDTOApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string(),
        network_access_level: zod.string(),
        allowed_domains: zod.array(zod.string()).optional(),
        repositories: zod.array(zod.string()).optional(),
        private: zod.boolean(),
        internal: zod.boolean(),
        created_by: zod.union([TaskUserBasicInfoApi, zod.null()]).optional(),
        created_at: zod.iso.datetime({ offset: true }).nullish(),
        updated_at: zod.iso.datetime({ offset: true }).nullish(),
        custom_image_id: zod.uuid().nullish(),
        custom_image_name: zod.string().nullish(),
        custom_image_status: zod.string().nullish(),
    })
    .describe('List response for sandbox environments (subset of fields).')

export type SandboxEnvironmentDTOApi = zod.input<typeof SandboxEnvironmentDTOApi>
export type SandboxEnvironmentDTOApiOutput = zod.output<typeof SandboxEnvironmentDTOApi>

export const PaginatedSandboxEnvironmentDTOListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(SandboxEnvironmentDTOApi),
})

export type PaginatedSandboxEnvironmentDTOListApi = zod.input<typeof PaginatedSandboxEnvironmentDTOListApi>
export type PaginatedSandboxEnvironmentDTOListApiOutput = zod.output<typeof PaginatedSandboxEnvironmentDTOListApi>

export const NetworkAccessLevelEnumApi = zod
    .enum(['trusted', 'full', 'custom'])
    .describe('\* `trusted` - Trusted\n\* `full` - Full\n\* `custom` - Custom')

export type NetworkAccessLevelEnumApi = zod.input<typeof NetworkAccessLevelEnumApi>
export type NetworkAccessLevelEnumApiOutput = zod.output<typeof NetworkAccessLevelEnumApi>

export const sandboxEnvironmentWriteApiNameMax = 255

export const sandboxEnvironmentWriteApiNetworkAccessLevelDefault = `full`
export const sandboxEnvironmentWriteApiAllowedDomainsItemMax = 255

export const sandboxEnvironmentWriteApiIncludeDefaultDomainsDefault = false
export const sandboxEnvironmentWriteApiRepositoriesItemMax = 255

export const sandboxEnvironmentWriteApiPrivateDefault = true

export const SandboxEnvironmentWriteApi = zod
    .object({
        name: zod.string().max(sandboxEnvironmentWriteApiNameMax).describe('Display name for the environment.'),
        network_access_level: NetworkAccessLevelEnumApi.default(
            sandboxEnvironmentWriteApiNetworkAccessLevelDefault
        ).describe(
            'Network access policy: trusted (default allowlist), full (unrestricted), or custom.\n\n\* `trusted` - Trusted\n\* `full` - Full\n\* `custom` - Custom'
        ),
        allowed_domains: zod
            .array(zod.string().max(sandboxEnvironmentWriteApiAllowedDomainsItemMax))
            .optional()
            .describe('Allowed domains for custom network access.'),
        include_default_domains: zod
            .boolean()
            .default(sandboxEnvironmentWriteApiIncludeDefaultDomainsDefault)
            .describe('Whether to include default trusted domains (GitHub, npm, PyPI).'),
        repositories: zod
            .array(zod.string().max(sandboxEnvironmentWriteApiRepositoriesItemMax))
            .optional()
            .describe('Repositories this environment applies to (format: org\/repo).'),
        environment_variables: zod
            .unknown()
            .optional()
            .describe('Encrypted environment variables (write-only, never returned in responses).'),
        private: zod
            .boolean()
            .default(sandboxEnvironmentWriteApiPrivateDefault)
            .describe('If true, only the creator can see this environment; otherwise the whole team can.'),
        custom_image_id: zod
            .uuid()
            .nullish()
            .describe(
                "Custom base image for this environment's sandboxes (Modal VM runtime only); null uses the default base."
            ),
    })
    .describe('Request body for creating or updating a sandbox environment.')

export type SandboxEnvironmentWriteApi = zod.input<typeof SandboxEnvironmentWriteApi>
export type SandboxEnvironmentWriteApiOutput = zod.output<typeof SandboxEnvironmentWriteApi>

export const patchedSandboxEnvironmentWriteApiNameMax = 255

export const patchedSandboxEnvironmentWriteApiNetworkAccessLevelDefault = `full`
export const patchedSandboxEnvironmentWriteApiAllowedDomainsItemMax = 255

export const patchedSandboxEnvironmentWriteApiIncludeDefaultDomainsDefault = false
export const patchedSandboxEnvironmentWriteApiRepositoriesItemMax = 255

export const patchedSandboxEnvironmentWriteApiPrivateDefault = true

export const PatchedSandboxEnvironmentWriteApi = zod
    .object({
        name: zod
            .string()
            .max(patchedSandboxEnvironmentWriteApiNameMax)
            .optional()
            .describe('Display name for the environment.'),
        network_access_level: NetworkAccessLevelEnumApi.default(
            patchedSandboxEnvironmentWriteApiNetworkAccessLevelDefault
        ).describe(
            'Network access policy: trusted (default allowlist), full (unrestricted), or custom.\n\n\* `trusted` - Trusted\n\* `full` - Full\n\* `custom` - Custom'
        ),
        allowed_domains: zod
            .array(zod.string().max(patchedSandboxEnvironmentWriteApiAllowedDomainsItemMax))
            .optional()
            .describe('Allowed domains for custom network access.'),
        include_default_domains: zod
            .boolean()
            .default(patchedSandboxEnvironmentWriteApiIncludeDefaultDomainsDefault)
            .describe('Whether to include default trusted domains (GitHub, npm, PyPI).'),
        repositories: zod
            .array(zod.string().max(patchedSandboxEnvironmentWriteApiRepositoriesItemMax))
            .optional()
            .describe('Repositories this environment applies to (format: org\/repo).'),
        environment_variables: zod
            .unknown()
            .optional()
            .describe('Encrypted environment variables (write-only, never returned in responses).'),
        private: zod
            .boolean()
            .default(patchedSandboxEnvironmentWriteApiPrivateDefault)
            .describe('If true, only the creator can see this environment; otherwise the whole team can.'),
        custom_image_id: zod
            .uuid()
            .nullish()
            .describe(
                "Custom base image for this environment's sandboxes (Modal VM runtime only); null uses the default base."
            ),
    })
    .describe('Request body for creating or updating a sandbox environment.')

export type PatchedSandboxEnvironmentWriteApi = zod.input<typeof PatchedSandboxEnvironmentWriteApi>
export type PatchedSandboxEnvironmentWriteApiOutput = zod.output<typeof PatchedSandboxEnvironmentWriteApi>

export const ActivityKindEnumApi = zod
    .enum(['awaiting_input', 'completed', 'mention', 'message', 'created'])
    .describe(
        '\* `awaiting_input` - awaiting_input\n\* `completed` - completed\n\* `mention` - mention\n\* `message` - message\n\* `created` - created'
    )

export type ActivityKindEnumApi = zod.input<typeof ActivityKindEnumApi>
export type ActivityKindEnumApiOutput = zod.output<typeof ActivityKindEnumApi>

export const TaskActivityDTOApi = zod
    .object({
        id: zod.uuid(),
        task_id: zod.uuid(),
        task_title: zod.string(),
        channel_id: zod.uuid().nullable(),
        channel_name: zod.string().nullable(),
        activity_at: zod.iso.datetime({ offset: true }),
        activity_kind: ActivityKindEnumApi.describe(
            'What the latest activity on this task was: an agent run waiting on the requester (awaiting_input), a completed run (completed), someone @-mentioning them (mention), a thread reply (message), or their creating the task (created).\n\n\* `awaiting_input` - awaiting_input\n\* `completed` - completed\n\* `mention` - mention\n\* `message` - message\n\* `created` - created'
        ),
        snippet: zod
            .string()
            .describe('Content of the thread message tied to the latest activity; empty for task-creation rows.'),
        latest_author: zod
            .union([TaskUserBasicInfoApi, zod.null()])
            .optional()
            .describe('Author of the thread message tied to the latest activity, when one applies.'),
        latest_message_id: zod.uuid().nullish(),
        is_unread: zod
            .boolean()
            .describe(
                'Whether the requester has yet to see this activity. Activity they caused themselves is never unread.'
            ),
    })
    .describe("Response shape for one task in the requester's activity feed (one row per task).")

export type TaskActivityDTOApi = zod.input<typeof TaskActivityDTOApi>
export type TaskActivityDTOApiOutput = zod.output<typeof TaskActivityDTOApi>

export const TaskActivityPageDTOApi = zod
    .object({
        results: zod.array(TaskActivityDTOApi).describe('Tasks with activity, most recent first.'),
        unread_count: zod
            .number()
            .describe("Unread tasks across the requester's whole feed, not just this page. Backs the sidebar badge."),
        next_before: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('Activity timestamp to pass as before for the next page, or null on the final page.'),
        next_before_id: zod
            .uuid()
            .nullish()
            .describe('Activity ID to pass as before_id for the next page, or null on the final page.'),
    })
    .describe("A page of the requester's activity feed, plus the unread total across the whole feed.")

export type TaskActivityPageDTOApi = zod.input<typeof TaskActivityPageDTOApi>
export type TaskActivityPageDTOApiOutput = zod.output<typeof TaskActivityPageDTOApi>

export const TaskActivityReadMarkerApi = zod.object({
    task_id: zod.uuid().describe('Task whose displayed activity should be marked read.'),
    seen_before: zod.iso
        .datetime({ offset: true })
        .describe('Mark activity at or before this timestamp read without clearing newer activity.'),
})

export type TaskActivityReadMarkerApi = zod.input<typeof TaskActivityReadMarkerApi>
export type TaskActivityReadMarkerApiOutput = zod.output<typeof TaskActivityReadMarkerApi>

export const taskActivityMarkReadApiActivitiesMax = 500

export const TaskActivityMarkReadApi = zod
    .object({
        activities: zod
            .array(TaskActivityReadMarkerApi)
            .max(taskActivityMarkReadApiActivitiesMax)
            .describe('Displayed task activities to mark read if they have not changed.'),
    })
    .describe('Request body for clearing the unread flag on specific tasks.')

export type TaskActivityMarkReadApi = zod.input<typeof TaskActivityMarkReadApi>
export type TaskActivityMarkReadApiOutput = zod.output<typeof TaskActivityMarkReadApi>

export const TaskActivityMarkReadResponseApi = zod.object({
    marked_read: zod.number().describe('How many feed rows changed from unread to read.'),
    unread_count: zod.number().describe("The requester's remaining unread total after the update."),
})

export type TaskActivityMarkReadResponseApi = zod.input<typeof TaskActivityMarkReadResponseApi>
export type TaskActivityMarkReadResponseApiOutput = zod.output<typeof TaskActivityMarkReadResponseApi>

export const TaskAutomationDTOApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string(),
        prompt: zod.string(),
        repository: zod.string().nullable(),
        github_integration: zod.number().nullable(),
        cron_expression: zod.string(),
        timezone: zod.string(),
        template_id: zod.string().nullable(),
        enabled: zod.boolean(),
        last_run_at: zod.iso.datetime({ offset: true }).nullable(),
        last_run_status: zod.string().nullable(),
        last_task_id: zod.string(),
        last_task_run_id: zod.string().nullable(),
        last_error: zod.string().nullable(),
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
    })
    .describe('Detail\/create\/update\/run response for a task automation.')

export type TaskAutomationDTOApi = zod.input<typeof TaskAutomationDTOApi>
export type TaskAutomationDTOApiOutput = zod.output<typeof TaskAutomationDTOApi>

export const PaginatedTaskAutomationDTOListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(TaskAutomationDTOApi),
})

export type PaginatedTaskAutomationDTOListApi = zod.input<typeof PaginatedTaskAutomationDTOListApi>
export type PaginatedTaskAutomationDTOListApiOutput = zod.output<typeof PaginatedTaskAutomationDTOListApi>

export const taskAutomationWriteApiNameMax = 255

export const taskAutomationWriteApiRepositoryMax = 255

export const taskAutomationWriteApiCronExpressionMax = 100

export const taskAutomationWriteApiTimezoneDefault = `UTC`
export const taskAutomationWriteApiTimezoneMax = 128

export const taskAutomationWriteApiTemplateIdMax = 255

export const taskAutomationWriteApiEnabledDefault = true

export const TaskAutomationWriteApi = zod
    .object({
        name: zod
            .string()
            .max(taskAutomationWriteApiNameMax)
            .describe("Display name (stored as the backing task's title)."),
        prompt: zod.string().describe("The automation prompt (stored as the backing task's description)."),
        repository: zod
            .string()
            .max(taskAutomationWriteApiRepositoryMax)
            .describe('Target repository in the format organization\/repository.'),
        github_integration: zod
            .number()
            .nullish()
            .describe("GitHub integration to run as. Defaults to the team's GitHub integration when omitted."),
        cron_expression: zod
            .string()
            .max(taskAutomationWriteApiCronExpressionMax)
            .describe('Standard 5-field cron expression (minute hour day month weekday).'),
        timezone: zod
            .string()
            .max(taskAutomationWriteApiTimezoneMax)
            .default(taskAutomationWriteApiTimezoneDefault)
            .describe('IANA timezone the schedule runs in.'),
        template_id: zod
            .string()
            .max(taskAutomationWriteApiTemplateIdMax)
            .nullish()
            .describe('Optional template identifier this automation was created from.'),
        enabled: zod
            .boolean()
            .default(taskAutomationWriteApiEnabledDefault)
            .describe('Whether the schedule is active; paused when false.'),
    })
    .describe('Request body for creating or updating a task automation.')

export type TaskAutomationWriteApi = zod.input<typeof TaskAutomationWriteApi>
export type TaskAutomationWriteApiOutput = zod.output<typeof TaskAutomationWriteApi>

export const patchedTaskAutomationWriteApiNameMax = 255

export const patchedTaskAutomationWriteApiRepositoryMax = 255

export const patchedTaskAutomationWriteApiCronExpressionMax = 100

export const patchedTaskAutomationWriteApiTimezoneDefault = `UTC`
export const patchedTaskAutomationWriteApiTimezoneMax = 128

export const patchedTaskAutomationWriteApiTemplateIdMax = 255

export const patchedTaskAutomationWriteApiEnabledDefault = true

export const PatchedTaskAutomationWriteApi = zod
    .object({
        name: zod
            .string()
            .max(patchedTaskAutomationWriteApiNameMax)
            .optional()
            .describe("Display name (stored as the backing task's title)."),
        prompt: zod.string().optional().describe("The automation prompt (stored as the backing task's description)."),
        repository: zod
            .string()
            .max(patchedTaskAutomationWriteApiRepositoryMax)
            .optional()
            .describe('Target repository in the format organization\/repository.'),
        github_integration: zod
            .number()
            .nullish()
            .describe("GitHub integration to run as. Defaults to the team's GitHub integration when omitted."),
        cron_expression: zod
            .string()
            .max(patchedTaskAutomationWriteApiCronExpressionMax)
            .optional()
            .describe('Standard 5-field cron expression (minute hour day month weekday).'),
        timezone: zod
            .string()
            .max(patchedTaskAutomationWriteApiTimezoneMax)
            .default(patchedTaskAutomationWriteApiTimezoneDefault)
            .describe('IANA timezone the schedule runs in.'),
        template_id: zod
            .string()
            .max(patchedTaskAutomationWriteApiTemplateIdMax)
            .nullish()
            .describe('Optional template identifier this automation was created from.'),
        enabled: zod
            .boolean()
            .default(patchedTaskAutomationWriteApiEnabledDefault)
            .describe('Whether the schedule is active; paused when false.'),
    })
    .describe('Request body for creating or updating a task automation.')

export type PatchedTaskAutomationWriteApi = zod.input<typeof PatchedTaskAutomationWriteApi>
export type PatchedTaskAutomationWriteApiOutput = zod.output<typeof PatchedTaskAutomationWriteApi>

export const ChannelDTOApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string(),
        channel_type: zod.string(),
        created_at: zod.iso.datetime({ offset: true }),
        created_by: zod.union([TaskUserBasicInfoApi, zod.null()]).optional(),
    })
    .describe('Response shape for a task channel, read from a frozen ``ChannelDTO``.')

export type ChannelDTOApi = zod.input<typeof ChannelDTOApi>
export type ChannelDTOApiOutput = zod.output<typeof ChannelDTOApi>

export const PaginatedChannelDTOListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ChannelDTOApi),
})

export type PaginatedChannelDTOListApi = zod.input<typeof PaginatedChannelDTOListApi>
export type PaginatedChannelDTOListApiOutput = zod.output<typeof PaginatedChannelDTOListApi>

export const channelWriteApiNameMax = 128

export const ChannelWriteApi = zod
    .object({
        name: zod
            .string()
            .max(channelWriteApiNameMax)
            .describe('Channel name, rendered as #<name>. Normalized to lowercase-dashed.'),
    })
    .describe('Request body for creating (resolve-or-create) or renaming a public channel.')

export type ChannelWriteApi = zod.input<typeof ChannelWriteApi>
export type ChannelWriteApiOutput = zod.output<typeof ChannelWriteApi>

export const ChannelFeedMessageDTOApi = zod
    .object({
        id: zod.uuid(),
        channel: zod.uuid(),
        author: zod.union([TaskUserBasicInfoApi, zod.null()]).optional(),
        author_kind: zod.string(),
        event: zod.string(),
        payload: zod.record(zod.string(), zod.unknown()),
        content: zod.string(),
        created_at: zod.iso.datetime({ offset: true }),
    })
    .describe("Response shape for one system announcement in a channel's feed.")

export type ChannelFeedMessageDTOApi = zod.input<typeof ChannelFeedMessageDTOApi>
export type ChannelFeedMessageDTOApiOutput = zod.output<typeof ChannelFeedMessageDTOApi>

export const PaginatedChannelFeedMessageDTOListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ChannelFeedMessageDTOApi),
})

export type PaginatedChannelFeedMessageDTOListApi = zod.input<typeof PaginatedChannelFeedMessageDTOListApi>
export type PaginatedChannelFeedMessageDTOListApiOutput = zod.output<typeof PaginatedChannelFeedMessageDTOListApi>

export const EventEnumApi = zod
    .enum(['context_created', 'context_md_building'])
    .describe('\* `context_created` - context_created\n\* `context_md_building` - context_md_building')

export type EventEnumApi = zod.input<typeof EventEnumApi>
export type EventEnumApiOutput = zod.output<typeof EventEnumApi>

export const ChannelFeedMessageWriteApi = zod
    .object({
        event: EventEnumApi.describe(
            'Lifecycle event key.\n\n\* `context_created` - context_created\n\* `context_md_building` - context_md_building'
        ),
        payload: zod
            .unknown()
            .optional()
            .describe('Structured event data, e.g. {\"context_name\": \"mobile\"}. At most 8 KB of JSON.'),
        created_at: zod.iso
            .datetime({ offset: true })
            .optional()
            .describe(
                'Optional explicit timestamp (within 10 minutes of now), so a client can order a burst of announcements.'
            ),
    })
    .describe("Request body for posting a system announcement into a channel's feed.")

export type ChannelFeedMessageWriteApi = zod.input<typeof ChannelFeedMessageWriteApi>
export type ChannelFeedMessageWriteApiOutput = zod.output<typeof ChannelFeedMessageWriteApi>

export const patchedChannelWriteApiNameMax = 128

export const PatchedChannelWriteApi = zod
    .object({
        name: zod
            .string()
            .max(patchedChannelWriteApiNameMax)
            .optional()
            .describe('Channel name, rendered as #<name>. Normalized to lowercase-dashed.'),
    })
    .describe('Request body for creating (resolve-or-create) or renaming a public channel.')

export type PatchedChannelWriteApi = zod.input<typeof PatchedChannelWriteApi>
export type PatchedChannelWriteApiOutput = zod.output<typeof PatchedChannelWriteApi>

export const TaskMentionDTOApi = zod
    .object({
        id: zod.uuid(),
        message_id: zod.uuid(),
        task_id: zod.uuid(),
        task_title: zod.string(),
        channel_id: zod.uuid().nullable(),
        channel_name: zod.string().nullable(),
        author: zod.union([TaskUserBasicInfoApi, zod.null()]).optional(),
        content: zod.string(),
        created_at: zod.iso.datetime({ offset: true }),
    })
    .describe("Response shape for one @-mention of the requester in a task's thread.")

export type TaskMentionDTOApi = zod.input<typeof TaskMentionDTOApi>
export type TaskMentionDTOApiOutput = zod.output<typeof TaskMentionDTOApi>

export const PaginatedTaskMentionDTOListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(TaskMentionDTOApi),
})

export type PaginatedTaskMentionDTOListApi = zod.input<typeof PaginatedTaskMentionDTOListApi>
export type PaginatedTaskMentionDTOListApiOutput = zod.output<typeof PaginatedTaskMentionDTOListApi>

export const RuntimeEnumApi = zod.enum(['acp', 'pi']).describe('\* `acp` - ACP\n\* `pi` - Pi')

export type RuntimeEnumApi = zod.input<typeof RuntimeEnumApi>
export type RuntimeEnumApiOutput = zod.output<typeof RuntimeEnumApi>

export const TaskRunDetailDTOProviderEnumApi = zod
    .enum(['anthropic', 'openai'])
    .describe('\* `anthropic` - anthropic\n\* `openai` - openai')

export type TaskRunDetailDTOProviderEnumApi = zod.input<typeof TaskRunDetailDTOProviderEnumApi>
export type TaskRunDetailDTOProviderEnumApiOutput = zod.output<typeof TaskRunDetailDTOProviderEnumApi>

export const taskRunArtifactMetadataApiSkillNameMax = 255

export const taskRunArtifactMetadataApiContentSha256RegExp = new RegExp('^[a-f0-9]{64}$')

export const TaskRunArtifactMetadataApi = zod.object({
    skill_name: zod
        .string()
        .max(taskRunArtifactMetadataApiSkillNameMax)
        .describe('Name of the local skill included in a skill_bundle artifact.'),
    skill_source: SkillSourceEnumApi.describe(
        'Local source for the uploaded skill bundle, such as user or repo.\n\n\* `user` - user\n\* `repo` - repo\n\* `marketplace` - marketplace\n\* `codex` - codex'
    ),
    content_sha256: zod
        .string()
        .regex(taskRunArtifactMetadataApiContentSha256RegExp)
        .describe('SHA-256 hex digest of the uploaded skill bundle bytes.'),
    bundle_format: BundleFormatEnumApi.describe('Archive format used for the local skill bundle.\n\n\* `zip` - zip'),
    schema_version: zod.number().min(1).describe('Version of the local skill bundle metadata schema.'),
})

export type TaskRunArtifactMetadataApi = zod.input<typeof TaskRunArtifactMetadataApi>
export type TaskRunArtifactMetadataApiOutput = zod.output<typeof TaskRunArtifactMetadataApi>

export const TaskRunArtifactResponseApi = zod.object({
    id: zod.string().optional().describe('Stable identifier for the artifact within this run'),
    name: zod.string().describe('Artifact file name'),
    type: zod.string().describe('Artifact classification (plan, context, etc.)'),
    source: zod.string().optional().describe('Source of the artifact, such as agent_output or user_attachment'),
    size: zod.number().optional().describe('Artifact size in bytes'),
    content_type: zod.string().optional().describe('Optional MIME type'),
    metadata: TaskRunArtifactMetadataApi.optional().describe(
        'Optional structured metadata for special artifact types, such as skill bundles.'
    ),
    storage_path: zod.string().describe('S3 object key for the artifact'),
    uploaded_at: zod.string().describe('Timestamp when the artifact was uploaded'),
    url: zod
        .url()
        .optional()
        .describe(
            'Presigned download URL for the artifact. Populated on the finalize-upload response so the caller can link to the file directly; it is time-limited and not persisted on the manifest.'
        ),
})

export type TaskRunArtifactResponseApi = zod.input<typeof TaskRunArtifactResponseApi>
export type TaskRunArtifactResponseApiOutput = zod.output<typeof TaskRunArtifactResponseApi>

export const TaskRunDetailDTOApi = zod
    .object({
        id: zod.uuid(),
        task: zod.uuid().describe('Parent task id this run belongs to.'),
        stage: zod.string().nullable(),
        branch: zod.string().nullable(),
        status: zod.string(),
        environment: zod.string(),
        runtime_adapter: zod
            .union([RuntimeAdapterEnumApi, zod.null()])
            .optional()
            .describe(
                "Configured runtime adapter for this run, such as 'claude' or 'codex'.\n\n\* `claude` - claude\n\* `codex` - codex"
            ),
        provider: zod
            .union([TaskRunDetailDTOProviderEnumApi, zod.null()])
            .optional()
            .describe(
                "Configured LLM provider for this run, such as 'anthropic' or 'openai'.\n\n\* `anthropic` - anthropic\n\* `openai` - openai"
            ),
        model: zod.string().nullish().describe('Configured LLM model identifier for this run.'),
        reasoning_effort: zod
            .union([ReasoningEffortEnumApi, zod.null()])
            .optional()
            .describe(
                'Configured reasoning effort for this run when the selected model supports it.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
            ),
        log_url: zod.url().nullish().describe('Presigned S3 URL for log access (valid for 1 hour).'),
        error_message: zod.string().nullable(),
        output: zod.record(zod.string(), zod.unknown()).nullable(),
        state: zod.record(zod.string(), zod.unknown()),
        artifacts: zod.array(TaskRunArtifactResponseApi),
        created_at: zod.iso.datetime({ offset: true }).nullish(),
        updated_at: zod.iso.datetime({ offset: true }).nullish(),
        completed_at: zod.iso.datetime({ offset: true }).nullish(),
    })
    .describe(
        'Detail response for a task run.\n\nReads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the\npresigned ``log_url`` and parses ``runtime_adapter`` \/ ``provider`` \/ ``model`` \/\n``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested\n``latest_run`` shape by the task detail response.'
    )

export type TaskRunDetailDTOApi = zod.input<typeof TaskRunDetailDTOApi>
export type TaskRunDetailDTOApiOutput = zod.output<typeof TaskRunDetailDTOApi>

export const TaskDetailDTOApi = zod
    .object({
        id: zod.uuid(),
        task_number: zod.number().nullable(),
        slug: zod.string(),
        title: zod.string(),
        title_manually_set: zod.boolean(),
        description: zod.string(),
        origin_product: zod.string(),
        runtime: RuntimeEnumApi.describe(
            "Agent protocol and harness used for this task's runs.\n\n\* `acp` - ACP\n\* `pi` - Pi"
        ),
        repository: zod.string().nullable(),
        github_integration: zod.number().nullable(),
        github_user_integration: zod.uuid().nullable(),
        signal_report: zod.uuid().nullable(),
        json_schema: zod.record(zod.string(), zod.unknown()).nullable(),
        internal: zod.boolean(),
        archived: zod.boolean(),
        archived_at: zod.iso.datetime({ offset: true }).nullable(),
        latest_run: zod
            .union([TaskRunDetailDTOApi, zod.null()])
            .optional()
            .describe('Latest run details for this task'),
        created_at: zod.iso.datetime({ offset: true }).nullish(),
        updated_at: zod.iso.datetime({ offset: true }).nullish(),
        created_by: zod.union([TaskUserBasicInfoApi, zod.null()]).optional(),
        ci_prompt: zod.string().nullable(),
        channel: zod.uuid().nullish(),
    })
    .describe(
        'Detail response for a task.\n\nReads from a frozen ``TaskDetailDTO`` produced by the facade. ``github_integration`` \/\n``github_user_integration`` are integration ids, ``signal_report`` is the report id, and\n``latest_run`` nests the run-detail shape. ``created_by`` mirrors core ``UserBasicSerializer``.'
    )

export type TaskDetailDTOApi = zod.input<typeof TaskDetailDTOApi>
export type TaskDetailDTOApiOutput = zod.output<typeof TaskDetailDTOApi>

export const PaginatedTaskDetailDTOListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(TaskDetailDTOApi),
})

export type PaginatedTaskDetailDTOListApi = zod.input<typeof PaginatedTaskDetailDTOListApi>
export type PaginatedTaskDetailDTOListApiOutput = zod.output<typeof PaginatedTaskDetailDTOListApi>

export const OriginProductEnumApi = zod
    .enum([
        'onboarding',
        'error_tracking',
        'eval_clusters',
        'user_created',
        'automation',
        'slack',
        'support_queue',
        'session_summaries',
        'posthog_ai',
        'experiments',
        'signal_report',
        'signals_scout',
        'support_reply',
        'hogdesk',
        'review_hog',
        'image_builder',
        'loop',
        'mcp_analytics',
    ])
    .describe(
        '\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `automation` - Automation\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop\n\* `mcp_analytics` - MCP Analytics'
    )

export type OriginProductEnumApi = zod.input<typeof OriginProductEnumApi>
export type OriginProductEnumApiOutput = zod.output<typeof OriginProductEnumApi>

export const taskCreateApiTitleMax = 255

export const taskCreateApiRepositoryMax = 255

export const taskCreateApiSignalReportTaskRelationshipMax = 200

export const taskCreateApiBranchMax = 255

export const taskCreateApiPendingUserArtifactIdsItemMax = 128

export const TaskCreateApi = zod
    .object({
        title: zod
            .string()
            .max(taskCreateApiTitleMax)
            .optional()
            .describe('Short human-readable title. Auto-generated from `description` when omitted.'),
        title_manually_set: zod
            .boolean()
            .optional()
            .describe('Whether the title was set by a human (vs auto-generated from the description).'),
        description: zod
            .string()
            .optional()
            .describe('Free-form description of the work to be done. Used as the prompt passed to the agent.'),
        origin_product: OriginProductEnumApi.optional().describe(
            'PostHog product or surface that created this task (e.g. error_tracking, slack, user_created). Origins reserved for server-created agents cannot be set through this API.\n\n\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `automation` - Automation\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop\n\* `mcp_analytics` - MCP Analytics'
        ),
        repository: zod
            .string()
            .max(taskCreateApiRepositoryMax)
            .nullish()
            .describe('Target GitHub repository in `organization\/repo` format (e.g. `posthog\/posthog-js`).'),
        github_integration: zod.number().nullish().describe('GitHub integration for this task.'),
        github_user_integration: zod
            .uuid()
            .nullish()
            .describe('User-scoped GitHub integration to use for user-authored cloud runs.'),
        signal_report: zod.uuid().nullish().describe('Signal report this task implements, when created from a report.'),
        signal_report_task_relationship: zod
            .string()
            .max(taskCreateApiSignalReportTaskRelationshipMax)
            .optional()
            .describe(
                "How the created task relates to the signal report (e.g. 'implementation', 'discussion', 'research'). Recorded as a signals task_run work-log entry; 'implementation' also opens the auto-start spend gate. Any routing-safe identifier (lowercase letters, numbers, '_', '-') is accepted."
            ),
        json_schema: zod.unknown().optional().describe('JSON schema used to validate the output of the task.'),
        internal: zod
            .boolean()
            .optional()
            .describe('If true, this task is for internal use and should not be exposed to end users.'),
        archived: zod.boolean().optional().describe('If true, the task is hidden from default list responses.'),
        ci_prompt: zod
            .string()
            .nullish()
            .describe('Custom prompt for CI fixes. If blank, a default prompt will be used.'),
        branch: zod
            .string()
            .max(taskCreateApiBranchMax)
            .nullish()
            .describe(
                'Branch the user has selected for this cloud task. Write-only and not persisted on the task itself: used only to reuse a matching pre-warmed sandbox Run on creation (the branch is otherwise carried on the run). Omit to match a warm Run on the default branch.'
            ),
        runtime_adapter: zod
            .union([RuntimeAdapterEnumApi, zod.null()])
            .optional()
            .describe(
                "Selected runtime adapter ('claude' or 'codex'). Write-only and not persisted on the task: used only to reuse a pre-warmed Run started on the same runtime. A value differing from the warm Run's runtime skips reuse so the task isn't silently run on the wrong runtime.\n\n\* `claude` - claude\n\* `codex` - codex"
            ),
        model: zod
            .string()
            .nullish()
            .describe(
                'Selected LLM model identifier. Write-only; used only to reuse a warm Run started on the same model.'
            ),
        reasoning_effort: zod
            .union([ReasoningEffortEnumApi, zod.null()])
            .optional()
            .describe(
                'Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
            ),
        pending_user_message: zod
            .string()
            .nullish()
            .describe(
                'First user message to forward when creation reuses a pre-warmed Run. Write-only and not persisted on the task: lets clients deliver a message that differs from `description` (e.g. a resolved skill invocation with channel context folded in). Ignored when no warm Run is reused — cold creation takes the first message via the run start endpoint instead.'
            ),
        pending_user_artifact_ids: zod
            .array(zod.string().max(taskCreateApiPendingUserArtifactIdsItemMax))
            .optional()
            .describe(
                "Run artifact ids (already uploaded to the pre-warmed Run) to attach to the forwarded first message when creation reuses that warm Run, e.g. skill bundles or file attachments. If any id is missing from the warm Run's manifest, warm reuse is skipped and the task is created cold. Ignored when no warm Run is matched."
            ),
        auto_publish: zod
            .boolean()
            .nullish()
            .describe(
                "When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask. Write-only and not persisted on the task: persisted into the reused warm Run's state when creation activates one, so resumes of that Run honor it. Ignored when no warm Run is reused — cold creation takes it via the run start endpoint instead."
            ),
        channel: zod.uuid().nullish().describe('Channel this task is owned by (the channel it was kicked off in).'),
        sandbox_environment_id: zod
            .uuid()
            .nullish()
            .describe('Sandbox environment selected for matching a pre-warmed cloud run. Not persisted on the task.'),
        custom_image_id: zod
            .uuid()
            .nullish()
            .describe('Custom image selected for matching a pre-warmed cloud run. Not persisted on the task.'),
        runtime: RuntimeEnumApi.optional().describe(
            "Agent protocol and harness used for this task's runs. Defaults to ACP when omitted.\n\n\* `acp` - ACP\n\* `pi` - Pi"
        ),
    })
    .describe(
        'Request body for creating or updating a task.\n\nField required\/default semantics match the ``Task`` model. The view passes\n``validated_data`` (integration\/report PK fields already resolved to instances) to the\nfacade ``create_task`` \/ ``update_task`` functions.'
    )

export type TaskCreateApi = zod.input<typeof TaskCreateApi>
export type TaskCreateApiOutput = zod.output<typeof TaskCreateApi>

export const taskWriteApiTitleMax = 255

export const taskWriteApiRepositoryMax = 255

export const taskWriteApiSignalReportTaskRelationshipMax = 200

export const taskWriteApiBranchMax = 255

export const taskWriteApiPendingUserArtifactIdsItemMax = 128

export const TaskWriteApi = zod
    .object({
        title: zod
            .string()
            .max(taskWriteApiTitleMax)
            .optional()
            .describe('Short human-readable title. Auto-generated from `description` when omitted.'),
        title_manually_set: zod
            .boolean()
            .optional()
            .describe('Whether the title was set by a human (vs auto-generated from the description).'),
        description: zod
            .string()
            .optional()
            .describe('Free-form description of the work to be done. Used as the prompt passed to the agent.'),
        origin_product: OriginProductEnumApi.optional().describe(
            'PostHog product or surface that created this task (e.g. error_tracking, slack, user_created). Origins reserved for server-created agents cannot be set through this API.\n\n\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `automation` - Automation\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop\n\* `mcp_analytics` - MCP Analytics'
        ),
        repository: zod
            .string()
            .max(taskWriteApiRepositoryMax)
            .nullish()
            .describe('Target GitHub repository in `organization\/repo` format (e.g. `posthog\/posthog-js`).'),
        github_integration: zod.number().nullish().describe('GitHub integration for this task.'),
        github_user_integration: zod
            .uuid()
            .nullish()
            .describe('User-scoped GitHub integration to use for user-authored cloud runs.'),
        signal_report: zod.uuid().nullish().describe('Signal report this task implements, when created from a report.'),
        signal_report_task_relationship: zod
            .string()
            .max(taskWriteApiSignalReportTaskRelationshipMax)
            .optional()
            .describe(
                "How the created task relates to the signal report (e.g. 'implementation', 'discussion', 'research'). Recorded as a signals task_run work-log entry; 'implementation' also opens the auto-start spend gate. Any routing-safe identifier (lowercase letters, numbers, '_', '-') is accepted."
            ),
        json_schema: zod.unknown().optional().describe('JSON schema used to validate the output of the task.'),
        internal: zod
            .boolean()
            .optional()
            .describe('If true, this task is for internal use and should not be exposed to end users.'),
        archived: zod.boolean().optional().describe('If true, the task is hidden from default list responses.'),
        ci_prompt: zod
            .string()
            .nullish()
            .describe('Custom prompt for CI fixes. If blank, a default prompt will be used.'),
        branch: zod
            .string()
            .max(taskWriteApiBranchMax)
            .nullish()
            .describe(
                'Branch the user has selected for this cloud task. Write-only and not persisted on the task itself: used only to reuse a matching pre-warmed sandbox Run on creation (the branch is otherwise carried on the run). Omit to match a warm Run on the default branch.'
            ),
        runtime_adapter: zod
            .union([RuntimeAdapterEnumApi, zod.null()])
            .optional()
            .describe(
                "Selected runtime adapter ('claude' or 'codex'). Write-only and not persisted on the task: used only to reuse a pre-warmed Run started on the same runtime. A value differing from the warm Run's runtime skips reuse so the task isn't silently run on the wrong runtime.\n\n\* `claude` - claude\n\* `codex` - codex"
            ),
        model: zod
            .string()
            .nullish()
            .describe(
                'Selected LLM model identifier. Write-only; used only to reuse a warm Run started on the same model.'
            ),
        reasoning_effort: zod
            .union([ReasoningEffortEnumApi, zod.null()])
            .optional()
            .describe(
                'Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
            ),
        pending_user_message: zod
            .string()
            .nullish()
            .describe(
                'First user message to forward when creation reuses a pre-warmed Run. Write-only and not persisted on the task: lets clients deliver a message that differs from `description` (e.g. a resolved skill invocation with channel context folded in). Ignored when no warm Run is reused — cold creation takes the first message via the run start endpoint instead.'
            ),
        pending_user_artifact_ids: zod
            .array(zod.string().max(taskWriteApiPendingUserArtifactIdsItemMax))
            .optional()
            .describe(
                "Run artifact ids (already uploaded to the pre-warmed Run) to attach to the forwarded first message when creation reuses that warm Run, e.g. skill bundles or file attachments. If any id is missing from the warm Run's manifest, warm reuse is skipped and the task is created cold. Ignored when no warm Run is matched."
            ),
        auto_publish: zod
            .boolean()
            .nullish()
            .describe(
                "When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask. Write-only and not persisted on the task: persisted into the reused warm Run's state when creation activates one, so resumes of that Run honor it. Ignored when no warm Run is reused — cold creation takes it via the run start endpoint instead."
            ),
        channel: zod.uuid().nullish().describe('Channel this task is owned by (the channel it was kicked off in).'),
    })
    .describe(
        'Request body for creating or updating a task.\n\nField required\/default semantics match the ``Task`` model. The view passes\n``validated_data`` (integration\/report PK fields already resolved to instances) to the\nfacade ``create_task`` \/ ``update_task`` functions.'
    )

export type TaskWriteApi = zod.input<typeof TaskWriteApi>
export type TaskWriteApiOutput = zod.output<typeof TaskWriteApi>

export const patchedTaskWriteApiTitleMax = 255

export const patchedTaskWriteApiRepositoryMax = 255

export const patchedTaskWriteApiSignalReportTaskRelationshipMax = 200

export const patchedTaskWriteApiBranchMax = 255

export const patchedTaskWriteApiPendingUserArtifactIdsItemMax = 128

export const PatchedTaskWriteApi = zod
    .object({
        title: zod
            .string()
            .max(patchedTaskWriteApiTitleMax)
            .optional()
            .describe('Short human-readable title. Auto-generated from `description` when omitted.'),
        title_manually_set: zod
            .boolean()
            .optional()
            .describe('Whether the title was set by a human (vs auto-generated from the description).'),
        description: zod
            .string()
            .optional()
            .describe('Free-form description of the work to be done. Used as the prompt passed to the agent.'),
        origin_product: OriginProductEnumApi.optional().describe(
            'PostHog product or surface that created this task (e.g. error_tracking, slack, user_created). Origins reserved for server-created agents cannot be set through this API.\n\n\* `onboarding` - Onboarding\n\* `error_tracking` - Error Tracking\n\* `eval_clusters` - Eval Clusters\n\* `user_created` - User Created\n\* `automation` - Automation\n\* `slack` - Slack\n\* `support_queue` - Support Queue\n\* `session_summaries` - Session Summaries\n\* `posthog_ai` - PostHog AI\n\* `experiments` - Experiments\n\* `signal_report` - Signal Report\n\* `signals_scout` - Signals Scout\n\* `support_reply` - Support Reply\n\* `hogdesk` - HogDesk\n\* `review_hog` - ReviewHog\n\* `image_builder` - Image Builder\n\* `loop` - Loop\n\* `mcp_analytics` - MCP Analytics'
        ),
        repository: zod
            .string()
            .max(patchedTaskWriteApiRepositoryMax)
            .nullish()
            .describe('Target GitHub repository in `organization\/repo` format (e.g. `posthog\/posthog-js`).'),
        github_integration: zod.number().nullish().describe('GitHub integration for this task.'),
        github_user_integration: zod
            .uuid()
            .nullish()
            .describe('User-scoped GitHub integration to use for user-authored cloud runs.'),
        signal_report: zod.uuid().nullish().describe('Signal report this task implements, when created from a report.'),
        signal_report_task_relationship: zod
            .string()
            .max(patchedTaskWriteApiSignalReportTaskRelationshipMax)
            .optional()
            .describe(
                "How the created task relates to the signal report (e.g. 'implementation', 'discussion', 'research'). Recorded as a signals task_run work-log entry; 'implementation' also opens the auto-start spend gate. Any routing-safe identifier (lowercase letters, numbers, '_', '-') is accepted."
            ),
        json_schema: zod.unknown().optional().describe('JSON schema used to validate the output of the task.'),
        internal: zod
            .boolean()
            .optional()
            .describe('If true, this task is for internal use and should not be exposed to end users.'),
        archived: zod.boolean().optional().describe('If true, the task is hidden from default list responses.'),
        ci_prompt: zod
            .string()
            .nullish()
            .describe('Custom prompt for CI fixes. If blank, a default prompt will be used.'),
        branch: zod
            .string()
            .max(patchedTaskWriteApiBranchMax)
            .nullish()
            .describe(
                'Branch the user has selected for this cloud task. Write-only and not persisted on the task itself: used only to reuse a matching pre-warmed sandbox Run on creation (the branch is otherwise carried on the run). Omit to match a warm Run on the default branch.'
            ),
        runtime_adapter: zod
            .union([RuntimeAdapterEnumApi, zod.null()])
            .optional()
            .describe(
                "Selected runtime adapter ('claude' or 'codex'). Write-only and not persisted on the task: used only to reuse a pre-warmed Run started on the same runtime. A value differing from the warm Run's runtime skips reuse so the task isn't silently run on the wrong runtime.\n\n\* `claude` - claude\n\* `codex` - codex"
            ),
        model: zod
            .string()
            .nullish()
            .describe(
                'Selected LLM model identifier. Write-only; used only to reuse a warm Run started on the same model.'
            ),
        reasoning_effort: zod
            .union([ReasoningEffortEnumApi, zod.null()])
            .optional()
            .describe(
                'Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
            ),
        pending_user_message: zod
            .string()
            .nullish()
            .describe(
                'First user message to forward when creation reuses a pre-warmed Run. Write-only and not persisted on the task: lets clients deliver a message that differs from `description` (e.g. a resolved skill invocation with channel context folded in). Ignored when no warm Run is reused — cold creation takes the first message via the run start endpoint instead.'
            ),
        pending_user_artifact_ids: zod
            .array(zod.string().max(patchedTaskWriteApiPendingUserArtifactIdsItemMax))
            .optional()
            .describe(
                "Run artifact ids (already uploaded to the pre-warmed Run) to attach to the forwarded first message when creation reuses that warm Run, e.g. skill bundles or file attachments. If any id is missing from the warm Run's manifest, warm reuse is skipped and the task is created cold. Ignored when no warm Run is matched."
            ),
        auto_publish: zod
            .boolean()
            .nullish()
            .describe(
                "When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask. Write-only and not persisted on the task: persisted into the reused warm Run's state when creation activates one, so resumes of that Run honor it. Ignored when no warm Run is reused — cold creation takes it via the run start endpoint instead."
            ),
        channel: zod.uuid().nullish().describe('Channel this task is owned by (the channel it was kicked off in).'),
    })
    .describe(
        'Request body for creating or updating a task.\n\nField required\/default semantics match the ``Task`` model. The view passes\n``validated_data`` (integration\/report PK fields already resolved to instances) to the\nfacade ``create_task`` \/ ``update_task`` functions.'
    )

export type PatchedTaskWriteApi = zod.input<typeof PatchedTaskWriteApi>
export type PatchedTaskWriteApiOutput = zod.output<typeof PatchedTaskWriteApi>

export const TaskPinRequestApi = zod.object({
    pinned: zod.boolean().describe('Whether the task should be pinned for the requester.'),
})

export type TaskPinRequestApi = zod.input<typeof TaskPinRequestApi>
export type TaskPinRequestApiOutput = zod.output<typeof TaskPinRequestApi>

export const TaskPinResponseApi = zod.object({
    task_id: zod.uuid().describe('Task whose pin state was updated.'),
    pinned: zod.boolean().describe('Current pin state for the requester.'),
})

export type TaskPinResponseApi = zod.input<typeof TaskPinResponseApi>
export type TaskPinResponseApiOutput = zod.output<typeof TaskPinResponseApi>

export const TaskPresenceBeaconRequestApi = zod
    .object({
        device_id: zod
            .uuid()
            .describe(
                "UUID of the caller's UserPushToken (returned by `\/api\/users\/@me\/push_tokens\/` on register)."
            ),
    })
    .describe(
        "Request body for the presence beacon and beacon-leave endpoints.\n\n`device_id` is the UUID of the caller's `UserPushToken` row, which the\nclient received when it registered for push via `\/api\/users\/@me\/push_tokens\/`.\nThe client is expected to use the same identifier on the beacon and leave\ncalls; if the user has unregistered the underlying push token, the value\nwon't resolve and the call returns 404 — at which point pushes were\nalready not going there anyway."
    )

export type TaskPresenceBeaconRequestApi = zod.input<typeof TaskPresenceBeaconRequestApi>
export type TaskPresenceBeaconRequestApiOutput = zod.output<typeof TaskPresenceBeaconRequestApi>

export const ImportedMcpServerTypeEnumApi = zod.enum(['http', 'sse']).describe('\* `http` - http\n\* `sse` - sse')

export type ImportedMcpServerTypeEnumApi = zod.input<typeof ImportedMcpServerTypeEnumApi>
export type ImportedMcpServerTypeEnumApiOutput = zod.output<typeof ImportedMcpServerTypeEnumApi>

export const importedMcpServerHeaderApiNameMax = 256

export const importedMcpServerHeaderApiValueMax = 4096

export const ImportedMcpServerHeaderApi = zod.object({
    name: zod.string().max(importedMcpServerHeaderApiNameMax),
    value: zod.string().max(importedMcpServerHeaderApiValueMax),
})

export type ImportedMcpServerHeaderApi = zod.input<typeof ImportedMcpServerHeaderApi>
export type ImportedMcpServerHeaderApiOutput = zod.output<typeof ImportedMcpServerHeaderApi>

export const importedMcpServerApiNameMax = 64

export const importedMcpServerApiUrlMax = 2048

export const ImportedMcpServerApi = zod
    .object({
        type: ImportedMcpServerTypeEnumApi,
        name: zod.string().max(importedMcpServerApiNameMax),
        url: zod.url().max(importedMcpServerApiUrlMax),
        headers: zod.array(ImportedMcpServerHeaderApi).optional(),
    })
    .describe("One client-imported MCP server, in the agent server's --mcpServers entry shape.")

export type ImportedMcpServerApi = zod.input<typeof ImportedMcpServerApi>
export type ImportedMcpServerApiOutput = zod.output<typeof ImportedMcpServerApi>

export const relayedMcpServerApiNameMax = 64

export const RelayedMcpServerApi = zod
    .object({
        name: zod.string().max(relayedMcpServerApiNameMax),
    })
    .describe('One desktop-only MCP server relayed into the run — a name only, never configuration.')

export type RelayedMcpServerApi = zod.input<typeof RelayedMcpServerApi>
export type RelayedMcpServerApiOutput = zod.output<typeof RelayedMcpServerApi>

export const TaskExecutionModeEnumApi = zod
    .enum(['interactive', 'background'])
    .describe('\* `interactive` - interactive\n\* `background` - background')

export type TaskExecutionModeEnumApi = zod.input<typeof TaskExecutionModeEnumApi>
export type TaskExecutionModeEnumApiOutput = zod.output<typeof TaskExecutionModeEnumApi>

export const PrAuthorshipModeEnumApi = zod.enum(['user', 'bot']).describe('\* `user` - user\n\* `bot` - bot')

export type PrAuthorshipModeEnumApi = zod.input<typeof PrAuthorshipModeEnumApi>
export type PrAuthorshipModeEnumApiOutput = zod.output<typeof PrAuthorshipModeEnumApi>

export const RunSourceEnumApi = zod
    .enum(['manual', 'signal_report'])
    .describe('\* `manual` - manual\n\* `signal_report` - signal_report')

export type RunSourceEnumApi = zod.input<typeof RunSourceEnumApi>
export type RunSourceEnumApiOutput = zod.output<typeof RunSourceEnumApi>

export const ClaudeRuntimeAdapterEnumApi = zod.enum(['claude']).describe('\* `claude` - claude')

export type ClaudeRuntimeAdapterEnumApi = zod.input<typeof ClaudeRuntimeAdapterEnumApi>
export type ClaudeRuntimeAdapterEnumApiOutput = zod.output<typeof ClaudeRuntimeAdapterEnumApi>

export const ContextWindowEnumApi = zod.enum(['200k', '1m']).describe('\* `200k` - 200k\n\* `1m` - 1m')

export type ContextWindowEnumApi = zod.input<typeof ContextWindowEnumApi>
export type ContextWindowEnumApiOutput = zod.output<typeof ContextWindowEnumApi>

export const InitialPermissionModeEnumApi = zod
    .enum(['default', 'acceptEdits', 'plan', 'bypassPermissions', 'auto'])
    .describe(
        '\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto'
    )

export type InitialPermissionModeEnumApi = zod.input<typeof InitialPermissionModeEnumApi>
export type InitialPermissionModeEnumApiOutput = zod.output<typeof InitialPermissionModeEnumApi>

export const claudeTaskRunCreateSchemaApiModeDefault = `background`
export const claudeTaskRunCreateSchemaApiBranchMax = 255

export const claudeTaskRunCreateSchemaApiPendingUserArtifactIdsItemMax = 128

export const ClaudeTaskRunCreateSchemaApi = zod
    .object({
        imported_mcp_servers: zod
            .array(ImportedMcpServerApi)
            .nullish()
            .describe(
                'Local url-based MCP servers from the creating client (PostHog Desktop) to make available inside the cloud sandbox. Header values are treated as credentials: stored encrypted and never returned by the API.'
            ),
        relayed_mcp_servers: zod
            .array(RelayedMcpServerApi)
            .nullish()
            .describe(
                'Names of desktop-only MCP servers the creating client (PostHog Desktop) relays into the cloud sandbox over the durable event\/command channel. Names only — the server configuration (command, env, URL, headers) never crosses the wire.'
            ),
        mode: TaskExecutionModeEnumApi.default(claudeTaskRunCreateSchemaApiModeDefault).describe(
            "Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs\n\n\* `interactive` - interactive\n\* `background` - background"
        ),
        branch: zod
            .string()
            .max(claudeTaskRunCreateSchemaApiBranchMax)
            .nullish()
            .describe('Git branch to checkout in the sandbox'),
        resume_from_run_id: zod
            .uuid()
            .optional()
            .describe('ID of a previous run to resume from. Must belong to the same task.'),
        pending_user_message: zod
            .string()
            .optional()
            .describe('Initial or follow-up user message to include in the run prompt.'),
        pending_user_artifact_ids: zod
            .array(zod.string().max(claudeTaskRunCreateSchemaApiPendingUserArtifactIdsItemMax))
            .optional()
            .describe('Identifiers for staged task artifacts that should be attached to the initial run prompt.'),
        sandbox_environment_id: zod
            .uuid()
            .optional()
            .describe('Optional sandbox environment to apply for this cloud run.'),
        custom_image_id: zod
            .uuid()
            .optional()
            .describe(
                "Optional custom base image for this cloud run's sandbox (Modal VM runtime only); takes precedence over the environment's image."
            ),
        pr_authorship_mode: PrAuthorshipModeEnumApi.optional().describe(
            'Whether pull requests for this run should be authored by the user or the bot.\n\n\* `user` - user\n\* `bot` - bot'
        ),
        auto_publish: zod
            .boolean()
            .nullish()
            .describe(
                'When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask.'
            ),
        run_source: RunSourceEnumApi.optional().describe(
            'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n\* `manual` - manual\n\* `signal_report` - signal_report'
        ),
        signal_report_id: zod
            .string()
            .optional()
            .describe('Optional signal report identifier when this run was started from Inbox.'),
        runtime_adapter: ClaudeRuntimeAdapterEnumApi.describe(
            "Agent runtime adapter to launch for this run. Must be 'claude' for Claude runtimes.\n\n\* `claude` - claude"
        ),
        model: zod.string().describe('LLM model identifier to run in the Claude runtime.'),
        reasoning_effort: ReasoningEffortEnumApi.optional().describe(
            'Reasoning effort to request for models that expose an effort control.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
        ),
        context_window: ContextWindowEnumApi.optional().describe(
            'Context window size for models that support the 1M window.\n\n\* `200k` - 200k\n\* `1m` - 1m'
        ),
        fast_mode: zod.boolean().nullish().describe('Enable fast mode for models that support it.'),
        github_user_token: zod
            .string()
            .optional()
            .describe(
                'Optional GitHub user token from PostHog Desktop for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens.'
            ),
        initial_permission_mode: InitialPermissionModeEnumApi.optional().describe(
            'Initial permission mode for Claude runtimes.\n\n\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto'
        ),
        rtk_enabled: zod
            .boolean()
            .nullish()
            .describe(
                'Whether rtk command-output compression is enabled for this run. Omitted or null follows the server-side default (enabled); false opts this run out.'
            ),
    })
    .describe('Request body for creating a new task run')

export type ClaudeTaskRunCreateSchemaApi = zod.input<typeof ClaudeTaskRunCreateSchemaApi>
export type ClaudeTaskRunCreateSchemaApiOutput = zod.output<typeof ClaudeTaskRunCreateSchemaApi>

export const CodexRuntimeAdapterEnumApi = zod.enum(['codex']).describe('\* `codex` - codex')

export type CodexRuntimeAdapterEnumApi = zod.input<typeof CodexRuntimeAdapterEnumApi>
export type CodexRuntimeAdapterEnumApiOutput = zod.output<typeof CodexRuntimeAdapterEnumApi>

export const CodexTaskRunCreateSchemaInitialPermissionModeEnumApi = zod
    .enum(['plan', 'auto', 'read-only', 'full-access'])
    .describe('\* `plan` - plan\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access')

export type CodexTaskRunCreateSchemaInitialPermissionModeEnumApi = zod.input<
    typeof CodexTaskRunCreateSchemaInitialPermissionModeEnumApi
>
export type CodexTaskRunCreateSchemaInitialPermissionModeEnumApiOutput = zod.output<
    typeof CodexTaskRunCreateSchemaInitialPermissionModeEnumApi
>

export const codexTaskRunCreateSchemaApiModeDefault = `background`
export const codexTaskRunCreateSchemaApiBranchMax = 255

export const codexTaskRunCreateSchemaApiPendingUserArtifactIdsItemMax = 128

export const CodexTaskRunCreateSchemaApi = zod
    .object({
        imported_mcp_servers: zod
            .array(ImportedMcpServerApi)
            .nullish()
            .describe(
                'Local url-based MCP servers from the creating client (PostHog Desktop) to make available inside the cloud sandbox. Header values are treated as credentials: stored encrypted and never returned by the API.'
            ),
        relayed_mcp_servers: zod
            .array(RelayedMcpServerApi)
            .nullish()
            .describe(
                'Names of desktop-only MCP servers the creating client (PostHog Desktop) relays into the cloud sandbox over the durable event\/command channel. Names only — the server configuration (command, env, URL, headers) never crosses the wire.'
            ),
        mode: TaskExecutionModeEnumApi.default(codexTaskRunCreateSchemaApiModeDefault).describe(
            "Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs\n\n\* `interactive` - interactive\n\* `background` - background"
        ),
        branch: zod
            .string()
            .max(codexTaskRunCreateSchemaApiBranchMax)
            .nullish()
            .describe('Git branch to checkout in the sandbox'),
        resume_from_run_id: zod
            .uuid()
            .optional()
            .describe('ID of a previous run to resume from. Must belong to the same task.'),
        pending_user_message: zod
            .string()
            .optional()
            .describe('Initial or follow-up user message to include in the run prompt.'),
        pending_user_artifact_ids: zod
            .array(zod.string().max(codexTaskRunCreateSchemaApiPendingUserArtifactIdsItemMax))
            .optional()
            .describe('Identifiers for staged task artifacts that should be attached to the initial run prompt.'),
        sandbox_environment_id: zod
            .uuid()
            .optional()
            .describe('Optional sandbox environment to apply for this cloud run.'),
        custom_image_id: zod
            .uuid()
            .optional()
            .describe(
                "Optional custom base image for this cloud run's sandbox (Modal VM runtime only); takes precedence over the environment's image."
            ),
        pr_authorship_mode: PrAuthorshipModeEnumApi.optional().describe(
            'Whether pull requests for this run should be authored by the user or the bot.\n\n\* `user` - user\n\* `bot` - bot'
        ),
        auto_publish: zod
            .boolean()
            .nullish()
            .describe(
                'When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask.'
            ),
        run_source: RunSourceEnumApi.optional().describe(
            'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n\* `manual` - manual\n\* `signal_report` - signal_report'
        ),
        signal_report_id: zod
            .string()
            .optional()
            .describe('Optional signal report identifier when this run was started from Inbox.'),
        runtime_adapter: CodexRuntimeAdapterEnumApi.describe(
            "Agent runtime adapter to launch for this run. Must be 'codex' for Codex runtimes.\n\n\* `codex` - codex"
        ),
        model: zod.string().describe('LLM model identifier to run in the Codex runtime.'),
        reasoning_effort: ReasoningEffortEnumApi.optional().describe(
            'Reasoning effort to request for models that expose an effort control.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
        ),
        context_window: ContextWindowEnumApi.optional().describe(
            'Context window size for models that support the 1M window.\n\n\* `200k` - 200k\n\* `1m` - 1m'
        ),
        fast_mode: zod.boolean().nullish().describe('Enable fast mode for models that support it.'),
        github_user_token: zod
            .string()
            .optional()
            .describe(
                'Optional GitHub user token from PostHog Desktop for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens.'
            ),
        initial_permission_mode: CodexTaskRunCreateSchemaInitialPermissionModeEnumApi.optional().describe(
            'Initial permission mode for Codex runtimes.\n\n\* `plan` - plan\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access'
        ),
        rtk_enabled: zod
            .boolean()
            .nullish()
            .describe(
                'Whether rtk command-output compression is enabled for this run. Omitted or null follows the server-side default (enabled); false opts this run out.'
            ),
    })
    .describe('Request body for creating a new task run')

export type CodexTaskRunCreateSchemaApi = zod.input<typeof CodexTaskRunCreateSchemaApi>
export type CodexTaskRunCreateSchemaApiOutput = zod.output<typeof CodexTaskRunCreateSchemaApi>

export const taskRunResumeRequestSchemaApiModeDefault = `background`
export const taskRunResumeRequestSchemaApiBranchMax = 255

export const TaskRunResumeRequestSchemaApi = zod.object({
    mode: TaskExecutionModeEnumApi.default(taskRunResumeRequestSchemaApiModeDefault).describe(
        "Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs\n\n\* `interactive` - interactive\n\* `background` - background"
    ),
    branch: zod
        .string()
        .max(taskRunResumeRequestSchemaApiBranchMax)
        .nullish()
        .describe('Git branch to checkout in the sandbox'),
    resume_from_run_id: zod
        .uuid()
        .optional()
        .describe('ID of a previous run to resume from. Must belong to the same task.'),
    pending_user_message: zod
        .string()
        .optional()
        .describe('Initial or follow-up user message to include in the run prompt.'),
    sandbox_environment_id: zod.uuid().optional().describe('Optional sandbox environment to apply for this cloud run.'),
    custom_image_id: zod
        .uuid()
        .optional()
        .describe(
            "Optional custom base image for this cloud run's sandbox (Modal VM runtime only); takes precedence over the environment's image."
        ),
    pr_authorship_mode: PrAuthorshipModeEnumApi.optional().describe(
        'Whether pull requests for this run should be authored by the user or the bot.\n\n\* `user` - user\n\* `bot` - bot'
    ),
    run_source: RunSourceEnumApi.optional().describe(
        'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n\* `manual` - manual\n\* `signal_report` - signal_report'
    ),
    signal_report_id: zod
        .string()
        .optional()
        .describe('Optional signal report identifier when this run was started from Inbox.'),
    github_user_token: zod
        .string()
        .optional()
        .describe(
            'Optional GitHub user token from PostHog Desktop for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens.'
        ),
})

export type TaskRunResumeRequestSchemaApi = zod.input<typeof TaskRunResumeRequestSchemaApi>
export type TaskRunResumeRequestSchemaApiOutput = zod.output<typeof TaskRunResumeRequestSchemaApi>

export const TaskRunCreateRequestSchemaApi = zod.union([
    ClaudeTaskRunCreateSchemaApi,
    CodexTaskRunCreateSchemaApi,
    TaskRunResumeRequestSchemaApi,
])

export type TaskRunCreateRequestSchemaApi = zod.input<typeof TaskRunCreateRequestSchemaApi>
export type TaskRunCreateRequestSchemaApiOutput = zod.output<typeof TaskRunCreateRequestSchemaApi>

export const TaskRunArtifactTypeEnumApi = zod
    .enum(['plan', 'context', 'reference', 'output', 'artifact', 'tree_snapshot', 'user_attachment', 'skill_bundle'])
    .describe(
        '\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
    )

export type TaskRunArtifactTypeEnumApi = zod.input<typeof TaskRunArtifactTypeEnumApi>
export type TaskRunArtifactTypeEnumApiOutput = zod.output<typeof TaskRunArtifactTypeEnumApi>

export const taskStagedArtifactFinalizeUploadApiNameMax = 255

export const taskStagedArtifactFinalizeUploadApiSourceDefault = ``
export const taskStagedArtifactFinalizeUploadApiSourceMax = 64

export const taskStagedArtifactFinalizeUploadApiStoragePathMax = 500

export const taskStagedArtifactFinalizeUploadApiContentTypeMax = 255

export const TaskStagedArtifactFinalizeUploadApi = zod.object({
    id: zod.string().describe('Stable identifier returned by the staged prepare upload endpoint'),
    name: zod
        .string()
        .max(taskStagedArtifactFinalizeUploadApiNameMax)
        .describe('File name associated with the staged artifact'),
    type: TaskRunArtifactTypeEnumApi.describe(
        'Classification for the artifact\n\n\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
    ),
    source: zod
        .string()
        .max(taskStagedArtifactFinalizeUploadApiSourceMax)
        .default(taskStagedArtifactFinalizeUploadApiSourceDefault)
        .describe('Optional source label for the artifact, such as agent_output or user_attachment'),
    storage_path: zod
        .string()
        .max(taskStagedArtifactFinalizeUploadApiStoragePathMax)
        .describe('S3 object key returned by the prepare step'),
    content_type: zod
        .string()
        .max(taskStagedArtifactFinalizeUploadApiContentTypeMax)
        .optional()
        .describe('Optional MIME type recorded for the artifact'),
    metadata: TaskRunArtifactMetadataApi.optional().describe(
        'Optional structured metadata for special artifact types, such as skill bundles.'
    ),
})

export type TaskStagedArtifactFinalizeUploadApi = zod.input<typeof TaskStagedArtifactFinalizeUploadApi>
export type TaskStagedArtifactFinalizeUploadApiOutput = zod.output<typeof TaskStagedArtifactFinalizeUploadApi>

export const TaskStagedArtifactsFinalizeUploadRequestApi = zod.object({
    artifacts: zod
        .array(TaskStagedArtifactFinalizeUploadApi)
        .describe('Array of staged artifacts to finalize after upload'),
})

export type TaskStagedArtifactsFinalizeUploadRequestApi = zod.input<typeof TaskStagedArtifactsFinalizeUploadRequestApi>
export type TaskStagedArtifactsFinalizeUploadRequestApiOutput = zod.output<
    typeof TaskStagedArtifactsFinalizeUploadRequestApi
>

export const TaskStagedArtifactsFinalizeUploadResponseApi = zod.object({
    artifacts: zod
        .array(TaskRunArtifactResponseApi)
        .describe('Finalized staged artifacts available for attachment to a new run'),
})

export type TaskStagedArtifactsFinalizeUploadResponseApi = zod.input<
    typeof TaskStagedArtifactsFinalizeUploadResponseApi
>
export type TaskStagedArtifactsFinalizeUploadResponseApiOutput = zod.output<
    typeof TaskStagedArtifactsFinalizeUploadResponseApi
>

export const taskStagedArtifactPrepareUploadApiNameMax = 255

export const taskStagedArtifactPrepareUploadApiSourceDefault = ``
export const taskStagedArtifactPrepareUploadApiSourceMax = 64

export const taskStagedArtifactPrepareUploadApiSizeMax = 31457280

export const taskStagedArtifactPrepareUploadApiContentTypeMax = 255

export const TaskStagedArtifactPrepareUploadApi = zod.object({
    name: zod
        .string()
        .max(taskStagedArtifactPrepareUploadApiNameMax)
        .describe('File name to associate with the staged artifact'),
    type: TaskRunArtifactTypeEnumApi.describe(
        'Classification for the artifact\n\n\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
    ),
    source: zod
        .string()
        .max(taskStagedArtifactPrepareUploadApiSourceMax)
        .default(taskStagedArtifactPrepareUploadApiSourceDefault)
        .describe('Optional source label for the artifact, such as agent_output or user_attachment'),
    size: zod
        .number()
        .min(1)
        .max(taskStagedArtifactPrepareUploadApiSizeMax)
        .describe('Expected upload size in bytes (max 31457280 bytes)'),
    content_type: zod
        .string()
        .max(taskStagedArtifactPrepareUploadApiContentTypeMax)
        .optional()
        .describe('Optional MIME type for the artifact upload'),
    metadata: TaskRunArtifactMetadataApi.optional().describe(
        'Optional structured metadata for special artifact types, such as skill bundles.'
    ),
})

export type TaskStagedArtifactPrepareUploadApi = zod.input<typeof TaskStagedArtifactPrepareUploadApi>
export type TaskStagedArtifactPrepareUploadApiOutput = zod.output<typeof TaskStagedArtifactPrepareUploadApi>

export const TaskStagedArtifactsPrepareUploadRequestApi = zod.object({
    artifacts: zod
        .array(TaskStagedArtifactPrepareUploadApi)
        .describe('Array of staged artifacts to prepare before creating a run'),
})

export type TaskStagedArtifactsPrepareUploadRequestApi = zod.input<typeof TaskStagedArtifactsPrepareUploadRequestApi>
export type TaskStagedArtifactsPrepareUploadRequestApiOutput = zod.output<
    typeof TaskStagedArtifactsPrepareUploadRequestApi
>

export const S3PresignedPostApi = zod.object({
    url: zod.url().describe('Presigned S3 POST URL'),
    fields: zod
        .record(zod.string(), zod.string())
        .describe('Form fields that must be submitted verbatim with the file upload'),
})

export type S3PresignedPostApi = zod.input<typeof S3PresignedPostApi>
export type S3PresignedPostApiOutput = zod.output<typeof S3PresignedPostApi>

export const TaskStagedArtifactPrepareUploadResponseApi = zod.object({
    id: zod.string().describe('Stable identifier for the prepared staged artifact within this task'),
    name: zod.string().describe('Artifact file name'),
    type: zod.string().describe('Artifact classification (plan, context, etc.)'),
    source: zod.string().optional().describe('Source of the artifact, such as agent_output or user_attachment'),
    size: zod.number().describe('Expected upload size in bytes'),
    content_type: zod.string().optional().describe('Optional MIME type'),
    metadata: TaskRunArtifactMetadataApi.optional().describe(
        'Optional structured metadata for special artifact types, such as skill bundles.'
    ),
    storage_path: zod.string().describe('S3 object key reserved for the staged artifact'),
    expires_in: zod.number().describe('Presigned POST expiry in seconds'),
    presigned_post: S3PresignedPostApi.describe('Presigned S3 POST configuration for uploading the file'),
})

export type TaskStagedArtifactPrepareUploadResponseApi = zod.input<typeof TaskStagedArtifactPrepareUploadResponseApi>
export type TaskStagedArtifactPrepareUploadResponseApiOutput = zod.output<
    typeof TaskStagedArtifactPrepareUploadResponseApi
>

export const TaskStagedArtifactsPrepareUploadResponseApi = zod.object({
    artifacts: zod
        .array(TaskStagedArtifactPrepareUploadResponseApi)
        .describe('Prepared staged uploads for the requested artifacts'),
})

export type TaskStagedArtifactsPrepareUploadResponseApi = zod.input<typeof TaskStagedArtifactsPrepareUploadResponseApi>
export type TaskStagedArtifactsPrepareUploadResponseApiOutput = zod.output<
    typeof TaskStagedArtifactsPrepareUploadResponseApi
>

export const PaginatedTaskRunDetailDTOListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(TaskRunDetailDTOApi),
})

export type PaginatedTaskRunDetailDTOListApi = zod.input<typeof PaginatedTaskRunDetailDTOListApi>
export type PaginatedTaskRunDetailDTOListApiOutput = zod.output<typeof PaginatedTaskRunDetailDTOListApi>

export const TaskRunBootstrapCreateRequestEnvironmentEnumApi = zod
    .enum(['local', 'cloud'])
    .describe('\* `local` - local\n\* `cloud` - cloud')

export type TaskRunBootstrapCreateRequestEnvironmentEnumApi = zod.input<
    typeof TaskRunBootstrapCreateRequestEnvironmentEnumApi
>
export type TaskRunBootstrapCreateRequestEnvironmentEnumApiOutput = zod.output<
    typeof TaskRunBootstrapCreateRequestEnvironmentEnumApi
>

export const TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi = zod
    .enum(['default', 'acceptEdits', 'plan', 'bypassPermissions', 'auto', 'read-only', 'full-access'])
    .describe(
        '\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access'
    )

export type TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi = zod.input<
    typeof TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi
>
export type TaskRunBootstrapCreateRequestInitialPermissionModeEnumApiOutput = zod.output<
    typeof TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi
>

export const taskRunBootstrapCreateRequestApiEnvironmentDefault = `local`
export const taskRunBootstrapCreateRequestApiModeDefault = `background`
export const taskRunBootstrapCreateRequestApiBranchMax = 255

export const TaskRunBootstrapCreateRequestApi = zod
    .object({
        imported_mcp_servers: zod
            .array(ImportedMcpServerApi)
            .nullish()
            .describe(
                'Local url-based MCP servers from the creating client (PostHog Desktop) to make available inside the cloud sandbox. Header values are treated as credentials: stored encrypted and never returned by the API.'
            ),
        relayed_mcp_servers: zod
            .array(RelayedMcpServerApi)
            .nullish()
            .describe(
                'Names of desktop-only MCP servers the creating client (PostHog Desktop) relays into the cloud sandbox over the durable event\/command channel. Names only — the server configuration (command, env, URL, headers) never crosses the wire.'
            ),
        environment: TaskRunBootstrapCreateRequestEnvironmentEnumApi.default(
            taskRunBootstrapCreateRequestApiEnvironmentDefault
        ).describe(
            "Execution environment for the new run. Use 'cloud' for remote sandbox runs and 'local' for desktop sessions.\n\n\* `local` - local\n\* `cloud` - cloud"
        ),
        mode: TaskExecutionModeEnumApi.default(taskRunBootstrapCreateRequestApiModeDefault).describe(
            "Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs\n\n\* `interactive` - interactive\n\* `background` - background"
        ),
        branch: zod
            .string()
            .max(taskRunBootstrapCreateRequestApiBranchMax)
            .nullish()
            .describe('Git branch to checkout in the sandbox'),
        sandbox_environment_id: zod
            .uuid()
            .optional()
            .describe('Optional sandbox environment to apply for this cloud run.'),
        custom_image_id: zod
            .uuid()
            .optional()
            .describe(
                "Optional custom base image for this cloud run's sandbox (Modal VM runtime only); takes precedence over the environment's image."
            ),
        pr_authorship_mode: PrAuthorshipModeEnumApi.optional().describe(
            'Whether pull requests for this run should be authored by the user or the bot.\n\n\* `user` - user\n\* `bot` - bot'
        ),
        auto_publish: zod
            .boolean()
            .nullish()
            .describe(
                'When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask.'
            ),
        run_source: RunSourceEnumApi.optional().describe(
            'High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.\n\n\* `manual` - manual\n\* `signal_report` - signal_report'
        ),
        signal_report_id: zod
            .string()
            .optional()
            .describe('Optional signal report identifier when this run was started from Inbox.'),
        runtime_adapter: RuntimeAdapterEnumApi.optional().describe(
            "Agent runtime adapter to launch for this run. Use 'claude' for the Claude runtime or 'codex' for the Codex runtime.\n\n\* `claude` - claude\n\* `codex` - codex"
        ),
        model: zod.string().optional().describe('LLM model identifier to run in the selected runtime.'),
        reasoning_effort: ReasoningEffortEnumApi.optional().describe(
            'Reasoning effort to request for models that expose an effort control.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
        ),
        context_window: ContextWindowEnumApi.optional().describe(
            'Context window size for models that support the 1M window.\n\n\* `200k` - 200k\n\* `1m` - 1m'
        ),
        fast_mode: zod.boolean().nullish().describe('Enable fast mode for models that support it.'),
        github_user_token: zod
            .string()
            .optional()
            .describe('Ephemeral GitHub user token from PostHog Desktop for user-authored cloud pull requests.'),
        initial_permission_mode: TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi.optional().describe(
            "Initial permission mode for the agent session. Claude runtimes accept PostHog permission presets like 'plan'. Codex runtimes accept native Codex modes like 'plan', 'auto', and 'read-only'.\n\n\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto\n\* `read-only` - read-only\n\* `full-access` - full-access"
        ),
        rtk_enabled: zod
            .boolean()
            .nullish()
            .describe(
                'Whether rtk command-output compression is enabled for this run. Omitted or null follows the server-side default (enabled); false opts this run out.'
            ),
    })
    .describe('Request body for creating a task run without starting execution yet.')

export type TaskRunBootstrapCreateRequestApi = zod.input<typeof TaskRunBootstrapCreateRequestApi>
export type TaskRunBootstrapCreateRequestApiOutput = zod.output<typeof TaskRunBootstrapCreateRequestApi>

export const RunStatusEnumApi = zod
    .enum(['not_started', 'queued', 'in_progress', 'completed', 'failed', 'cancelled'])
    .describe(
        '\* `not_started` - not_started\n\* `queued` - queued\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `cancelled` - cancelled'
    )

export type RunStatusEnumApi = zod.input<typeof RunStatusEnumApi>
export type RunStatusEnumApiOutput = zod.output<typeof RunStatusEnumApi>

export const TaskRunUpdateEnvironmentEnumApi = zod.enum(['local']).describe('\* `local` - local')

export type TaskRunUpdateEnvironmentEnumApi = zod.input<typeof TaskRunUpdateEnvironmentEnumApi>
export type TaskRunUpdateEnvironmentEnumApiOutput = zod.output<typeof TaskRunUpdateEnvironmentEnumApi>

export const PatchedTaskRunUpdateApi = zod.object({
    status: RunStatusEnumApi.optional().describe(
        'Current execution status\n\n\* `not_started` - not_started\n\* `queued` - queued\n\* `in_progress` - in_progress\n\* `completed` - completed\n\* `failed` - failed\n\* `cancelled` - cancelled'
    ),
    branch: zod.string().nullish().describe('Git branch name to associate with the task'),
    stage: zod.string().nullish().describe('Current stage of the run (e.g. research, plan, build)'),
    output: zod.unknown().optional().describe('Output from the run'),
    state: zod.unknown().optional().describe('State of the run'),
    state_remove_keys: zod
        .array(zod.string())
        .optional()
        .describe('State keys to remove atomically before applying any state updates.'),
    error_message: zod.string().nullish().describe('Error message if execution failed'),
    environment: TaskRunUpdateEnvironmentEnumApi.optional().describe(
        'Transition a cloud run to local. Use the resume_in_cloud action to move a run into cloud.\n\n\* `local` - local'
    ),
})

export type PatchedTaskRunUpdateApi = zod.input<typeof PatchedTaskRunUpdateApi>
export type PatchedTaskRunUpdateApiOutput = zod.output<typeof PatchedTaskRunUpdateApi>

export const TaskRunAppendLogRequestApi = zod.object({
    entries: zod.array(zod.record(zod.string(), zod.unknown())).describe('Array of log entry dictionaries to append'),
})

export type TaskRunAppendLogRequestApi = zod.input<typeof TaskRunAppendLogRequestApi>
export type TaskRunAppendLogRequestApiOutput = zod.output<typeof TaskRunAppendLogRequestApi>

export const ContentEncodingEnumApi = zod.enum(['utf-8', 'base64']).describe('\* `utf-8` - utf-8\n\* `base64` - base64')

export type ContentEncodingEnumApi = zod.input<typeof ContentEncodingEnumApi>
export type ContentEncodingEnumApiOutput = zod.output<typeof ContentEncodingEnumApi>

export const taskRunArtifactUploadApiNameMax = 255

export const taskRunArtifactUploadApiSourceDefault = ``
export const taskRunArtifactUploadApiSourceMax = 64

export const taskRunArtifactUploadApiContentEncodingDefault = `utf-8`
export const taskRunArtifactUploadApiContentTypeMax = 255

export const TaskRunArtifactUploadApi = zod.object({
    name: zod.string().max(taskRunArtifactUploadApiNameMax).describe('File name to associate with the artifact'),
    type: TaskRunArtifactTypeEnumApi.describe(
        'Classification for the artifact\n\n\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
    ),
    source: zod
        .string()
        .max(taskRunArtifactUploadApiSourceMax)
        .default(taskRunArtifactUploadApiSourceDefault)
        .describe('Optional source label for the artifact, such as agent_output or user_attachment'),
    content: zod.string().describe('Artifact contents encoded according to content_encoding'),
    content_encoding: ContentEncodingEnumApi.default(taskRunArtifactUploadApiContentEncodingDefault).describe(
        'Encoding used for content. Use base64 for binary files and utf-8 for text payloads.\n\n\* `utf-8` - utf-8\n\* `base64` - base64'
    ),
    content_type: zod
        .string()
        .max(taskRunArtifactUploadApiContentTypeMax)
        .optional()
        .describe('Optional MIME type for the artifact'),
    metadata: TaskRunArtifactMetadataApi.optional().describe(
        'Optional structured metadata for special artifact types, such as skill bundles.'
    ),
})

export type TaskRunArtifactUploadApi = zod.input<typeof TaskRunArtifactUploadApi>
export type TaskRunArtifactUploadApiOutput = zod.output<typeof TaskRunArtifactUploadApi>

export const TaskRunArtifactsUploadRequestApi = zod.object({
    artifacts: zod.array(TaskRunArtifactUploadApi).describe('Array of artifacts to upload'),
})

export type TaskRunArtifactsUploadRequestApi = zod.input<typeof TaskRunArtifactsUploadRequestApi>
export type TaskRunArtifactsUploadRequestApiOutput = zod.output<typeof TaskRunArtifactsUploadRequestApi>

export const TaskRunArtifactsUploadResponseApi = zod.object({
    artifacts: zod.array(TaskRunArtifactResponseApi).describe('Updated list of artifacts on the run'),
})

export type TaskRunArtifactsUploadResponseApi = zod.input<typeof TaskRunArtifactsUploadResponseApi>
export type TaskRunArtifactsUploadResponseApiOutput = zod.output<typeof TaskRunArtifactsUploadResponseApi>

export const taskRunArtifactPresignRequestApiStoragePathMax = 500

export const TaskRunArtifactPresignRequestApi = zod.object({
    storage_path: zod
        .string()
        .max(taskRunArtifactPresignRequestApiStoragePathMax)
        .describe('S3 storage path returned in the artifact manifest'),
})

export type TaskRunArtifactPresignRequestApi = zod.input<typeof TaskRunArtifactPresignRequestApi>
export type TaskRunArtifactPresignRequestApiOutput = zod.output<typeof TaskRunArtifactPresignRequestApi>

export const taskRunArtifactFinalizeUploadApiNameMax = 255

export const taskRunArtifactFinalizeUploadApiSourceDefault = ``
export const taskRunArtifactFinalizeUploadApiSourceMax = 64

export const taskRunArtifactFinalizeUploadApiStoragePathMax = 500

export const taskRunArtifactFinalizeUploadApiContentTypeMax = 255

export const TaskRunArtifactFinalizeUploadApi = zod.object({
    id: zod.string().describe('Stable identifier returned by the prepare upload endpoint'),
    name: zod.string().max(taskRunArtifactFinalizeUploadApiNameMax).describe('File name associated with the artifact'),
    type: TaskRunArtifactTypeEnumApi.describe(
        'Classification for the artifact\n\n\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
    ),
    source: zod
        .string()
        .max(taskRunArtifactFinalizeUploadApiSourceMax)
        .default(taskRunArtifactFinalizeUploadApiSourceDefault)
        .describe('Optional source label for the artifact, such as agent_output or user_attachment'),
    storage_path: zod
        .string()
        .max(taskRunArtifactFinalizeUploadApiStoragePathMax)
        .describe('S3 object key returned by the prepare step'),
    content_type: zod
        .string()
        .max(taskRunArtifactFinalizeUploadApiContentTypeMax)
        .optional()
        .describe('Optional MIME type recorded for the artifact'),
    metadata: TaskRunArtifactMetadataApi.optional().describe(
        'Optional structured metadata for special artifact types, such as skill bundles.'
    ),
})

export type TaskRunArtifactFinalizeUploadApi = zod.input<typeof TaskRunArtifactFinalizeUploadApi>
export type TaskRunArtifactFinalizeUploadApiOutput = zod.output<typeof TaskRunArtifactFinalizeUploadApi>

export const TaskRunArtifactsFinalizeUploadRequestApi = zod.object({
    artifacts: zod.array(TaskRunArtifactFinalizeUploadApi).describe('Array of uploaded artifacts to finalize'),
})

export type TaskRunArtifactsFinalizeUploadRequestApi = zod.input<typeof TaskRunArtifactsFinalizeUploadRequestApi>
export type TaskRunArtifactsFinalizeUploadRequestApiOutput = zod.output<typeof TaskRunArtifactsFinalizeUploadRequestApi>

export const TaskRunArtifactsFinalizeUploadResponseApi = zod.object({
    artifacts: zod.array(TaskRunArtifactResponseApi).describe('Updated list of artifacts on the run'),
})

export type TaskRunArtifactsFinalizeUploadResponseApi = zod.input<typeof TaskRunArtifactsFinalizeUploadResponseApi>
export type TaskRunArtifactsFinalizeUploadResponseApiOutput = zod.output<
    typeof TaskRunArtifactsFinalizeUploadResponseApi
>

export const taskRunArtifactPrepareUploadApiNameMax = 255

export const taskRunArtifactPrepareUploadApiSourceDefault = ``
export const taskRunArtifactPrepareUploadApiSourceMax = 64

export const taskRunArtifactPrepareUploadApiSizeMax = 31457280

export const taskRunArtifactPrepareUploadApiContentTypeMax = 255

export const TaskRunArtifactPrepareUploadApi = zod.object({
    name: zod.string().max(taskRunArtifactPrepareUploadApiNameMax).describe('File name to associate with the artifact'),
    type: TaskRunArtifactTypeEnumApi.describe(
        'Classification for the artifact\n\n\* `plan` - plan\n\* `context` - context\n\* `reference` - reference\n\* `output` - output\n\* `artifact` - artifact\n\* `tree_snapshot` - tree_snapshot\n\* `user_attachment` - user_attachment\n\* `skill_bundle` - skill_bundle'
    ),
    source: zod
        .string()
        .max(taskRunArtifactPrepareUploadApiSourceMax)
        .default(taskRunArtifactPrepareUploadApiSourceDefault)
        .describe('Optional source label for the artifact, such as agent_output or user_attachment'),
    size: zod
        .number()
        .min(1)
        .max(taskRunArtifactPrepareUploadApiSizeMax)
        .describe('Expected upload size in bytes (max 31457280 bytes)'),
    content_type: zod
        .string()
        .max(taskRunArtifactPrepareUploadApiContentTypeMax)
        .optional()
        .describe('Optional MIME type for the artifact upload'),
    metadata: TaskRunArtifactMetadataApi.optional().describe(
        'Optional structured metadata for special artifact types, such as skill bundles.'
    ),
})

export type TaskRunArtifactPrepareUploadApi = zod.input<typeof TaskRunArtifactPrepareUploadApi>
export type TaskRunArtifactPrepareUploadApiOutput = zod.output<typeof TaskRunArtifactPrepareUploadApi>

export const TaskRunArtifactsPrepareUploadRequestApi = zod.object({
    artifacts: zod.array(TaskRunArtifactPrepareUploadApi).describe('Array of artifacts to prepare'),
})

export type TaskRunArtifactsPrepareUploadRequestApi = zod.input<typeof TaskRunArtifactsPrepareUploadRequestApi>
export type TaskRunArtifactsPrepareUploadRequestApiOutput = zod.output<typeof TaskRunArtifactsPrepareUploadRequestApi>

export const TaskRunArtifactPrepareUploadResponseApi = zod.object({
    id: zod.string().describe('Stable identifier for the prepared artifact within this run'),
    name: zod.string().describe('Artifact file name'),
    type: zod.string().describe('Artifact classification (plan, context, etc.)'),
    source: zod.string().optional().describe('Source of the artifact, such as agent_output or user_attachment'),
    size: zod.number().describe('Expected upload size in bytes'),
    content_type: zod.string().optional().describe('Optional MIME type'),
    metadata: TaskRunArtifactMetadataApi.optional().describe(
        'Optional structured metadata for special artifact types, such as skill bundles.'
    ),
    storage_path: zod.string().describe('S3 object key reserved for the artifact'),
    expires_in: zod.number().describe('Presigned POST expiry in seconds'),
    presigned_post: S3PresignedPostApi.describe('Presigned S3 POST configuration for uploading the file'),
})

export type TaskRunArtifactPrepareUploadResponseApi = zod.input<typeof TaskRunArtifactPrepareUploadResponseApi>
export type TaskRunArtifactPrepareUploadResponseApiOutput = zod.output<typeof TaskRunArtifactPrepareUploadResponseApi>

export const TaskRunArtifactsPrepareUploadResponseApi = zod.object({
    artifacts: zod
        .array(TaskRunArtifactPrepareUploadResponseApi)
        .describe('Prepared uploads for the requested artifacts'),
})

export type TaskRunArtifactsPrepareUploadResponseApi = zod.input<typeof TaskRunArtifactsPrepareUploadResponseApi>
export type TaskRunArtifactsPrepareUploadResponseApiOutput = zod.output<typeof TaskRunArtifactsPrepareUploadResponseApi>

export const TaskRunArtifactPresignResponseApi = zod.object({
    url: zod.url().describe('Presigned URL for downloading the artifact'),
    expires_in: zod.number().describe('URL expiry in seconds'),
})

export type TaskRunArtifactPresignResponseApi = zod.input<typeof TaskRunArtifactPresignResponseApi>
export type TaskRunArtifactPresignResponseApiOutput = zod.output<typeof TaskRunArtifactPresignResponseApi>

export const taskRunCancelRequestApiReasonMax = 500

export const TaskRunCancelRequestApi = zod.object({
    reason: zod
        .string()
        .max(taskRunCancelRequestApiReasonMax)
        .nullish()
        .describe('Optional reason for the cancellation, recorded on the run and shown to run watchers.'),
})

export type TaskRunCancelRequestApi = zod.input<typeof TaskRunCancelRequestApi>
export type TaskRunCancelRequestApiOutput = zod.output<typeof TaskRunCancelRequestApi>

export const JsonrpcEnumApi = zod.enum(['2.0']).describe('\* `2.0` - 2.0')

export type JsonrpcEnumApi = zod.input<typeof JsonrpcEnumApi>
export type JsonrpcEnumApiOutput = zod.output<typeof JsonrpcEnumApi>

export const TaskRunCommandRequestMethodEnumApi = zod
    .enum([
        'user_message',
        'cancel',
        'close',
        'permission_response',
        'set_config_option',
        'mcp_response',
        'pi/rpc',
        'queue_get',
        'queue_clear',
    ])
    .describe(
        '\* `user_message` - user_message\n\* `cancel` - cancel\n\* `close` - close\n\* `permission_response` - permission_response\n\* `set_config_option` - set_config_option\n\* `mcp_response` - mcp_response\n\* `pi\/rpc` - pi\/rpc\n\* `queue_get` - queue_get\n\* `queue_clear` - queue_clear'
    )

export type TaskRunCommandRequestMethodEnumApi = zod.input<typeof TaskRunCommandRequestMethodEnumApi>
export type TaskRunCommandRequestMethodEnumApiOutput = zod.output<typeof TaskRunCommandRequestMethodEnumApi>

export const TaskRunCommandRequestApi = zod
    .object({
        jsonrpc: JsonrpcEnumApi.describe("JSON-RPC version, must be '2.0'\n\n\* `2.0` - 2.0"),
        method: TaskRunCommandRequestMethodEnumApi.describe(
            'Command method to execute on the agent server\n\n\* `user_message` - user_message\n\* `cancel` - cancel\n\* `close` - close\n\* `permission_response` - permission_response\n\* `set_config_option` - set_config_option\n\* `mcp_response` - mcp_response\n\* `pi\/rpc` - pi\/rpc\n\* `queue_get` - queue_get\n\* `queue_clear` - queue_clear'
        ),
        params: zod.record(zod.string(), zod.unknown()).optional().describe('Parameters for the command'),
        id: zod.unknown().optional().describe('Optional JSON-RPC request ID (string or number)'),
    })
    .describe('JSON-RPC request to send a command to the agent server in the sandbox.')

export type TaskRunCommandRequestApi = zod.input<typeof TaskRunCommandRequestApi>
export type TaskRunCommandRequestApiOutput = zod.output<typeof TaskRunCommandRequestApi>

export const TaskRunCommandResponseApi = zod
    .object({
        jsonrpc: zod.string().describe('JSON-RPC version'),
        id: zod.unknown().optional().describe('Request ID echoed back (string or number)'),
        result: zod.unknown().optional().describe('Command result on success'),
        error: zod.record(zod.string(), zod.unknown()).optional().describe('Error details on failure'),
    })
    .describe('Response from the agent server command endpoint.')

export type TaskRunCommandResponseApi = zod.input<typeof TaskRunCommandResponseApi>
export type TaskRunCommandResponseApiOutput = zod.output<typeof TaskRunCommandResponseApi>

export const ConnectionTokenResponseApi = zod
    .object({
        token: zod.string().describe('JWT token for authenticating with the sandbox'),
    })
    .describe('Response containing a JWT token for direct sandbox connection')

export type ConnectionTokenResponseApi = zod.input<typeof ConnectionTokenResponseApi>
export type ConnectionTokenResponseApiOutput = zod.output<typeof ConnectionTokenResponseApi>

export const taskRunRelayMessageRequestApiTextMax = 10000

export const taskRunRelayMessageRequestApiMessageIdMax = 128

export const taskRunRelayMessageRequestApiTextPartsItemMax = 10000

export const TaskRunRelayMessageRequestApi = zod.object({
    text: zod
        .string()
        .max(taskRunRelayMessageRequestApiTextMax)
        .describe('Joined message body. Used when text_parts is absent.'),
    message_id: zod
        .string()
        .max(taskRunRelayMessageRequestApiMessageIdMax)
        .nullish()
        .describe('Id of the user message this turn answers, when the agent-server echoes it.'),
    text_parts: zod
        .array(zod.string().max(taskRunRelayMessageRequestApiTextPartsItemMax))
        .optional()
        .describe('Ordered assistant text blocks. When present, the last non-empty entry is posted instead of text.'),
})

export type TaskRunRelayMessageRequestApi = zod.input<typeof TaskRunRelayMessageRequestApi>
export type TaskRunRelayMessageRequestApiOutput = zod.output<typeof TaskRunRelayMessageRequestApi>

export const TaskRunRelayMessageResponseApi = zod.object({
    status: zod.string().describe("Relay status: 'accepted' or 'skipped'"),
    relay_id: zod.string().optional().describe('Relay workflow ID when accepted'),
})

export type TaskRunRelayMessageResponseApi = zod.input<typeof TaskRunRelayMessageResponseApi>
export type TaskRunRelayMessageResponseApiOutput = zod.output<typeof TaskRunRelayMessageResponseApi>

export const PatchedTaskRunSetOutputRequestApi = zod.object({
    output: zod
        .unknown()
        .optional()
        .describe("Output data from the run. Validated against the task's json_schema if one is set."),
})

export type PatchedTaskRunSetOutputRequestApi = zod.input<typeof PatchedTaskRunSetOutputRequestApi>
export type PatchedTaskRunSetOutputRequestApiOutput = zod.output<typeof PatchedTaskRunSetOutputRequestApi>

export const taskRunStartRequestApiPendingUserArtifactIdsItemMax = 128

export const TaskRunStartRequestApi = zod.object({
    pending_user_message: zod
        .string()
        .optional()
        .describe('Initial or follow-up user message to include in the run prompt.'),
    pending_user_artifact_ids: zod
        .array(zod.string().max(taskRunStartRequestApiPendingUserArtifactIdsItemMax))
        .optional()
        .describe(
            'Identifiers for run artifacts that should be attached to the next user message delivered to the sandbox.'
        ),
})

export type TaskRunStartRequestApi = zod.input<typeof TaskRunStartRequestApi>
export type TaskRunStartRequestApiOutput = zod.output<typeof TaskRunStartRequestApi>

export const StreamReadTokenResponseApi = zod
    .object({
        token: zod
            .string()
            .describe("Run-scoped JWT the browser presents to the agent-proxy to read this run's live event stream"),
        stream_base_url: zod
            .string()
            .nullable()
            .describe(
                "Base URL of the agent-proxy to read the stream from when routing via the proxy is enabled for this user. Null means read from the Django endpoint directly (same-origin). The client appends the run's stream path and sends the token as a Bearer header when this is set."
            ),
    })
    .describe("Response containing a JWT token (and resolved base URL) for reading a task run's live event stream")

export type StreamReadTokenResponseApi = zod.input<typeof StreamReadTokenResponseApi>
export type StreamReadTokenResponseApiOutput = zod.output<typeof StreamReadTokenResponseApi>

export const TaskSessionResponseApi = zod.object({
    id: zod.uuid().describe('Task session identifier'),
    download_url: zod.url().nullable().describe('Temporary URL for downloading the session'),
    content_sha256: zod.string().nullable().describe('SHA-256 digest of the current session content'),
})

export type TaskSessionResponseApi = zod.input<typeof TaskSessionResponseApi>
export type TaskSessionResponseApiOutput = zod.output<typeof TaskSessionResponseApi>

export const TaskSessionSyncResponseApi = zod.object({
    id: zod.uuid().describe('Task session identifier'),
    content_sha256: zod.string().describe('SHA-256 digest of the uploaded session content'),
})

export type TaskSessionSyncResponseApi = zod.input<typeof TaskSessionSyncResponseApi>
export type TaskSessionSyncResponseApiOutput = zod.output<typeof TaskSessionSyncResponseApi>

export const ArtifactTypeEnumApi = zod
    .enum(['slack_message', 'slack_canvas', 'document', 'spreadsheet', 'dashboard', 'file', 'github_pr'])
    .describe(
        '\* `slack_message` - slack_message\n\* `slack_canvas` - slack_canvas\n\* `document` - document\n\* `spreadsheet` - spreadsheet\n\* `dashboard` - dashboard\n\* `file` - file\n\* `github_pr` - github_pr'
    )

export type ArtifactTypeEnumApi = zod.input<typeof ArtifactTypeEnumApi>
export type ArtifactTypeEnumApiOutput = zod.output<typeof ArtifactTypeEnumApi>

export const AdapterEnumApi = zod
    .enum(['slack_message', 'slack_canvas', 'slack_file', 'document_connector', 'github_pr'])
    .describe(
        '\* `slack_message` - slack_message\n\* `slack_canvas` - slack_canvas\n\* `slack_file` - slack_file\n\* `document_connector` - document_connector\n\* `github_pr` - github_pr'
    )

export type AdapterEnumApi = zod.input<typeof AdapterEnumApi>
export type AdapterEnumApiOutput = zod.output<typeof AdapterEnumApi>

export const TaskArtifactStatusEnumApi = zod
    .enum(['active', 'failed'])
    .describe('\* `active` - active\n\* `failed` - failed')

export type TaskArtifactStatusEnumApi = zod.input<typeof TaskArtifactStatusEnumApi>
export type TaskArtifactStatusEnumApiOutput = zod.output<typeof TaskArtifactStatusEnumApi>

export const TaskRunLivingArtifactResponseApi = zod.object({
    id: zod.string().describe('Stable living artifact id. Use this id when editing the artifact.'),
    task_id: zod.string().describe('Task id this living artifact belongs to.'),
    run_id: zod.string().describe('Task run id that created or currently owns this artifact.'),
    team_id: zod.number().describe('Project id that owns this artifact.'),
    name: zod.string().describe('Human-readable artifact name.'),
    artifact_type: ArtifactTypeEnumApi.describe(
        'Artifact format or delivery surface, such as document, spreadsheet, slack_canvas, file, or slack_message.\n\n\* `slack_message` - slack_message\n\* `slack_canvas` - slack_canvas\n\* `document` - document\n\* `spreadsheet` - spreadsheet\n\* `dashboard` - dashboard\n\* `file` - file\n\* `github_pr` - github_pr'
    ),
    adapter: AdapterEnumApi.describe(
        'Adapter that currently stores or edits the artifact.\n\n\* `slack_message` - slack_message\n\* `slack_canvas` - slack_canvas\n\* `slack_file` - slack_file\n\* `document_connector` - document_connector\n\* `github_pr` - github_pr'
    ),
    status: TaskArtifactStatusEnumApi.describe(
        'Current registry status for the artifact.\n\n\* `active` - active\n\* `failed` - failed'
    ),
    location: zod.unknown().describe('Adapter-specific location, such as S3 key or Slack canvas id.'),
    metadata: zod.unknown().describe('Adapter-specific metadata for external storage and source tracking.'),
    current_version: zod.number().describe('Current version number for the artifact.'),
    versions: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe('Chronological version records for this artifact.'),
    created_at: zod.string().nullish().describe('ISO timestamp when created.'),
    updated_at: zod.string().nullish().describe('ISO timestamp when last updated.'),
})

export type TaskRunLivingArtifactResponseApi = zod.input<typeof TaskRunLivingArtifactResponseApi>
export type TaskRunLivingArtifactResponseApiOutput = zod.output<typeof TaskRunLivingArtifactResponseApi>

export const TaskRunLivingArtifactsResponseApi = zod.object({
    artifacts: zod.array(TaskRunLivingArtifactResponseApi).describe('Living artifacts for this task run.'),
})

export type TaskRunLivingArtifactsResponseApi = zod.input<typeof TaskRunLivingArtifactsResponseApi>
export type TaskRunLivingArtifactsResponseApiOutput = zod.output<typeof TaskRunLivingArtifactsResponseApi>

export const taskRunLivingArtifactCreateRequestApiNameMax = 255

export const taskRunLivingArtifactCreateRequestApiArtifactTypeDefault = `document`
export const taskRunLivingArtifactCreateRequestApiContentMax = 500000

export const taskRunLivingArtifactCreateRequestApiContentTypeMax = 255

export const TaskRunLivingArtifactCreateRequestApi = zod.object({
    name: zod
        .string()
        .max(taskRunLivingArtifactCreateRequestApiNameMax)
        .describe('Human-readable artifact name, used as the title.'),
    artifact_type: ArtifactTypeEnumApi.default(taskRunLivingArtifactCreateRequestApiArtifactTypeDefault).describe(
        'Artifact format or delivery surface to create, such as document, spreadsheet, slack_canvas, or file.\n\n\* `slack_message` - slack_message\n\* `slack_canvas` - slack_canvas\n\* `document` - document\n\* `spreadsheet` - spreadsheet\n\* `dashboard` - dashboard\n\* `file` - file\n\* `github_pr` - github_pr'
    ),
    adapter: AdapterEnumApi.optional().describe(
        'Optional preferred external storage or delivery adapter. Slack adapters deliver into the mapped Slack thread; omitted Slack-run documents use Slack canvas, omitted Slack-run files and spreadsheets use Slack file upload, and document_connector uses a connected external document provider.\n\n\* `slack_message` - slack_message\n\* `slack_canvas` - slack_canvas\n\* `slack_file` - slack_file\n\* `document_connector` - document_connector\n\* `github_pr` - github_pr'
    ),
    content: zod
        .string()
        .max(taskRunLivingArtifactCreateRequestApiContentMax)
        .optional()
        .describe('Markdown or text content for the initial artifact version.'),
    content_base64: zod
        .string()
        .optional()
        .describe(
            'Base64-encoded binary content for Slack file uploads or other external adapters. Prefer source_artifact_id or source_storage_path for large files that were already uploaded as run output artifacts.'
        ),
    content_type: zod
        .string()
        .max(taskRunLivingArtifactCreateRequestApiContentTypeMax)
        .optional()
        .describe(
            'MIME type for content_base64 or source-backed artifacts, such as application\/vnd.openxmlformats-officedocument.spreadsheetml.sheet.'
        ),
    source_artifact_id: zod
        .string()
        .optional()
        .describe(
            'Existing run artifact id to use as the initial content source. Only agent-uploaded output artifacts are accepted; internal run artifacts are rejected.'
        ),
    source_storage_path: zod
        .string()
        .optional()
        .describe(
            'Existing run artifact storage_path to use as the initial content source. Only agent-uploaded output artifacts are accepted; internal run artifacts are rejected.'
        ),
    metadata: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Optional metadata to persist with the living artifact.'),
})

export type TaskRunLivingArtifactCreateRequestApi = zod.input<typeof TaskRunLivingArtifactCreateRequestApi>
export type TaskRunLivingArtifactCreateRequestApiOutput = zod.output<typeof TaskRunLivingArtifactCreateRequestApi>

export const TaskRunLivingArtifactOpenResponseApi = zod.object({
    id: zod.string().describe('Stable living artifact id. Use this id when editing the artifact.'),
    task_id: zod.string().describe('Task id this living artifact belongs to.'),
    run_id: zod.string().describe('Task run id that created or currently owns this artifact.'),
    team_id: zod.number().describe('Project id that owns this artifact.'),
    name: zod.string().describe('Human-readable artifact name.'),
    artifact_type: ArtifactTypeEnumApi.describe(
        'Artifact format or delivery surface, such as document, spreadsheet, slack_canvas, file, or slack_message.\n\n\* `slack_message` - slack_message\n\* `slack_canvas` - slack_canvas\n\* `document` - document\n\* `spreadsheet` - spreadsheet\n\* `dashboard` - dashboard\n\* `file` - file\n\* `github_pr` - github_pr'
    ),
    adapter: AdapterEnumApi.describe(
        'Adapter that currently stores or edits the artifact.\n\n\* `slack_message` - slack_message\n\* `slack_canvas` - slack_canvas\n\* `slack_file` - slack_file\n\* `document_connector` - document_connector\n\* `github_pr` - github_pr'
    ),
    status: TaskArtifactStatusEnumApi.describe(
        'Current registry status for the artifact.\n\n\* `active` - active\n\* `failed` - failed'
    ),
    location: zod.unknown().describe('Adapter-specific location, such as S3 key or Slack canvas id.'),
    metadata: zod.unknown().describe('Adapter-specific metadata for external storage and source tracking.'),
    current_version: zod.number().describe('Current version number for the artifact.'),
    versions: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe('Chronological version records for this artifact.'),
    created_at: zod.string().nullish().describe('ISO timestamp when created.'),
    updated_at: zod.string().nullish().describe('ISO timestamp when last updated.'),
    content: zod.string().nullish().describe('Current artifact content when the adapter can read it directly.'),
})

export type TaskRunLivingArtifactOpenResponseApi = zod.input<typeof TaskRunLivingArtifactOpenResponseApi>
export type TaskRunLivingArtifactOpenResponseApiOutput = zod.output<typeof TaskRunLivingArtifactOpenResponseApi>

export const taskRunLivingArtifactEditRequestApiNameMax = 255

export const taskRunLivingArtifactEditRequestApiContentMax = 500000

export const taskRunLivingArtifactEditRequestApiContentTypeMax = 255

export const TaskRunLivingArtifactEditRequestApi = zod.object({
    name: zod
        .string()
        .max(taskRunLivingArtifactEditRequestApiNameMax)
        .optional()
        .describe('Optional new human-readable artifact name.'),
    content: zod
        .string()
        .max(taskRunLivingArtifactEditRequestApiContentMax)
        .optional()
        .describe('Markdown or text content for the next version.'),
    content_base64: zod
        .string()
        .optional()
        .describe('Base64-encoded binary content for the next version, used by adapters such as slack_file.'),
    content_type: zod
        .string()
        .max(taskRunLivingArtifactEditRequestApiContentTypeMax)
        .optional()
        .describe('MIME type for content_base64 or source-backed edits.'),
    source_artifact_id: zod
        .string()
        .optional()
        .describe(
            'Existing run artifact id to use as the next version content source. Only agent-uploaded output artifacts are accepted; internal run artifacts are rejected.'
        ),
    source_storage_path: zod
        .string()
        .optional()
        .describe(
            'Existing run artifact storage_path to use as the next version content source. Only agent-uploaded output artifacts are accepted; internal run artifacts are rejected.'
        ),
    metadata: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Optional metadata to merge into the artifact registry record.'),
})

export type TaskRunLivingArtifactEditRequestApi = zod.input<typeof TaskRunLivingArtifactEditRequestApi>
export type TaskRunLivingArtifactEditRequestApiOutput = zod.output<typeof TaskRunLivingArtifactEditRequestApi>

export const taskRunLivingArtifactChartRequestApiNameMax = 255

export const TaskRunLivingArtifactChartRequestApi = zod.object({
    name: zod
        .string()
        .max(taskRunLivingArtifactChartRequestApiNameMax)
        .describe('Chart title, also used as the delivered file name.'),
    query: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Insight query JSON to render ad hoc, e.g. {\"kind\": \"InsightVizNode\", \"source\": {\"kind\": \"TrendsQuery\", ...}}. SQL queries (DataVisualizationNode, HogQLQuery) are not supported yet. Provide exactly one of query or insight_id.'
        ),
    insight_id: zod
        .number()
        .optional()
        .describe('Numeric id of a saved insight to render. Provide exactly one of query or insight_id.'),
})

export type TaskRunLivingArtifactChartRequestApi = zod.input<typeof TaskRunLivingArtifactChartRequestApi>
export type TaskRunLivingArtifactChartRequestApiOutput = zod.output<typeof TaskRunLivingArtifactChartRequestApi>

export const TaskRunLivingArtifactChartResponseApi = zod.object({
    artifact: TaskRunLivingArtifactResponseApi.describe('The living artifact registered for delivery.'),
    export_asset_id: zod.number().describe('Id of the rendered PNG export backing the chart.'),
    url: zod.url().nullish().describe('Link to explore this chart interactively in PostHog.'),
})

export type TaskRunLivingArtifactChartResponseApi = zod.input<typeof TaskRunLivingArtifactChartResponseApi>
export type TaskRunLivingArtifactChartResponseApiOutput = zod.output<typeof TaskRunLivingArtifactChartResponseApi>

export const TaskThreadMessageDTOApi = zod
    .object({
        id: zod.uuid(),
        task: zod.uuid(),
        author_kind: zod.string(),
        event: zod.string(),
        payload: zod.record(zod.string(), zod.unknown()),
        content: zod.string(),
        created_at: zod.iso.datetime({ offset: true }),
        author: zod.union([TaskUserBasicInfoApi, zod.null()]).optional(),
        forwarded_to_agent_at: zod.iso.datetime({ offset: true }).nullish(),
        forwarded_by: zod.union([TaskUserBasicInfoApi, zod.null()]).optional(),
    })
    .describe("Response shape for one message in a task's thread.")

export type TaskThreadMessageDTOApi = zod.input<typeof TaskThreadMessageDTOApi>
export type TaskThreadMessageDTOApiOutput = zod.output<typeof TaskThreadMessageDTOApi>

export const PaginatedTaskThreadMessageDTOListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(TaskThreadMessageDTOApi),
})

export type PaginatedTaskThreadMessageDTOListApi = zod.input<typeof PaginatedTaskThreadMessageDTOListApi>
export type PaginatedTaskThreadMessageDTOListApiOutput = zod.output<typeof PaginatedTaskThreadMessageDTOListApi>

export const TaskThreadMessageWriteApi = zod
    .object({
        content: zod.string().describe('Message text.'),
    })
    .describe('Request body for posting a thread message.')

export type TaskThreadMessageWriteApi = zod.input<typeof TaskThreadMessageWriteApi>
export type TaskThreadMessageWriteApiOutput = zod.output<typeof TaskThreadMessageWriteApi>

export const WizardCloudRunDTOApi = zod
    .object({
        task_id: zod.uuid().describe('Id of the onboarding wizard task.'),
        run_id: zod.uuid().describe("Id of the task's latest run, for reconnecting to its progress stream."),
        status: zod.string().describe('Latest run status (e.g. queued, in_progress, completed, failed).'),
        started_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe("When the run was created, for the FAB's elapsed timer."),
    })
    .describe(
        "The team's active onboarding wizard cloud run, used to rehydrate\nthe setup-progress FAB when the run was started server-side (drop flow)."
    )

export type WizardCloudRunDTOApi = zod.input<typeof WizardCloudRunDTOApi>
export type WizardCloudRunDTOApiOutput = zod.output<typeof WizardCloudRunDTOApi>

export const PinnedTaskIdsResponseApi = zod.object({
    task_ids: zod.array(zod.uuid()).describe('Visible task IDs pinned by the requester, newest pin first.'),
})

export type PinnedTaskIdsResponseApi = zod.input<typeof PinnedTaskIdsResponseApi>
export type PinnedTaskIdsResponseApiOutput = zod.output<typeof PinnedTaskIdsResponseApi>

export const TaskRepositoriesResponseApi = zod.object({
    repositories: zod
        .array(zod.string())
        .describe('Distinct repositories in use by non-deleted, non-internal tasks for the current team.'),
})

export type TaskRepositoriesResponseApi = zod.input<typeof TaskRepositoriesResponseApi>
export type TaskRepositoriesResponseApiOutput = zod.output<typeof TaskRepositoriesResponseApi>

export const CapabilityStateStateEnumApi = zod
    .enum(['needs_setup', 'detected', 'waiting_for_data', 'ready', 'not_applicable', 'unknown'])
    .describe(
        '\* `needs_setup` - needs_setup\n\* `detected` - detected\n\* `waiting_for_data` - waiting_for_data\n\* `ready` - ready\n\* `not_applicable` - not_applicable\n\* `unknown` - unknown'
    )

export type CapabilityStateStateEnumApi = zod.input<typeof CapabilityStateStateEnumApi>
export type CapabilityStateStateEnumApiOutput = zod.output<typeof CapabilityStateStateEnumApi>

export const CapabilityStateApi = zod.object({
    state: CapabilityStateStateEnumApi.describe(
        'Current state of the capability\n\n\* `needs_setup` - needs_setup\n\* `detected` - detected\n\* `waiting_for_data` - waiting_for_data\n\* `ready` - ready\n\* `not_applicable` - not_applicable\n\* `unknown` - unknown'
    ),
    estimated: zod.boolean().describe('Whether the state is estimated from static analysis'),
    reason: zod.string().describe('Human-readable explanation'),
    evidence: zod.record(zod.string(), zod.unknown()).optional().describe('Supporting evidence'),
})

export type CapabilityStateApi = zod.input<typeof CapabilityStateApi>
export type CapabilityStateApiOutput = zod.output<typeof CapabilityStateApi>

export const ScanEvidenceApi = zod.object({
    filesScanned: zod.number().describe('Number of files scanned'),
    detectedFilesCount: zod.number().describe('Total candidate files detected'),
    eventNameCount: zod.number().describe('Number of distinct event names found'),
    foundPosthogInit: zod.boolean().describe('Whether posthog.init() was found in scanned files'),
    foundPosthogCapture: zod.boolean().describe('Whether posthog.capture() was found in scanned files'),
    foundErrorSignal: zod.boolean().describe('Whether error tracking signals were found in scanned files'),
})

export type ScanEvidenceApi = zod.input<typeof ScanEvidenceApi>
export type ScanEvidenceApiOutput = zod.output<typeof ScanEvidenceApi>

export const RepositoryReadinessResponseApi = zod.object({
    repository: zod.string().describe('Normalized repository identifier'),
    classification: zod.string().describe('Repository classification'),
    excluded: zod.boolean().describe('Whether the repository is excluded from readiness checks'),
    coreSuggestions: CapabilityStateApi.describe('Tracking capability state'),
    replayInsights: CapabilityStateApi.describe('Computer vision capability state'),
    errorInsights: CapabilityStateApi.describe('Error tracking capability state'),
    overall: zod.string().describe('Overall readiness state'),
    evidenceTaskCount: zod.number().describe('Count of replay-derived evidence tasks'),
    windowDays: zod.number().describe('Lookback window in days'),
    generatedAt: zod.string().describe('ISO timestamp when the response was generated'),
    cacheAgeSeconds: zod.number().describe('Age of cached response in seconds'),
    scan: ScanEvidenceApi.optional().describe('Scan evidence details'),
})

export type RepositoryReadinessResponseApi = zod.input<typeof RepositoryReadinessResponseApi>
export type RepositoryReadinessResponseApiOutput = zod.output<typeof RepositoryReadinessResponseApi>

export const SlackThreadContextThreadApi = zod
    .object({
        url: zod.string().describe('Echoed input URL.'),
        channel: zod.string().describe('Slack channel id parsed from the URL (e.g. C0ACRAMJUAG).'),
        thread_ts: zod.string().describe('Slack thread_ts (e.g. 1779956938.619299).'),
        slack_workspace_id: zod
            .string()
            .nullable()
            .describe('Slack workspace id (e.g. T…). Null when no mapping exists yet.'),
        mentioning_slack_user_id: zod
            .string()
            .nullable()
            .describe('The Slack user who triggered the task. Null when no mapping exists yet.'),
    })
    .describe('Slack-side identifiers and the mapping metadata for a thread → task lookup.')

export type SlackThreadContextThreadApi = zod.input<typeof SlackThreadContextThreadApi>
export type SlackThreadContextThreadApiOutput = zod.output<typeof SlackThreadContextThreadApi>

export const SlackThreadContextTaskApi = zod
    .object({
        id: zod.string().describe('UUID of the Task row.'),
        team_id: zod.number().describe('Team that owns the task.'),
        title: zod.string().describe('Task title (typically the first ~255 chars of the Slack ask).'),
        repository: zod
            .string()
            .nullable()
            .describe('Resolved repository in `org\/repo` form, or null if the run started without a repo.'),
        origin_product: zod.string().describe('`Task.OriginProduct` (`slack` for slack-originated tasks).'),
        created_at: zod.iso.datetime({ offset: true }).describe('When the task was created (server-side timestamp).'),
        url: zod.string().describe('Absolute URL to the task detail page in the PostHog app.'),
    })
    .describe('The PostHog Task linked to the Slack thread.')

export type SlackThreadContextTaskApi = zod.input<typeof SlackThreadContextTaskApi>
export type SlackThreadContextTaskApiOutput = zod.output<typeof SlackThreadContextTaskApi>

export const SlackThreadContextRepoResearchApi = zod
    .object({
        task_id: zod.string().describe('UUID of the internal repo-research Task.'),
        run_id: zod.string().describe('UUID of the internal repo-research TaskRun.'),
        status: zod.string().nullable().describe('Research run status, or null if the run row could not be loaded.'),
        task_processing_workflow_id: zod
            .string()
            .describe(
                'Temporal workflow id for the research sandbox run (`task-processing-<task_id>-<run_id>`, or a caller-prefixed variant).'
            ),
        task_processing_workflow_url: zod
            .string()
            .nullable()
            .describe('Full Temporal Web UI URL for the research workflow; null when `TEMPORAL_UI_HOST` is unset.'),
        sandbox_url: zod
            .string()
            .nullable()
            .describe('Live sandbox tunnel URL for the research run, when one was attached.'),
        task_view_url: zod
            .string()
            .describe('Absolute URL to the research task detail page (carries `?ph_debug=true`).'),
        log_url: zod
            .string()
            .nullable()
            .describe("Presigned S3 URL for the research run's JSONL log transcript (valid ~1 hour)."),
    })
    .describe(
        "The internal sandbox run the discovery agent used to pick this run's repo.\n\nOnly present when the originating mention was ambiguous (multiple candidate\nrepos, no explicit mention) — that's the only path that spins up a research\nsandbox. Null otherwise."
    )

export type SlackThreadContextRepoResearchApi = zod.input<typeof SlackThreadContextRepoResearchApi>
export type SlackThreadContextRepoResearchApiOutput = zod.output<typeof SlackThreadContextRepoResearchApi>

export const SlackThreadContextRunApi = zod
    .object({
        id: zod.string().describe('UUID of the TaskRun row.'),
        status: zod.string().describe('Run status (queued\/in_progress\/completed\/failed\/…).'),
        created_at: zod.iso.datetime({ offset: true }).describe('When the run was created.'),
        completed_at: zod.iso
            .datetime({ offset: true })
            .nullable()
            .describe('When the run reached a terminal state, or null while still running.'),
        sandbox_url: zod.string().nullable().describe('Live sandbox tunnel URL, when one was attached.'),
        pr_url: zod.string().nullable().describe('PR URL produced by the run, when one was opened.'),
        error_message: zod.string().nullable().describe('Error captured on terminal failure, or null on success.'),
        task_processing_workflow_id: zod
            .string()
            .describe(
                'Temporal workflow id for the sandbox\/agent run (`task-processing-<task_id>-<run_id>`, or a caller-prefixed variant).'
            ),
        task_processing_workflow_url: zod
            .string()
            .nullable()
            .describe(
                'Full Temporal Web UI URL for the task-processing workflow; null when `TEMPORAL_UI_HOST` is unset.'
            ),
        mention_workflow_id: zod
            .string()
            .nullable()
            .describe(
                'Temporal workflow id of the Slack mention that dispatched this run (`posthog-code-mention-<workspace>:<event_id_or_channel:ts>`). Null for runs created before this field was persisted.'
            ),
        mention_workflow_url: zod
            .string()
            .nullable()
            .describe('Full Temporal Web UI URL for the mention dispatch workflow; null when unavailable.'),
        task_view_url: zod.string().describe('Absolute URL to the task detail page focused on this run.'),
        log_url: zod
            .string()
            .nullable()
            .describe("Presigned S3 URL for the run's full JSONL log transcript (valid ~1 hour)."),
        repo_research: zod
            .union([SlackThreadContextRepoResearchApi, zod.null()])
            .describe("The discovery-agent sandbox that picked this run's repo, when the mention was ambiguous."),
    })
    .describe('One TaskRun and its associated Temporal workflow handles.')

export type SlackThreadContextRunApi = zod.input<typeof SlackThreadContextRunApi>
export type SlackThreadContextRunApiOutput = zod.output<typeof SlackThreadContextRunApi>

export const SlackThreadContextResponseApi = zod
    .object({
        thread: SlackThreadContextThreadApi.describe('Slack-side identifiers and the mapping metadata.'),
        task: zod
            .union([SlackThreadContextTaskApi, zod.null()])
            .describe('Linked PostHog Task. Null when no mapping was found for the thread.'),
        runs: zod
            .array(SlackThreadContextRunApi)
            .describe('All runs on the task, oldest first. Empty when no mapping was found.'),
    })
    .describe('Top-level response for the slack-thread debug endpoint.')

export type SlackThreadContextResponseApi = zod.input<typeof SlackThreadContextResponseApi>
export type SlackThreadContextResponseApiOutput = zod.output<typeof SlackThreadContextResponseApi>

export const taskSummariesRequestApiIdsMax = 5000

export const TaskSummariesRequestApi = zod.object({
    ids: zod
        .array(zod.uuid())
        .max(taskSummariesRequestApiIdsMax)
        .describe(
            'Task IDs to fetch summaries for (max 5000). Response is paginated; follow the `next` cursor to retrieve all results.'
        ),
})

export type TaskSummariesRequestApi = zod.input<typeof TaskSummariesRequestApi>
export type TaskSummariesRequestApiOutput = zod.output<typeof TaskSummariesRequestApi>

export const TaskRunStatusEnumApi = zod
    .enum(['not_started', 'queued', 'in_progress', 'completed', 'failed', 'cancelled'])
    .describe(
        '\* `not_started` - Not Started\n\* `queued` - Queued\n\* `in_progress` - In Progress\n\* `completed` - Completed\n\* `failed` - Failed\n\* `cancelled` - Cancelled'
    )

export type TaskRunStatusEnumApi = zod.input<typeof TaskRunStatusEnumApi>
export type TaskRunStatusEnumApiOutput = zod.output<typeof TaskRunStatusEnumApi>

export const TaskRunEnvironmentEnumApi = zod.enum(['local', 'cloud']).describe('\* `local` - Local\n\* `cloud` - Cloud')

export type TaskRunEnvironmentEnumApi = zod.input<typeof TaskRunEnvironmentEnumApi>
export type TaskRunEnvironmentEnumApiOutput = zod.output<typeof TaskRunEnvironmentEnumApi>

export const TaskRunSummaryApi = zod.object({
    status: zod.union([TaskRunStatusEnumApi, zod.null()]),
    environment: zod.union([TaskRunEnvironmentEnumApi, zod.null()]),
})

export type TaskRunSummaryApi = zod.input<typeof TaskRunSummaryApi>
export type TaskRunSummaryApiOutput = zod.output<typeof TaskRunSummaryApi>

export const TaskSummaryDTOApi = zod
    .object({
        id: zod.uuid(),
        title: zod.string(),
        repository: zod.string().nullable(),
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
        origin_product: zod.string().optional(),
        latest_run: zod.union([TaskRunSummaryApi, zod.null()]).optional(),
    })
    .describe('Summary response for a task — reads from a frozen ``TaskSummaryDTO``.')

export type TaskSummaryDTOApi = zod.input<typeof TaskSummaryDTOApi>
export type TaskSummaryDTOApiOutput = zod.output<typeof TaskSummaryDTOApi>

export const PaginatedTaskSummaryDTOListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(TaskSummaryDTOApi),
})

export type PaginatedTaskSummaryDTOListApi = zod.input<typeof PaginatedTaskSummaryDTOListApi>
export type PaginatedTaskSummaryDTOListApiOutput = zod.output<typeof PaginatedTaskSummaryDTOListApi>

export const warmTaskRequestApiRepositoryMax = 255

export const warmTaskRequestApiBranchMax = 255

export const WarmTaskRequestApi = zod
    .object({
        repository: zod
            .string()
            .max(warmTaskRequestApiRepositoryMax)
            .describe('Target GitHub repository to clone, in `organization\/repo` format (e.g. `posthog\/posthog`).'),
        github_integration: zod.number().describe("Primary key of the team's GitHub integration to clone with."),
        branch: zod
            .string()
            .max(warmTaskRequestApiBranchMax)
            .nullish()
            .describe(
                "Branch to check out in the warm sandbox. Defaults to the repository's default branch when omitted."
            ),
        runtime_adapter: zod
            .union([RuntimeAdapterEnumApi, zod.null()])
            .optional()
            .describe(
                "Agent runtime adapter to warm the sandbox on ('claude' or 'codex'). The warm Run starts the agent on this runtime so a matching submit reuses it; a submit selecting a different runtime falls through to a cold Run instead of reusing a mismatched warm session.\n\n\* `claude` - claude\n\* `codex` - codex"
            ),
        model: zod
            .string()
            .nullish()
            .describe(
                "LLM model identifier to warm the sandbox on. A submit selecting a different model won't reuse this warm Run."
            ),
        reasoning_effort: zod
            .union([ReasoningEffortEnumApi, zod.null()])
            .optional()
            .describe(
                'Reasoning effort to warm the sandbox on for models that expose an effort control.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max\n\* `ultracode` - ultracode'
            ),
        sandbox_environment_id: zod
            .uuid()
            .nullish()
            .describe('Optional sandbox environment to provision before the task is submitted.'),
        custom_image_id: zod
            .uuid()
            .nullish()
            .describe(
                "Optional custom base image to provision before the task is submitted; takes precedence over the environment's image."
            ),
    })
    .describe(
        "Request body for warming a full idling Run while composing a Code-app cloud task.\n\nCollection-level: no task exists yet at typing time. The warmer births a draft Task and an\ninteractive Run that boots, clones, checks out `branch`, and starts the agent, then idles awaiting\nthe first message. `github_integration` is a plain integration PK (an integer); the view re-scopes\nit to the caller's team before use."
    )

export type WarmTaskRequestApi = zod.input<typeof WarmTaskRequestApi>
export type WarmTaskRequestApiOutput = zod.output<typeof WarmTaskRequestApi>

export const WarmTaskResponseApi = zod
    .object({
        task_id: zod.uuid().describe('Id of the draft Task birthed for the warm Run.'),
        run_id: zod
            .uuid()
            .describe('Id of the idling warm Run. The normal create+run path reuses and activates it on submit.'),
    })
    .describe('Response for a successful warm request — the draft Task + idling warm Run reused on submit.')

export type WarmTaskResponseApi = zod.input<typeof WarmTaskResponseApi>
export type WarmTaskResponseApiOutput = zod.output<typeof WarmTaskResponseApi>
