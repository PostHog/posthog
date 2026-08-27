/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface LegacyDesktopAccessResponseApi {
    /** Whether the user has legacy PostHog Desktop access. */
    has_access: boolean
    /** Whether the independent Loops feature is enabled. */
    has_loops_access: boolean
}

export interface CodeInviteRedeemRequestApi {
    /** @maxLength 50 */
    code: string
}

/**
 * * `startup_plan` - startup_plan
 * * `prepaid_credits` - prepaid_credits
 */
export type DesktopAccessReasonEnumApi = (typeof DesktopAccessReasonEnumApi)[keyof typeof DesktopAccessReasonEnumApi]

export const DesktopAccessReasonEnumApi = {
    StartupPlan: 'startup_plan',
    PrepaidCredits: 'prepaid_credits',
} as const

/**
 * * `burst` - burst
 * * `sustained` - sustained
 */
export type LimitTypeEnumApi = (typeof LimitTypeEnumApi)[keyof typeof LimitTypeEnumApi]

export const LimitTypeEnumApi = {
    Burst: 'burst',
    Sustained: 'sustained',
} as const

export interface TaskRunErrorResponseApi {
    /** Human-readable validation error */
    detail?: string
    /** Human-readable error message */
    error?: string
    /** Machine-readable error type */
    type?: string
    /** Machine-readable error code */
    code?: string
    /** Why PostHog Desktop access was denied, when applicable.
     *
     * * `startup_plan` - startup_plan
     * * `prepaid_credits` - prepaid_credits */
    reason?: DesktopAccessReasonEnumApi
    /** Request field associated with the error */
    attr?: string
    /** Artifact ids that could not be resolved for the run */
    missing_artifact_ids?: string[]
    /** Which usage limit was hit on a rate_limited error: 'burst' (daily) or 'sustained' (monthly)
     *
     * * `burst` - burst
     * * `sustained` - sustained */
    limit_type?: LimitTypeEnumApi
    /** ISO 8601 timestamp when the hit usage limit resets, when known */
    reset_at?: string
    /** Whether the team is on a Pro plan (drives the upgrade-prompt copy) */
    is_pro?: boolean
}

export interface ComputeRateCardApi {
    /** Stable identifier for this rate card. */
    version: string
    /** Time when this rate card became effective. */
    effective_at: string
    /**
     * Time when this rate card stopped applying, or null while it remains current.
     * @nullable
     */
    expires_at: string | null
    /** USD charged per CPU core-second as an exact decimal string. */
    cpu_core_second_usd: string
    /** USD charged per GiB-second of memory as an exact decimal string. */
    memory_gib_second_usd: string
}

export interface SandboxComputePricingApi {
    /** Currently effective sandbox compute rate card, or null before pricing is published. */
    current: ComputeRateCardApi | null
    /** Expired sandbox compute rate cards, newest first. */
    history: ComputeRateCardApi[]
}

export interface DesktopBetaTermsAcceptanceDTOApi {
    /** Whether the organization has accepted the PostHog Desktop beta terms. */
    readonly is_desktop_beta_terms_accepted: boolean
}

export interface DesktopAccessResponseApi {
    /** Whether the selected project can use PostHog Desktop. */
    allowed: boolean
    /** Why Desktop access is blocked, or null when access is allowed.
     *
     * * `startup_plan` - startup_plan
     * * `prepaid_credits` - prepaid_credits */
    reason: DesktopAccessReasonEnumApi | null
}

export interface LoopRepositoryEntryDTOApi {
    github_integration_id: number
    full_name: string
}

export interface LoopBehaviorsDTOApi {
    create_prs?: boolean
    watch_ci?: boolean
    fix_review_comments?: boolean
    max_fix_iterations?: number
}

export interface LoopConnectorsDTOApi {
    mcp_installation_ids?: string[]
    posthog_mcp_scopes?: string
}

export type LoopNotificationChannelDTOApiParams = { [key: string]: unknown }

export interface LoopNotificationChannelDTOApi {
    enabled?: boolean
    events?: string[]
    params?: LoopNotificationChannelDTOApiParams
}

export interface LoopNotificationsDTOApi {
    push: LoopNotificationChannelDTOApi
    email: LoopNotificationChannelDTOApi
    slack: LoopNotificationChannelDTOApi
}

export interface LoopContextOutputsDTOApi {
    post_to_feed?: boolean
    update_context?: boolean
    /** @nullable */
    canvas_id?: string | null
}

export interface LoopContextTargetDTOApi {
    /** What the loop maintains in this context each run. */
    outputs: LoopContextOutputsDTOApi
    channel_id: string
    name: string
}

export type LoopTriggerDTOApiConfig = { [key: string]: unknown }

/**
 * Read response for a single loop trigger.
 */
export interface LoopTriggerDTOApi {
    id: string
    loop_id: string
    type: string
    enabled: boolean
    config: LoopTriggerDTOApiConfig
    /** @nullable */
    schedule_sync_status: string | null
    /** @nullable */
    last_fired_at: string | null
    created_at: string
    updated_at: string
}

export interface LoopSkillBundleDTOApi {
    id: string
    skill_name: string
    skill_source: string
    size: number
    content_sha256: string
    uploaded_at: string
}

/**
 * Detail/create/update response for a loop, including its triggers.
 */
export interface LoopDTOApi {
    id: string
    team_id: number
    /** @nullable */
    created_by_id: number | null
    name: string
    description: string
    visibility: string
    instructions: string
    runtime_adapter: string
    model: string
    /** @nullable */
    reasoning_effort: string | null
    /** Repositories this loop operates on. */
    repositories: LoopRepositoryEntryDTOApi[]
    /** @nullable */
    sandbox_environment_id: string | null
    enabled: boolean
    /** @nullable */
    disabled_reason: string | null
    overlap_policy: string
    /** PR / CI-follow-up behavior configuration. */
    behaviors: LoopBehaviorsDTOApi
    /** MCP connector configuration for this loop's runs. */
    connectors: LoopConnectorsDTOApi
    /** Per-channel notification configuration. */
    notifications: LoopNotificationsDTOApi
    /** Context this loop is attached to, or null when unattached. */
    context_target?: LoopContextTargetDTOApi | null
    internal: boolean
    origin_product: string
    /** @nullable */
    last_run_at: string | null
    /** @nullable */
    last_run_status: string | null
    /** @nullable */
    last_error: string | null
    consecutive_failures: number
    created_at: string
    updated_at: string
    /** Triggers attached to this loop. */
    triggers: LoopTriggerDTOApi[]
    /** Skill bundles attached to this loop, seeded into every fired run. */
    skill_bundles: LoopSkillBundleDTOApi[]
}

export interface PaginatedLoopDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: LoopDTOApi[]
    /** Hard cap on non-deleted loops per project. Creating a loop beyond this returns a 429 with `error: loop_safety_limit`. Authoritative — read this rather than assuming a value. */
    max_loops_per_team?: number
    /** Current number of non-deleted, user-facing loops in this project, counted against `max_loops_per_team`. At or above the cap, creation is blocked. */
    total_loop_count?: number
}

/**
 * * `personal` - personal
 * * `team` - team
 */
export type LoopWriteVisibilityEnumApi = (typeof LoopWriteVisibilityEnumApi)[keyof typeof LoopWriteVisibilityEnumApi]

export const LoopWriteVisibilityEnumApi = {
    Personal: 'personal',
    Team: 'team',
} as const

/**
 * * `claude` - claude
 * * `codex` - codex
 */
export type RuntimeAdapterEnumApi = (typeof RuntimeAdapterEnumApi)[keyof typeof RuntimeAdapterEnumApi]

export const RuntimeAdapterEnumApi = {
    Claude: 'claude',
    Codex: 'codex',
} as const

/**
 * * `low` - low
 * * `medium` - medium
 * * `high` - high
 * * `xhigh` - xhigh
 * * `max` - max
 * * `ultracode` - ultracode
 */
export type ReasoningEffortEnumApi = (typeof ReasoningEffortEnumApi)[keyof typeof ReasoningEffortEnumApi]

export const ReasoningEffortEnumApi = {
    Low: 'low',
    Medium: 'medium',
    High: 'high',
    Xhigh: 'xhigh',
    Max: 'max',
    Ultracode: 'ultracode',
} as const

export interface LoopRepositoryEntryApi {
    /** GitHub integration id this repository is accessed through. */
    github_integration_id: number
    /**
     * Repository in `organization/repo` format, e.g. `posthog/posthog`.
     * @maxLength 255
     */
    full_name: string
}

/**
 * * `skip` - skip
 * * `allow` - allow
 * * `cancel_previous` - cancel_previous
 */
export type OverlapPolicyEnumApi = (typeof OverlapPolicyEnumApi)[keyof typeof OverlapPolicyEnumApi]

export const OverlapPolicyEnumApi = {
    Skip: 'skip',
    Allow: 'allow',
    CancelPrevious: 'cancel_previous',
} as const

export interface LoopBehaviorsApi {
    /** Whether the agent may push branches and open PRs. False makes this a report-only loop. */
    create_prs?: boolean
    /** Whether to watch CI on loop-created PRs and report status. */
    watch_ci?: boolean
    /** Whether to automatically address review comments on loop-created PRs. */
    fix_review_comments?: boolean
    /**
     * Ceiling on automatic CI/review-comment fix iterations, capped at 10.
     * @minimum 0
     * @maximum 10
     */
    max_fix_iterations?: number
}

/**
 * * `read_only` - read_only
 * * `full` - full
 */
export type PosthogMcpScopesEnumApi = (typeof PosthogMcpScopesEnumApi)[keyof typeof PosthogMcpScopesEnumApi]

export const PosthogMcpScopesEnumApi = {
    ReadOnly: 'read_only',
    Full: 'full',
} as const

export interface LoopConnectorsApi {
    /** MCP Store installation ids (Slack, Linear, etc.) available to this loop's runs. */
    mcp_installation_ids?: string[]
    /** Scope of the PostHog MCP access injected into this loop's runs.
     *
     * * `read_only` - read_only
     * * `full` - full */
    posthog_mcp_scopes?: PosthogMcpScopesEnumApi
}

/**
 * * `run_completed` - run_completed
 * * `run_failed` - run_failed
 * * `pr_created` - pr_created
 * * `needs_attention` - needs_attention
 */
export type EventsEnumApi = (typeof EventsEnumApi)[keyof typeof EventsEnumApi]

export const EventsEnumApi = {
    RunCompleted: 'run_completed',
    RunFailed: 'run_failed',
    PrCreated: 'pr_created',
    NeedsAttention: 'needs_attention',
} as const

/**
 * Channel-specific parameters, e.g. Slack's `integration_id` and `channel`.
 */
export type LoopNotificationChannelApiParams = { [key: string]: unknown }

export interface LoopNotificationChannelApi {
    /** Whether this channel is active. */
    enabled?: boolean
    /** Event kinds this channel notifies on. One or more of: run_completed, run_failed, pr_created, needs_attention. */
    events?: EventsEnumApi[]
    /** Channel-specific parameters, e.g. Slack's `integration_id` and `channel`. */
    params?: LoopNotificationChannelApiParams
}

export interface LoopNotificationsApi {
    /** Push notification settings. */
    push?: LoopNotificationChannelApi
    /** Email notification settings. */
    email?: LoopNotificationChannelApi
    /** Slack notification settings. */
    slack?: LoopNotificationChannelApi
}

export interface LoopContextOutputsWriteApi {
    /** Whether each run is filed into the context's feed as a card (sets the run's channel). */
    post_to_feed?: boolean
    /** Whether each run reads and republishes the context's context.md to reflect the latest state. */
    update_context?: boolean
    /**
     * Id of a canvas in this context the loop keeps up to date each run, or null to maintain none.
     * @nullable
     */
    canvas_id?: string | null
}

export interface LoopContextTargetWriteApi {
    /** Id of the channel (context) this loop is attached to. */
    channel_id: string
    /**
     * Display name of the context, shown in the loop's publish prompt.
     * @maxLength 128
     */
    name: string
    /** What the loop maintains in this context each run. */
    outputs?: LoopContextOutputsWriteApi
}

/**
 * * `schedule` - schedule
 * * `github` - github
 * * `api` - api
 */
export type LoopTriggerTypeEnumApi = (typeof LoopTriggerTypeEnumApi)[keyof typeof LoopTriggerTypeEnumApi]

export const LoopTriggerTypeEnumApi = {
    Schedule: 'schedule',
    Github: 'github',
    Api: 'api',
} as const

export interface LoopTriggerWriteApi {
    /** Existing trigger id to update in place. Omit to create a new trigger. */
    id?: string
    /** Trigger type: `schedule` (cron or one-time), `github` (repo webhook events), or `api` (POST to `trigger/`).
     *
     * * `schedule` - schedule
     * * `github` - github
     * * `api` - api */
    type: LoopTriggerTypeEnumApi
    /** Whether this trigger is active. Disabling pauses only this trigger. */
    enabled?: boolean
    /** Trigger configuration, shape validated per `type`: schedule takes `{cron_expression, timezone}` or `{run_at}` for a one-time run; github takes `{github_integration_id, repository, events, filters}` where `events` is one or more of `issues`, `issue_comment`, `pull_request`, `push` (`event.action` shorthand like `issues.opened` is folded into an `actions` filter, one event per trigger) and `filters` takes `{actions, branches, labels, payload}`. Use `actions` for the event action; `payload` is for anything else in the webhook body, as a list of `{path, equals}` conditions where `path` is a dot-path of object keys and `equals` is a string or list of strings, e.g. `[{"path": "requested_team.slug", "equals": "team-security"}]` to run only when that team is asked to review. All filters must match. API triggers take no config. */
    config?: unknown
}

/**
 * Request body for creating or updating a loop. Field required/default semantics match
 * the `Loop` model; partial updates only touch keys present in the payload.
 */
export interface LoopWriteApi {
    /**
     * Display name for the loop.
     * @maxLength 400
     */
    name: string
    /** Free-form description of what this loop does. */
    description?: string
    /** On a team loop, claim ownership as part of this update so you can edit identity-bearing config (instructions, model, triggers, ...) that only the owner may change. Ignored on personal loops and on create. */
    take_ownership?: boolean
    /** `personal` (owner-only) or `team` (visible and fireable by any team member).
     *
     * * `personal` - personal
     * * `team` - team */
    visibility?: LoopWriteVisibilityEnumApi
    /** The prompt delivered to the agent on every run. */
    instructions: string
    /** Runtime adapter: 'claude' or 'codex'.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter: RuntimeAdapterEnumApi
    /** LLM model identifier, validated against `runtime_adapter`'s catalog. Leave blank to let PostHog pick a sensible default at run time. */
    model?: string
    /** Reasoning effort, validated against `runtime_adapter`/`model`'s supported set.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max
     * * `ultracode` - ultracode */
    reasoning_effort?: ReasoningEffortEnumApi | null
    /**
     * Repositories this loop operates on, ordered. Capped at 1 until multi-repo execution ships. May be empty for report-only loops.
     * @maxItems 1
     */
    repositories?: LoopRepositoryEntryApi[]
    /**
     * Sandbox environment carrying encrypted env vars and the network allowlist into every run.
     * @nullable
     */
    sandbox_environment?: string | null
    /** Whether the loop's triggers are active. Pausing disables all triggers. */
    enabled?: boolean
    /** What happens when a trigger fires while a run is already active: 'skip', 'allow', or 'cancel_previous'.
     *
     * * `skip` - skip
     * * `allow` - allow
     * * `cancel_previous` - cancel_previous */
    overlap_policy?: OverlapPolicyEnumApi
    /** PR / CI-follow-up behavior configuration. */
    behaviors?: LoopBehaviorsApi
    /** MCP connector configuration for this loop's runs. */
    connectors?: LoopConnectorsApi
    /** Per-channel notification configuration. */
    notifications?: LoopNotificationsApi
    /** Context (channel) this loop is attached to, or null to detach. Drives feed placement and the context.md / canvas it keeps up to date. */
    context_target?: LoopContextTargetWriteApi | null
    /** Full desired trigger list, id-stable: entries with a matching `id` are updated in place, entries without one are created, and existing triggers absent from this list are deleted. Omit the field entirely to leave triggers untouched. At most 25 triggers per loop. */
    triggers?: LoopTriggerWriteApi[]
}

/**
 * Request body for creating or updating a loop. Field required/default semantics match
 * the `Loop` model; partial updates only touch keys present in the payload.
 */
export interface PatchedLoopWriteApi {
    /**
     * Display name for the loop.
     * @maxLength 400
     */
    name?: string
    /** Free-form description of what this loop does. */
    description?: string
    /** On a team loop, claim ownership as part of this update so you can edit identity-bearing config (instructions, model, triggers, ...) that only the owner may change. Ignored on personal loops and on create. */
    take_ownership?: boolean
    /** `personal` (owner-only) or `team` (visible and fireable by any team member).
     *
     * * `personal` - personal
     * * `team` - team */
    visibility?: LoopWriteVisibilityEnumApi
    /** The prompt delivered to the agent on every run. */
    instructions?: string
    /** Runtime adapter: 'claude' or 'codex'.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter?: RuntimeAdapterEnumApi
    /** LLM model identifier, validated against `runtime_adapter`'s catalog. Leave blank to let PostHog pick a sensible default at run time. */
    model?: string
    /** Reasoning effort, validated against `runtime_adapter`/`model`'s supported set.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max
     * * `ultracode` - ultracode */
    reasoning_effort?: ReasoningEffortEnumApi | null
    /**
     * Repositories this loop operates on, ordered. Capped at 1 until multi-repo execution ships. May be empty for report-only loops.
     * @maxItems 1
     */
    repositories?: LoopRepositoryEntryApi[]
    /**
     * Sandbox environment carrying encrypted env vars and the network allowlist into every run.
     * @nullable
     */
    sandbox_environment?: string | null
    /** Whether the loop's triggers are active. Pausing disables all triggers. */
    enabled?: boolean
    /** What happens when a trigger fires while a run is already active: 'skip', 'allow', or 'cancel_previous'.
     *
     * * `skip` - skip
     * * `allow` - allow
     * * `cancel_previous` - cancel_previous */
    overlap_policy?: OverlapPolicyEnumApi
    /** PR / CI-follow-up behavior configuration. */
    behaviors?: LoopBehaviorsApi
    /** MCP connector configuration for this loop's runs. */
    connectors?: LoopConnectorsApi
    /** Per-channel notification configuration. */
    notifications?: LoopNotificationsApi
    /** Context (channel) this loop is attached to, or null to detach. Drives feed placement and the context.md / canvas it keeps up to date. */
    context_target?: LoopContextTargetWriteApi | null
    /** Full desired trigger list, id-stable: entries with a matching `id` are updated in place, entries without one are created, and existing triggers absent from this list are deleted. Omit the field entirely to leave triggers untouched. At most 25 triggers per loop. */
    triggers?: LoopTriggerWriteApi[]
}

export interface LoopPreviewRequestApi {
    /** Trigger type to simulate. Defaults to a synthetic schedule fire.
     *
     * * `schedule` - schedule
     * * `github` - github
     * * `api` - api */
    trigger_type?: LoopTriggerTypeEnumApi
    /** Sample trigger payload, e.g. a GitHub webhook body or an API trigger body, to render into context. */
    payload?: unknown
}

export interface LoopPreviewDTOApi {
    instructions: string
    trigger_type: string
    trigger_context: string
}

/**
 * * `created` - created
 * * `deduped` - deduped
 * * `overlap_skipped` - overlap_skipped
 * * `rate_capped` - rate_capped
 * * `team_rate_capped` - team_rate_capped
 * * `disabled` - disabled
 * * `gate_blocked` - gate_blocked
 * * `owner_inactive` - owner_inactive
 * * `owner_changed` - owner_changed
 */
export type LoopFireResultReasonEnumApi = (typeof LoopFireResultReasonEnumApi)[keyof typeof LoopFireResultReasonEnumApi]

export const LoopFireResultReasonEnumApi = {
    Created: 'created',
    Deduped: 'deduped',
    OverlapSkipped: 'overlap_skipped',
    RateCapped: 'rate_capped',
    TeamRateCapped: 'team_rate_capped',
    Disabled: 'disabled',
    GateBlocked: 'gate_blocked',
    OwnerInactive: 'owner_inactive',
    OwnerChanged: 'owner_changed',
} as const

/**
 * Response for a manual (`run/`) or external (`trigger/`) fire.
 */
export interface LoopFireResultApi {
    created: boolean
    /** Outcome of the fire attempt.
     *
     * * `created` - created
     * * `deduped` - deduped
     * * `overlap_skipped` - overlap_skipped
     * * `rate_capped` - rate_capped
     * * `team_rate_capped` - team_rate_capped
     * * `disabled` - disabled
     * * `gate_blocked` - gate_blocked
     * * `owner_inactive` - owner_inactive
     * * `owner_changed` - owner_changed */
    reason: LoopFireResultReasonEnumApi
    /**
     * Id of the created task, when `created` is true.
     * @nullable
     */
    task_id: string | null
    /**
     * Id of the created task run, when `created` is true.
     * @nullable
     */
    task_run_id: string | null
}

/**
 * @nullable
 */
export type LoopRunDTOApiOutput = { [key: string]: unknown } | null

/**
 * A single entry in a loop's run history.
 */
export interface LoopRunDTOApi {
    id: string
    task_id: string
    /** @nullable */
    loop_trigger_id: string | null
    status: string
    environment: string
    /** @nullable */
    branch: string | null
    /** @nullable */
    error_message: string | null
    /** @nullable */
    output: LoopRunDTOApiOutput
    created_at: string
    /** @nullable */
    completed_at: string | null
}

export interface LoopRunPageApi {
    /** Run history entries, newest first. */
    results: LoopRunDTOApi[]
    /**
     * Opaque cursor for the next page, or null when there are no more results.
     * @nullable
     */
    next_cursor: string | null
}

/**
 * * `user` - user
 * * `repo` - repo
 * * `marketplace` - marketplace
 * * `codex` - codex
 */
export type SkillSourceEnumApi = (typeof SkillSourceEnumApi)[keyof typeof SkillSourceEnumApi]

export const SkillSourceEnumApi = {
    User: 'user',
    Repo: 'repo',
    Marketplace: 'marketplace',
    Codex: 'codex',
} as const

/**
 * * `zip` - zip
 */
export type BundleFormatEnumApi = (typeof BundleFormatEnumApi)[keyof typeof BundleFormatEnumApi]

export const BundleFormatEnumApi = {
    Zip: 'zip',
} as const

/**
 * One zipped local skill in a skill-bundle replace request.
 */
export interface LoopSkillBundleUploadApi {
    /**
     * File name for the stored bundle, e.g. `my-skill.zip`.
     * @maxLength 255
     */
    file_name: string
    /**
     * Name of the skill inside the bundle.
     * @maxLength 255
     */
    skill_name: string
    /** Local source the bundle was built from, such as user or repo.
     *
     * * `user` - user
     * * `repo` - repo
     * * `marketplace` - marketplace
     * * `codex` - codex */
    skill_source: SkillSourceEnumApi
    /**
     * SHA-256 hex digest of the bundle bytes.
     * @pattern ^[a-f0-9]{64}$
     */
    content_sha256: string
    /** Archive format used for the bundle.
     *
     * * `zip` - zip */
    bundle_format: BundleFormatEnumApi
    /** Base64-encoded bundle bytes. */
    content_base64: string
}

/**
 * Request body for replacing a loop's attached skill bundles wholesale. Send an empty
 * list to detach every skill.
 */
export interface LoopSkillBundlesWriteApi {
    bundles: LoopSkillBundleUploadApi[]
}

/**
 * @nullable
 */
export type TaskUserBasicInfoApiHedgehogConfig = { [key: string]: unknown } | null

/**
 * Response shape for a task creator, mirroring core ``UserBasicSerializer`` output.
 */
export interface TaskUserBasicInfoApi {
    id: number
    uuid: string
    distinct_id: string
    first_name: string
    last_name: string
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    hedgehog_config?: TaskUserBasicInfoApiHedgehogConfig
    /** @nullable */
    role_at_organization?: string | null
}

export type SandboxCustomImageDTOApiSpec = { [key: string]: unknown }

export type SandboxCustomImageDTOApiScanResult = { [key: string]: unknown }

/**
 * Detail response for a custom sandbox base image.
 */
export interface SandboxCustomImageDTOApi {
    id: string
    name: string
    description: string
    repository?: string
    private?: boolean
    status: string
    version: number
    modal_image_name: string
    spec?: SandboxCustomImageDTOApiSpec
    spec_yaml?: string
    scan_result?: SandboxCustomImageDTOApiScanResult
    build_log?: string
    error: string
    /** @nullable */
    builder_task_id?: string | null
    created_by?: TaskUserBasicInfoApi | null
    /** @nullable */
    created_at?: string | null
    /** @nullable */
    updated_at?: string | null
}

export interface PaginatedSandboxCustomImageDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SandboxCustomImageDTOApi[]
}

/**
 * Request body for creating a custom sandbox base image.
 */
export interface SandboxCustomImageWriteApi {
    /**
     * Display name for the custom image.
     * @maxLength 255
     */
    name: string
    /** What should go into the image; seeds the image-builder agent conversation. */
    description?: string
    /**
     * Optional 'org/repo' the builder session clones so it can verify the image brings up that repository's dependencies.
     * @maxLength 255
     * @nullable
     */
    repository?: string | null
    /** If true, only you can see and use this image; otherwise the whole team can. */
    private?: boolean
}

/**
 * Request body for renaming / re-describing a custom sandbox base image.
 */
export interface PatchedSandboxCustomImageUpdateApi {
    /**
     * New display name for the custom image. Omit to leave unchanged.
     * @minLength 1
     * @maxLength 255
     */
    name?: string
    /** New description. Omit to leave unchanged; pass an empty string to clear it. */
    description?: string
}

/**
 * Request body for scanning and building a custom sandbox base image.
 */
export interface SandboxCustomImageBuildApi {
    /**
     * Image spec YAML to build. When omitted, the spec is read from the builder agent's live sandbox.
     * @nullable
     */
    spec_yaml?: string | null
}

/**
 * A sandbox environment, as returned by list, detail, create and update.
 */
export interface SandboxEnvironmentDTOApi {
    id: string
    name: string
    network_access_level: string
    allowed_domains?: string[]
    include_default_domains: boolean
    repositories?: string[]
    /** Whether any environment variables are set on this environment. */
    has_environment_variables?: boolean
    /** Names of the environment variables that are set, sorted. Values are write-only and never returned. */
    environment_variable_keys?: string[]
    private: boolean
    internal: boolean
    effective_domains?: string[]
    created_by?: TaskUserBasicInfoApi | null
    /** @nullable */
    created_at?: string | null
    /** @nullable */
    updated_at?: string | null
    /** @nullable */
    custom_image_id?: string | null
    /** @nullable */
    custom_image_name?: string | null
    /** @nullable */
    custom_image_status?: string | null
}

export interface PaginatedSandboxEnvironmentDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SandboxEnvironmentDTOApi[]
}

/**
 * * `trusted` - Trusted
 * * `full` - Full
 * * `custom` - Custom
 */
export type NetworkAccessLevelEnumApi = (typeof NetworkAccessLevelEnumApi)[keyof typeof NetworkAccessLevelEnumApi]

export const NetworkAccessLevelEnumApi = {
    Trusted: 'trusted',
    Full: 'full',
    Custom: 'custom',
} as const

/**
 * Request body for creating or updating a sandbox environment.
 */
export interface SandboxEnvironmentWriteApi {
    /**
     * Display name for the environment.
     * @maxLength 255
     */
    name: string
    /** Network access policy: trusted (default allowlist), full (unrestricted), or custom.
     *
     * * `trusted` - Trusted
     * * `full` - Full
     * * `custom` - Custom */
    network_access_level?: NetworkAccessLevelEnumApi
    /**
     * Allowed domains for custom network access.
     * @maxItems 100
     * @items.maxLength 255
     */
    allowed_domains?: string[]
    /** Whether to include default trusted domains (GitHub, npm, PyPI). */
    include_default_domains?: boolean
    /**
     * Repositories this environment applies to (format: org/repo).
     * @items.maxLength 255
     */
    repositories?: string[]
    /** Encrypted environment variables (write-only, never returned in responses). */
    environment_variables?: unknown
    /** If true, only the creator can see this environment; otherwise the whole team can. */
    private?: boolean
    /**
     * Custom base image for this environment's sandboxes (Modal VM runtime only); null uses the default base.
     * @nullable
     */
    custom_image_id?: string | null
}

/**
 * Request body for creating or updating a sandbox environment.
 */
export interface PatchedSandboxEnvironmentWriteApi {
    /**
     * Display name for the environment.
     * @maxLength 255
     */
    name?: string
    /** Network access policy: trusted (default allowlist), full (unrestricted), or custom.
     *
     * * `trusted` - Trusted
     * * `full` - Full
     * * `custom` - Custom */
    network_access_level?: NetworkAccessLevelEnumApi
    /**
     * Allowed domains for custom network access.
     * @maxItems 100
     * @items.maxLength 255
     */
    allowed_domains?: string[]
    /** Whether to include default trusted domains (GitHub, npm, PyPI). */
    include_default_domains?: boolean
    /**
     * Repositories this environment applies to (format: org/repo).
     * @items.maxLength 255
     */
    repositories?: string[]
    /** Encrypted environment variables (write-only, never returned in responses). */
    environment_variables?: unknown
    /** If true, only the creator can see this environment; otherwise the whole team can. */
    private?: boolean
    /**
     * Custom base image for this environment's sandboxes (Modal VM runtime only); null uses the default base.
     * @nullable
     */
    custom_image_id?: string | null
}

/**
 * * `awaiting_input` - awaiting_input
 * * `completed` - completed
 * * `mention` - mention
 * * `thread_reply` - thread_reply
 * * `owned_item_comment` - owned_item_comment
 * * `message` - message
 * * `created` - created
 */
export type ActivityKindEnumApi = (typeof ActivityKindEnumApi)[keyof typeof ActivityKindEnumApi]

export const ActivityKindEnumApi = {
    AwaitingInput: 'awaiting_input',
    Completed: 'completed',
    Mention: 'mention',
    ThreadReply: 'thread_reply',
    OwnedItemComment: 'owned_item_comment',
    Message: 'message',
    Created: 'created',
} as const

/**
 * Response shape for one task in the requester's activity feed (one row per task).
 */
export interface TaskActivityDTOApi {
    id: string
    task_id: string
    task_title: string
    /** @nullable */
    channel_id: string | null
    /** @nullable */
    channel_name: string | null
    activity_at: string
    /** What the latest activity on this task was: an agent run waiting on the requester (awaiting_input), a completed run (completed), someone @-mentioning them (mention), a comment-thread reply (thread_reply), a comment on their item (owned_item_comment), a task-thread reply (message), or their creating the task (created).
     *
     * * `awaiting_input` - awaiting_input
     * * `completed` - completed
     * * `mention` - mention
     * * `thread_reply` - thread_reply
     * * `owned_item_comment` - owned_item_comment
     * * `message` - message
     * * `created` - created */
    activity_kind: ActivityKindEnumApi
    /** Content of the thread message or resource comment tied to the latest activity. */
    snippet: string
    /** Author of the thread message tied to the latest activity, when one applies. */
    latest_author?: TaskUserBasicInfoApi | null
    /** @nullable */
    latest_message_id?: string | null
    /** @nullable */
    latest_comment_id?: string | null
    /** @nullable */
    latest_comment_scope?: string | null
    /** @nullable */
    latest_comment_item_id?: string | null
    /** Whether the requester has yet to see this activity. Activity they caused themselves is never unread. */
    is_unread: boolean
}

/**
 * A page of the requester's activity feed, plus the unread total across the whole feed.
 */
export interface TaskActivityPageDTOApi {
    /** Tasks with activity, most recent first. */
    results: TaskActivityDTOApi[]
    /** Unread tasks across the requester's whole feed, not just this page. Backs the sidebar badge. */
    unread_count: number
    /**
     * Activity timestamp to pass as before for the next page, or null on the final page.
     * @nullable
     */
    next_before?: string | null
    /**
     * Activity ID to pass as before_id for the next page, or null on the final page.
     * @nullable
     */
    next_before_id?: string | null
}

export interface TaskActivityReadMarkerApi {
    /** Task whose displayed activity should be marked read. */
    task_id: string
    /**
     * Comment activity row to mark read. Omit for collapsed task activity.
     * @nullable
     */
    activity_id?: string | null
    /** Mark activity at or before this timestamp read without clearing newer activity. */
    seen_before: string
}

/**
 * Request body for clearing the unread flag on specific tasks.
 */
export interface TaskActivityMarkReadApi {
    /**
     * Displayed task activities to mark read if they have not changed.
     * @maxItems 500
     */
    activities: TaskActivityReadMarkerApi[]
}

export interface TaskActivityMarkReadResponseApi {
    /** How many feed rows changed from unread to read. */
    marked_read: number
    /** The requester's remaining unread total after the update. */
    unread_count: number
}

/**
 * * `personal` - Personal
 * * `general` - General
 */
export type SystemRoleEnumApi = (typeof SystemRoleEnumApi)[keyof typeof SystemRoleEnumApi]

export const SystemRoleEnumApi = {
    Personal: 'personal',
    General: 'general',
} as const

/**
 * Response shape for a task channel, read from a frozen ``ChannelDTO``.
 */
export interface ChannelDTOApi {
    id: string
    name: string
    channel_type: string
    /** @nullable */
    github_integration: number | null
    repositories: string[]
    created_at: string
    created_by?: TaskUserBasicInfoApi | null
    starred?: boolean
    /** Identifies this channel as one of the two system-provisioned spaces ('personal' for the user's own #me space, 'general' for the team's shared #general space). Null for an ordinary channel.
     *
     * * `personal` - Personal
     * * `general` - General */
    readonly system_role: SystemRoleEnumApi | null
}

export interface PaginatedChannelDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ChannelDTOApi[]
}

/**
 * Request body for creating (resolve-or-create) or renaming a public channel.
 */
export interface ChannelWriteApi {
    /**
     * Channel name, rendered as #<name>. Normalized to lowercase-dashed.
     * @maxLength 128
     */
    name: string
    /** Star the channel for the requester when this call creates it. Ignored when the channel already exists, which leaves existing stars untouched. */
    star?: boolean
}

export type ChannelFeedMessageDTOApiPayload = { [key: string]: unknown }

/**
 * Response shape for one system announcement in a channel's feed.
 */
export interface ChannelFeedMessageDTOApi {
    id: string
    channel: string
    author?: TaskUserBasicInfoApi | null
    author_kind: string
    event: string
    payload: ChannelFeedMessageDTOApiPayload
    content: string
    created_at: string
}

export interface PaginatedChannelFeedMessageDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ChannelFeedMessageDTOApi[]
}

/**
 * * `context_created` - context_created
 * * `context_md_building` - context_md_building
 */
export type EventEnumApi = (typeof EventEnumApi)[keyof typeof EventEnumApi]

export const EventEnumApi = {
    ContextCreated: 'context_created',
    ContextMdBuilding: 'context_md_building',
} as const

/**
 * Request body for posting a system announcement into a channel's feed.
 */
export interface ChannelFeedMessageWriteApi {
    /** Lifecycle event key.
     *
     * * `context_created` - context_created
     * * `context_md_building` - context_md_building */
    event: EventEnumApi
    /** Structured event data, e.g. {"context_name": "mobile"}. At most 8 KB of JSON. */
    payload?: unknown
    /** Optional explicit timestamp (within 10 minutes of now), so a client can order a burst of announcements. */
    created_at?: string
}

export interface PatchedChannelUpdateApi {
    /**
     * Channel name, rendered as #<name>. Normalized to lowercase-dashed.
     * @maxLength 128
     */
    name?: string
    /**
     * Team GitHub integration used for repositories linked to this channel.
     * @nullable
     */
    github_integration?: number | null
    /**
     * GitHub repositories inherited by new tasks in this channel.
     * @maxItems 10
     * @items.maxLength 255
     */
    repositories?: string[]
}

export interface ChannelDeleteConflictApi {
    /** Why the space cannot be deleted. */
    detail: string
}

/**
 * The task currently generating this channel's CONTEXT.md, or null.
 */
export interface ChannelContextGenerationApi {
    /** @nullable */
    task_id: string | null
}

/**
 * Response shape for a channel's CONTEXT.md instructions version.
 */
export interface ChannelInstructionsDTOApi {
    channel: string
    content: string
    version: number
    /** @nullable */
    created_at?: string | null
    created_by?: TaskUserBasicInfoApi | null
}

/**
 * Request body for publishing a new instructions version.
 */
export interface ChannelInstructionsWriteApi {
    /**
     * The complete markdown instructions (CONTEXT.md) for the channel.
     * @maxLength 100000
     */
    content: string
    /**
     * Optimistic-concurrency guard: the version the edit is based on (0 for a channel with no instructions yet). A stale base is rejected with 409; omit to publish unguarded.
     * @minimum 0
     * @nullable
     */
    base_version?: number | null
}

/**
 * Request body for publishing a new instructions version.
 */
export interface PatchedChannelInstructionsWriteApi {
    /**
     * The complete markdown instructions (CONTEXT.md) for the channel.
     * @maxLength 100000
     */
    content?: string
    /**
     * Optimistic-concurrency guard: the version the edit is based on (0 for a channel with no instructions yet). A stale base is rejected with 409; omit to publish unguarded.
     * @minimum 0
     * @nullable
     */
    base_version?: number | null
}

export interface PaginatedChannelInstructionsDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ChannelInstructionsDTOApi[]
}

/**
 * Request body for starring/unstarring a channel for the requesting user.
 */
export interface ChannelStarWriteApi {
    starred: boolean
}

/**
 * The first-run session that was started for the requester.
 */
export interface OnboardingSessionApi {
    /** The agent session opened in the team's #general space. */
    task_id: string
}

export interface OnboardingSessionTestApi {
    /**
     * Company domain to research. Blank simulates a personal email address.
     * @maxLength 253
     */
    company_domain?: string
    /** Whether the user is joining an organization that already has shared context. */
    joining_existing_organization?: boolean
    /** Whether the project has ingested events. */
    has_events?: boolean
    /**
     * Number of findings waiting in #general.
     * @minimum 0
     * @maximum 10000
     */
    signal_reports_waiting?: number
    /**
     * Display names of other Desktop users in the organization.
     * @maxItems 25
     * @items.maxLength 100
     */
    other_members?: string[]
    /**
     * Signal sources that were already enabled.
     * @maxItems 25
     * @items.maxLength 100
     */
    sources_enabled?: string[]
    /**
     * Signal sources the onboarding flow is watching.
     * @maxItems 25
     * @items.maxLength 100
     */
    sources_watching?: string[]
    /** Whether onboarding enabled any signal sources. */
    sources_newly_enabled?: boolean
}

/**
 * The first-run session that was started for the requester.
 */
export interface OnboardingSessionTestResponseApi {
    /** The agent session opened in the team's #general space. */
    task_id: string
    /** The requester's personal space containing the session. */
    channel_id: string
}

/**
 * The requester's default channels, plus whether this call is what created them.
 */
export interface ProvisionedChannelsApi {
    /** The full channel list after provisioning, same shape as the list endpoint. */
    channels: ChannelDTOApi[]
    /** Whether this call created the requester's personal #me channel. */
    personal_created: boolean
    /** Whether this call created the team's shared #general channel. True only for the first user to provision it, so clients can branch first-user setup on it. */
    general_created: boolean
}

export interface TeachingCanvasApi {
    /** The teaching canvas that was resolved or created. */
    canvas_id: string
    /** The requester's personal space containing the canvas. */
    channel_id: string
}

/**
 * Response shape for one @-mention of the requester in a task's thread.
 */
export interface TaskMentionDTOApi {
    id: string
    message_id: string
    task_id: string
    task_title: string
    /** @nullable */
    channel_id: string | null
    /** @nullable */
    channel_name: string | null
    author?: TaskUserBasicInfoApi | null
    content: string
    created_at: string
}

export interface PaginatedTaskMentionDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskMentionDTOApi[]
}

/**
 * * `acp` - ACP
 * * `pi` - Pi
 */
export type RuntimeEnumApi = (typeof RuntimeEnumApi)[keyof typeof RuntimeEnumApi]

export const RuntimeEnumApi = {
    Acp: 'acp',
    Pi: 'pi',
} as const

/**
 * * `anthropic` - anthropic
 * * `openai` - openai
 */
export type TaskRunDetailDTOProviderEnumApi =
    (typeof TaskRunDetailDTOProviderEnumApi)[keyof typeof TaskRunDetailDTOProviderEnumApi]

export const TaskRunDetailDTOProviderEnumApi = {
    Anthropic: 'anthropic',
    Openai: 'openai',
} as const

/**
 * * `off` - off
 * * `minimal` - minimal
 * * `low` - low
 * * `medium` - medium
 * * `high` - high
 * * `xhigh` - xhigh
 * * `max` - max
 * * `ultracode` - ultracode
 */
export type TaskRunReasoningEffortEnumApi =
    (typeof TaskRunReasoningEffortEnumApi)[keyof typeof TaskRunReasoningEffortEnumApi]

export const TaskRunReasoningEffortEnumApi = {
    Off: 'off',
    Minimal: 'minimal',
    Low: 'low',
    Medium: 'medium',
    High: 'high',
    Xhigh: 'xhigh',
    Max: 'max',
    Ultracode: 'ultracode',
} as const

export interface TaskRunSkillBundleMetadataApi {
    /**
     * Name of the local skill included in a skill_bundle artifact.
     * @maxLength 255
     */
    skill_name: string
    /** Local source for the uploaded skill bundle, such as user or repo.
     *
     * * `user` - user
     * * `repo` - repo
     * * `marketplace` - marketplace
     * * `codex` - codex */
    skill_source: SkillSourceEnumApi
    /**
     * SHA-256 hex digest of the uploaded skill bundle bytes.
     * @pattern ^[a-f0-9]{64}$
     */
    content_sha256: string
    /** Archive format used for the local skill bundle.
     *
     * * `zip` - zip */
    bundle_format: BundleFormatEnumApi
    /**
     * Version of the local skill bundle metadata schema.
     * @minimum 1
     */
    schema_version: number
}

/**
 * * `posthog_object` - posthog_object
 */
export type ReferenceTypeEnumApi = (typeof ReferenceTypeEnumApi)[keyof typeof ReferenceTypeEnumApi]

export const ReferenceTypeEnumApi = {
    PosthogObject: 'posthog_object',
} as const

/**
 * * `insight` - insight
 * * `hogql` - hogql
 * * `dashboard` - dashboard
 * * `error` - error
 * * `replay` - replay
 * * `flag` - flag
 * * `experiment` - experiment
 * * `survey` - survey
 * * `ticket` - ticket
 * * `trace` - trace
 * * `eval` - eval
 * * `event` - event
 * * `cohort` - cohort
 * * `action` - action
 * * `person` - person
 */
export type ObjectKindEnumApi = (typeof ObjectKindEnumApi)[keyof typeof ObjectKindEnumApi]

export const ObjectKindEnumApi = {
    Insight: 'insight',
    Hogql: 'hogql',
    Dashboard: 'dashboard',
    Error: 'error',
    Replay: 'replay',
    Flag: 'flag',
    Experiment: 'experiment',
    Survey: 'survey',
    Ticket: 'ticket',
    Trace: 'trace',
    Eval: 'eval',
    Event: 'event',
    Cohort: 'cohort',
    Action: 'action',
    Person: 'person',
} as const

export interface TaskRunPostHogReferenceMetadataApi {
    /** Reference metadata type. posthog_object identifies a live PostHog object.
     *
     * * `posthog_object` - posthog_object */
    reference_type: ReferenceTypeEnumApi
    /** PostHog object kind used to resolve the reference.
     *
     * * `insight` - insight
     * * `hogql` - hogql
     * * `dashboard` - dashboard
     * * `error` - error
     * * `replay` - replay
     * * `flag` - flag
     * * `experiment` - experiment
     * * `survey` - survey
     * * `ticket` - ticket
     * * `trace` - trace
     * * `eval` - eval
     * * `event` - event
     * * `cohort` - cohort
     * * `action` - action
     * * `person` - person */
    object_kind: ObjectKindEnumApi
    /**
     * Exact PostHog object identifier, flag key, event name, or SQL query.
     * @maxLength 16384
     */
    object_id: string
    /**
     * Completed assistant message identifiers that referenced the object.
     * @maxItems 100
     * @items.maxLength 255
     */
    source_message_ids: string[]
    /**
     * Number of distinct completed assistant messages that referenced the object.
     * @minimum 1
     */
    occurrence_count: number
}

export type TaskRunArtifactMetadataApi = TaskRunSkillBundleMetadataApi | TaskRunPostHogReferenceMetadataApi

/**
 * * `agent` - agent
 * * `user` - user
 */
export type UploadedByEnumApi = (typeof UploadedByEnumApi)[keyof typeof UploadedByEnumApi]

export const UploadedByEnumApi = {
    Agent: 'agent',
    User: 'user',
} as const

export interface TaskRunArtifactResponseApi {
    /** Stable identifier for the artifact within this run */
    id?: string
    /** Artifact file name */
    name: string
    /** Artifact classification (plan, context, etc.) */
    type: string
    /** Source of the artifact, such as agent_output or user_attachment */
    source?: string
    /** Artifact size in bytes */
    size?: number
    /** Optional MIME type */
    content_type?: string
    /** Structured metadata for a skill bundle or a PostHog object reference. */
    metadata?: TaskRunArtifactMetadataApi
    /** S3 object key for file artifacts. Reference artifacts do not have one. */
    storage_path?: string
    /** Timestamp when the artifact was uploaded or registered */
    uploaded_at: string
    /** Whether the artifact version was uploaded by the task agent or an interactive user.
     *
     * * `agent` - agent
     * * `user` - user */
    uploaded_by?: UploadedByEnumApi
    /** User id for an interactive user upload. Absent for agent uploads and legacy entries. */
    uploaded_by_user_id?: number
    /** Timestamp when a user dismissed the artifact. Absent while the artifact is shown. */
    dismissed_at?: string
    /** Stable download URL for the artifact. Populated on the finalize-upload response so the caller can link to the file; it redirects to a fresh presigned URL on each request and is not persisted on the manifest. */
    url?: string
}

/**
 * @nullable
 */
export type TaskRunDetailDTOApiOutput = { [key: string]: unknown } | null

export type TaskRunDetailDTOApiState = { [key: string]: unknown }

/**
 * Detail response for a task run.
 *
 * Reads from a frozen ``TaskRunDetailDTO`` produced by the facade mapper (which computes the
 * presigned ``log_url`` and parses ``runtime_adapter`` / ``provider`` / ``model`` /
 * ``reasoning_effort`` off the run state). ``task`` is the parent task id. Reused as the nested
 * ``latest_run`` shape by the task detail response.
 */
export interface TaskRunDetailDTOApi {
    id: string
    /** Parent task id this run belongs to. */
    task: string
    /** @nullable */
    stage: string | null
    /** @nullable */
    branch: string | null
    status: string
    environment: string
    /** Configured runtime adapter for this run, such as 'claude' or 'codex'.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter?: RuntimeAdapterEnumApi | null
    /** Configured LLM provider for this run, such as 'anthropic' or 'openai'.
     *
     * * `anthropic` - anthropic
     * * `openai` - openai */
    provider?: TaskRunDetailDTOProviderEnumApi | null
    /**
     * Configured LLM model identifier for this run.
     * @nullable
     */
    model?: string | null
    /** Configured reasoning effort for this run when the selected model supports it.
     *
     * * `off` - off
     * * `minimal` - minimal
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max
     * * `ultracode` - ultracode */
    reasoning_effort?: TaskRunReasoningEffortEnumApi | null
    /**
     * Presigned S3 URL for log access (valid for 1 hour).
     * @nullable
     */
    log_url?: string | null
    /** @nullable */
    error_message: string | null
    /** @nullable */
    output: TaskRunDetailDTOApiOutput
    state: TaskRunDetailDTOApiState
    readonly artifacts: readonly TaskRunArtifactResponseApi[]
    /** @nullable */
    created_at?: string | null
    /** @nullable */
    updated_at?: string | null
    /** @nullable */
    completed_at?: string | null
}

export interface SlackThreadReferenceDTOApi {
    url: string
    channel: string
    /** @nullable */
    created_at?: string | null
}

/**
 * @nullable
 */
export type TaskDetailDTOApiJsonSchema = { [key: string]: unknown } | null

/**
 * Detail response for a task.
 *
 * Reads from a frozen ``TaskDetailDTO`` produced by the facade. ``github_integration`` /
 * ``github_user_integration`` are integration ids, ``signal_report`` is the report id, and
 * ``latest_run`` nests the run-detail shape. ``created_by`` mirrors core ``UserBasicSerializer``.
 */
export interface TaskDetailDTOApi {
    id: string
    /** @nullable */
    task_number: number | null
    slug: string
    title: string
    title_manually_set: boolean
    description: string
    origin_product: string
    /** Agent protocol and harness used for this task's runs.
     *
     * * `acp` - ACP
     * * `pi` - Pi */
    runtime: RuntimeEnumApi
    /** @nullable */
    repository: string | null
    repositories: string[]
    /** @nullable */
    github_integration: number | null
    /** @nullable */
    github_user_integration: string | null
    /** @nullable */
    signal_report: string | null
    /** @nullable */
    json_schema: TaskDetailDTOApiJsonSchema
    internal: boolean
    archived: boolean
    /** @nullable */
    archived_at: string | null
    /** Latest run details for this task */
    latest_run?: TaskRunDetailDTOApi | null
    /** @nullable */
    created_at?: string | null
    /** @nullable */
    updated_at?: string | null
    /** @nullable */
    last_activity_at?: string | null
    created_by?: TaskUserBasicInfoApi | null
    /** @nullable */
    ci_prompt: string | null
    /** @nullable */
    channel?: string | null
    readonly slack_thread_references: readonly SlackThreadReferenceDTOApi[]
}

export interface PaginatedTaskDetailDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskDetailDTOApi[]
}

/**
 * * `onboarding` - Onboarding
 * * `error_tracking` - Error Tracking
 * * `eval_clusters` - Eval Clusters
 * * `user_created` - User Created
 * * `slack` - Slack
 * * `support_queue` - Support Queue
 * * `session_summaries` - Session Summaries
 * * `posthog_ai` - PostHog AI
 * * `experiments` - Experiments
 * * `signal_report` - Signal Report
 * * `signals_scout` - Signals Scout
 * * `support_reply` - Support Reply
 * * `hogdesk` - HogDesk
 * * `review_hog` - ReviewHog
 * * `image_builder` - Image Builder
 * * `loop` - Loop
 * * `mcp_analytics` - MCP Analytics
 * * `signals_chat` - Signals Chat
 * * `task_analysis` - Task Analysis
 * * `workflow` - Workflow
 */
export type OriginProductEnumApi = (typeof OriginProductEnumApi)[keyof typeof OriginProductEnumApi]

export const OriginProductEnumApi = {
    Onboarding: 'onboarding',
    ErrorTracking: 'error_tracking',
    EvalClusters: 'eval_clusters',
    UserCreated: 'user_created',
    Slack: 'slack',
    SupportQueue: 'support_queue',
    SessionSummaries: 'session_summaries',
    PosthogAi: 'posthog_ai',
    Experiments: 'experiments',
    SignalReport: 'signal_report',
    SignalsScout: 'signals_scout',
    SupportReply: 'support_reply',
    Hogdesk: 'hogdesk',
    ReviewHog: 'review_hog',
    ImageBuilder: 'image_builder',
    Loop: 'loop',
    McpAnalytics: 'mcp_analytics',
    SignalsChat: 'signals_chat',
    TaskAnalysis: 'task_analysis',
    Workflow: 'workflow',
} as const

/**
 * * `default` - default
 * * `acceptEdits` - acceptEdits
 * * `plan` - plan
 * * `bypassPermissions` - bypassPermissions
 * * `auto` - auto
 * * `read-only` - read-only
 * * `full-access` - full-access
 */
export type TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi =
    (typeof TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi)[keyof typeof TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi]

export const TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi = {
    Default: 'default',
    AcceptEdits: 'acceptEdits',
    Plan: 'plan',
    BypassPermissions: 'bypassPermissions',
    Auto: 'auto',
    ReadOnly: 'read-only',
    FullAccess: 'full-access',
} as const

/**
 * Request body for creating or updating a task.
 *
 * Field required/default semantics match the ``Task`` model. The view passes
 * ``validated_data`` (integration/report PK fields already resolved to instances) to the
 * facade ``create_task`` / ``update_task`` functions.
 */
export interface TaskCreateApi {
    /**
     * Short human-readable title. Auto-generated from `description` when omitted.
     * @maxLength 255
     */
    title?: string
    /** Whether the title was set by a human (vs auto-generated from the description). */
    title_manually_set?: boolean
    /** Free-form description of the work to be done. Used as the prompt passed to the agent. */
    description?: string
    /** PostHog product or surface that created this task (e.g. error_tracking, slack, user_created). Origins reserved for server-created agents cannot be set through this API.
     *
     * * `onboarding` - Onboarding
     * * `error_tracking` - Error Tracking
     * * `eval_clusters` - Eval Clusters
     * * `user_created` - User Created
     * * `slack` - Slack
     * * `support_queue` - Support Queue
     * * `session_summaries` - Session Summaries
     * * `posthog_ai` - PostHog AI
     * * `experiments` - Experiments
     * * `signal_report` - Signal Report
     * * `signals_scout` - Signals Scout
     * * `support_reply` - Support Reply
     * * `hogdesk` - HogDesk
     * * `review_hog` - ReviewHog
     * * `image_builder` - Image Builder
     * * `loop` - Loop
     * * `mcp_analytics` - MCP Analytics
     * * `signals_chat` - Signals Chat
     * * `task_analysis` - Task Analysis
     * * `workflow` - Workflow */
    origin_product?: OriginProductEnumApi
    /**
     * Target GitHub repository in `organization/repo` format (e.g. `posthog/posthog-js`).
     * @maxLength 255
     * @nullable
     */
    repository?: string | null
    /**
     * GitHub repositories available to this task, each in `organization/repo` format.
     * @maxItems 10
     * @items.maxLength 255
     */
    repositories?: string[]
    /**
     * GitHub integration for this task.
     * @nullable
     */
    github_integration?: number | null
    /**
     * User-scoped GitHub integration to use for user-authored cloud runs.
     * @nullable
     */
    github_user_integration?: string | null
    /**
     * Signal report this task implements, when created from a report.
     * @nullable
     */
    signal_report?: string | null
    /**
     * How the created task relates to the signal report (e.g. 'implementation', 'discussion'). Recorded as a signals task_run work-log entry; 'implementation' also opens the auto-start spend gate. Any routing-safe identifier (lowercase letters, numbers, '_', '-') is accepted except labels reserved for server-created tasks ('research', 'repo_selection', 'scout'). Non-implementation labels count toward the report's discussion task limit.
     * @maxLength 200
     */
    signal_report_task_relationship?: string
    /** JSON schema used to validate the output of the task. */
    json_schema?: unknown
    /** If true, the task is hidden from default list responses. */
    archived?: boolean
    /**
     * Custom prompt for CI fixes. If blank, a default prompt will be used.
     * @nullable
     */
    ci_prompt?: string | null
    /**
     * Branch the user has selected for this cloud task. Write-only and not persisted on the task itself: used only to reuse a matching pre-warmed sandbox Run on creation (the branch is otherwise carried on the run). Omit to match a warm Run on the default branch.
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** Selected runtime adapter ('claude' or 'codex'). Write-only and not persisted on the task: used only to reuse a pre-warmed Run started on the same runtime. A value differing from the warm Run's runtime skips reuse so the task isn't silently run on the wrong runtime.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter?: RuntimeAdapterEnumApi | null
    /**
     * Selected LLM model identifier. Write-only; used only to reuse a warm Run started on the same model.
     * @nullable
     */
    model?: string | null
    /** Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max
     * * `ultracode` - ultracode */
    reasoning_effort?: ReasoningEffortEnumApi | null
    /** Selected agent permission mode. Write-only; used only to reuse a warm Run booted on the same mode. Omit to reuse a warm Run whatever mode it booted on.
     *
     * * `default` - default
     * * `acceptEdits` - acceptEdits
     * * `plan` - plan
     * * `bypassPermissions` - bypassPermissions
     * * `auto` - auto
     * * `read-only` - read-only
     * * `full-access` - full-access */
    initial_permission_mode?: TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi | null
    /**
     * First user message to forward when creation reuses a pre-warmed Run. Write-only and not persisted on the task: lets clients deliver a message that differs from `description` (e.g. a resolved skill invocation with channel context folded in). Ignored when no warm Run is reused — cold creation takes the first message via the run start endpoint instead.
     * @nullable
     */
    pending_user_message?: string | null
    /**
     * Run artifact ids (already uploaded to the pre-warmed Run) to attach to the forwarded first message when creation reuses that warm Run, e.g. skill bundles or file attachments. If any id is missing from the warm Run's manifest, warm reuse is skipped and the task is created cold. Ignored when no warm Run is matched.
     * @items.maxLength 128
     */
    pending_user_artifact_ids?: string[]
    /**
     * When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask. Write-only and not persisted on the task: persisted into the reused warm Run's state when creation activates one, so resumes of that Run honor it. Ignored when no warm Run is reused — cold creation takes it via the run start endpoint instead.
     * @nullable
     */
    auto_publish?: boolean | null
    /**
     * Channel this task is owned by (the channel it was kicked off in).
     * @nullable
     */
    channel?: string | null
    /** Text the server generates the title from instead of `description`. Lets a client whose `description` is only an attachment summary (e.g. pasted text stored as a file) supply the real content for naming, so `description` (the prompt passed to the agent) stays unchanged. Not persisted. */
    naming_source?: string
    /**
     * Sandbox environment selected for matching a pre-warmed cloud run. Not persisted on the task.
     * @nullable
     */
    sandbox_environment_id?: string | null
    /**
     * Custom image selected for matching a pre-warmed cloud run. Not persisted on the task.
     * @nullable
     */
    custom_image_id?: string | null
    /** Agent protocol and harness used for this task's runs. Defaults to ACP when omitted.
     *
     * * `acp` - ACP
     * * `pi` - Pi */
    runtime?: RuntimeEnumApi
}

/**
 * Request body for creating or updating a task.
 *
 * Field required/default semantics match the ``Task`` model. The view passes
 * ``validated_data`` (integration/report PK fields already resolved to instances) to the
 * facade ``create_task`` / ``update_task`` functions.
 */
export interface TaskWriteApi {
    /**
     * Short human-readable title. Auto-generated from `description` when omitted.
     * @maxLength 255
     */
    title?: string
    /** Whether the title was set by a human (vs auto-generated from the description). */
    title_manually_set?: boolean
    /** Free-form description of the work to be done. Used as the prompt passed to the agent. */
    description?: string
    /** PostHog product or surface that created this task (e.g. error_tracking, slack, user_created). Origins reserved for server-created agents cannot be set through this API.
     *
     * * `onboarding` - Onboarding
     * * `error_tracking` - Error Tracking
     * * `eval_clusters` - Eval Clusters
     * * `user_created` - User Created
     * * `slack` - Slack
     * * `support_queue` - Support Queue
     * * `session_summaries` - Session Summaries
     * * `posthog_ai` - PostHog AI
     * * `experiments` - Experiments
     * * `signal_report` - Signal Report
     * * `signals_scout` - Signals Scout
     * * `support_reply` - Support Reply
     * * `hogdesk` - HogDesk
     * * `review_hog` - ReviewHog
     * * `image_builder` - Image Builder
     * * `loop` - Loop
     * * `mcp_analytics` - MCP Analytics
     * * `signals_chat` - Signals Chat
     * * `task_analysis` - Task Analysis
     * * `workflow` - Workflow */
    origin_product?: OriginProductEnumApi
    /**
     * Target GitHub repository in `organization/repo` format (e.g. `posthog/posthog-js`).
     * @maxLength 255
     * @nullable
     */
    repository?: string | null
    /**
     * GitHub repositories available to this task, each in `organization/repo` format.
     * @maxItems 10
     * @items.maxLength 255
     */
    repositories?: string[]
    /**
     * GitHub integration for this task.
     * @nullable
     */
    github_integration?: number | null
    /**
     * User-scoped GitHub integration to use for user-authored cloud runs.
     * @nullable
     */
    github_user_integration?: string | null
    /**
     * Signal report this task implements, when created from a report.
     * @nullable
     */
    signal_report?: string | null
    /**
     * How the created task relates to the signal report (e.g. 'implementation', 'discussion'). Recorded as a signals task_run work-log entry; 'implementation' also opens the auto-start spend gate. Any routing-safe identifier (lowercase letters, numbers, '_', '-') is accepted except labels reserved for server-created tasks ('research', 'repo_selection', 'scout'). Non-implementation labels count toward the report's discussion task limit.
     * @maxLength 200
     */
    signal_report_task_relationship?: string
    /** JSON schema used to validate the output of the task. */
    json_schema?: unknown
    /** If true, the task is hidden from default list responses. */
    archived?: boolean
    /**
     * Custom prompt for CI fixes. If blank, a default prompt will be used.
     * @nullable
     */
    ci_prompt?: string | null
    /**
     * Branch the user has selected for this cloud task. Write-only and not persisted on the task itself: used only to reuse a matching pre-warmed sandbox Run on creation (the branch is otherwise carried on the run). Omit to match a warm Run on the default branch.
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** Selected runtime adapter ('claude' or 'codex'). Write-only and not persisted on the task: used only to reuse a pre-warmed Run started on the same runtime. A value differing from the warm Run's runtime skips reuse so the task isn't silently run on the wrong runtime.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter?: RuntimeAdapterEnumApi | null
    /**
     * Selected LLM model identifier. Write-only; used only to reuse a warm Run started on the same model.
     * @nullable
     */
    model?: string | null
    /** Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max
     * * `ultracode` - ultracode */
    reasoning_effort?: ReasoningEffortEnumApi | null
    /** Selected agent permission mode. Write-only; used only to reuse a warm Run booted on the same mode. Omit to reuse a warm Run whatever mode it booted on.
     *
     * * `default` - default
     * * `acceptEdits` - acceptEdits
     * * `plan` - plan
     * * `bypassPermissions` - bypassPermissions
     * * `auto` - auto
     * * `read-only` - read-only
     * * `full-access` - full-access */
    initial_permission_mode?: TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi | null
    /**
     * First user message to forward when creation reuses a pre-warmed Run. Write-only and not persisted on the task: lets clients deliver a message that differs from `description` (e.g. a resolved skill invocation with channel context folded in). Ignored when no warm Run is reused — cold creation takes the first message via the run start endpoint instead.
     * @nullable
     */
    pending_user_message?: string | null
    /**
     * Run artifact ids (already uploaded to the pre-warmed Run) to attach to the forwarded first message when creation reuses that warm Run, e.g. skill bundles or file attachments. If any id is missing from the warm Run's manifest, warm reuse is skipped and the task is created cold. Ignored when no warm Run is matched.
     * @items.maxLength 128
     */
    pending_user_artifact_ids?: string[]
    /**
     * When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask. Write-only and not persisted on the task: persisted into the reused warm Run's state when creation activates one, so resumes of that Run honor it. Ignored when no warm Run is reused — cold creation takes it via the run start endpoint instead.
     * @nullable
     */
    auto_publish?: boolean | null
    /**
     * Channel this task is owned by (the channel it was kicked off in).
     * @nullable
     */
    channel?: string | null
}

/**
 * Request body for creating or updating a task.
 *
 * Field required/default semantics match the ``Task`` model. The view passes
 * ``validated_data`` (integration/report PK fields already resolved to instances) to the
 * facade ``create_task`` / ``update_task`` functions.
 */
export interface PatchedTaskWriteApi {
    /**
     * Short human-readable title. Auto-generated from `description` when omitted.
     * @maxLength 255
     */
    title?: string
    /** Whether the title was set by a human (vs auto-generated from the description). */
    title_manually_set?: boolean
    /** Free-form description of the work to be done. Used as the prompt passed to the agent. */
    description?: string
    /** PostHog product or surface that created this task (e.g. error_tracking, slack, user_created). Origins reserved for server-created agents cannot be set through this API.
     *
     * * `onboarding` - Onboarding
     * * `error_tracking` - Error Tracking
     * * `eval_clusters` - Eval Clusters
     * * `user_created` - User Created
     * * `slack` - Slack
     * * `support_queue` - Support Queue
     * * `session_summaries` - Session Summaries
     * * `posthog_ai` - PostHog AI
     * * `experiments` - Experiments
     * * `signal_report` - Signal Report
     * * `signals_scout` - Signals Scout
     * * `support_reply` - Support Reply
     * * `hogdesk` - HogDesk
     * * `review_hog` - ReviewHog
     * * `image_builder` - Image Builder
     * * `loop` - Loop
     * * `mcp_analytics` - MCP Analytics
     * * `signals_chat` - Signals Chat
     * * `task_analysis` - Task Analysis
     * * `workflow` - Workflow */
    origin_product?: OriginProductEnumApi
    /**
     * Target GitHub repository in `organization/repo` format (e.g. `posthog/posthog-js`).
     * @maxLength 255
     * @nullable
     */
    repository?: string | null
    /**
     * GitHub repositories available to this task, each in `organization/repo` format.
     * @maxItems 10
     * @items.maxLength 255
     */
    repositories?: string[]
    /**
     * GitHub integration for this task.
     * @nullable
     */
    github_integration?: number | null
    /**
     * User-scoped GitHub integration to use for user-authored cloud runs.
     * @nullable
     */
    github_user_integration?: string | null
    /**
     * Signal report this task implements, when created from a report.
     * @nullable
     */
    signal_report?: string | null
    /**
     * How the created task relates to the signal report (e.g. 'implementation', 'discussion'). Recorded as a signals task_run work-log entry; 'implementation' also opens the auto-start spend gate. Any routing-safe identifier (lowercase letters, numbers, '_', '-') is accepted except labels reserved for server-created tasks ('research', 'repo_selection', 'scout'). Non-implementation labels count toward the report's discussion task limit.
     * @maxLength 200
     */
    signal_report_task_relationship?: string
    /** JSON schema used to validate the output of the task. */
    json_schema?: unknown
    /** If true, the task is hidden from default list responses. */
    archived?: boolean
    /**
     * Custom prompt for CI fixes. If blank, a default prompt will be used.
     * @nullable
     */
    ci_prompt?: string | null
    /**
     * Branch the user has selected for this cloud task. Write-only and not persisted on the task itself: used only to reuse a matching pre-warmed sandbox Run on creation (the branch is otherwise carried on the run). Omit to match a warm Run on the default branch.
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** Selected runtime adapter ('claude' or 'codex'). Write-only and not persisted on the task: used only to reuse a pre-warmed Run started on the same runtime. A value differing from the warm Run's runtime skips reuse so the task isn't silently run on the wrong runtime.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter?: RuntimeAdapterEnumApi | null
    /**
     * Selected LLM model identifier. Write-only; used only to reuse a warm Run started on the same model.
     * @nullable
     */
    model?: string | null
    /** Selected reasoning effort. Write-only; used only to reuse a warm Run started on the same effort.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max
     * * `ultracode` - ultracode */
    reasoning_effort?: ReasoningEffortEnumApi | null
    /** Selected agent permission mode. Write-only; used only to reuse a warm Run booted on the same mode. Omit to reuse a warm Run whatever mode it booted on.
     *
     * * `default` - default
     * * `acceptEdits` - acceptEdits
     * * `plan` - plan
     * * `bypassPermissions` - bypassPermissions
     * * `auto` - auto
     * * `read-only` - read-only
     * * `full-access` - full-access */
    initial_permission_mode?: TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi | null
    /**
     * First user message to forward when creation reuses a pre-warmed Run. Write-only and not persisted on the task: lets clients deliver a message that differs from `description` (e.g. a resolved skill invocation with channel context folded in). Ignored when no warm Run is reused — cold creation takes the first message via the run start endpoint instead.
     * @nullable
     */
    pending_user_message?: string | null
    /**
     * Run artifact ids (already uploaded to the pre-warmed Run) to attach to the forwarded first message when creation reuses that warm Run, e.g. skill bundles or file attachments. If any id is missing from the warm Run's manifest, warm reuse is skipped and the task is created cold. Ignored when no warm Run is matched.
     * @items.maxLength 128
     */
    pending_user_artifact_ids?: string[]
    /**
     * When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask. Write-only and not persisted on the task: persisted into the reused warm Run's state when creation activates one, so resumes of that Run honor it. Ignored when no warm Run is reused — cold creation takes it via the run start endpoint instead.
     * @nullable
     */
    auto_publish?: boolean | null
    /**
     * Channel this task is owned by (the channel it was kicked off in).
     * @nullable
     */
    channel?: string | null
}

export interface TaskArtifactApi {
    /** Stable artifact id used to filter task comments. */
    id: string
    /** Artifact type: artifact or canvas. */
    type: string
    /** Display name of the artifact. */
    name: string
}

export interface TaskArtifactsResponseApi {
    /** Artifacts and canvases linked to this task. */
    artifacts: TaskArtifactApi[]
}

export interface TaskCommentTargetApi {
    /** Stable target id. */
    id: string
    /** Target type: task, artifact, or canvas. */
    type: string
    /** Display name of the comment target. */
    name: string
}

export interface TaskCommentSummaryApi {
    /** Root comment id. */
    id: string
    /** Task, artifact, or canvas receiving the comment. */
    target: TaskCommentTargetApi
    /** Bounded excerpt of the root comment body. */
    content: string
    /** Whether the root comment body has more content. */
    content_truncated: boolean
    /**
     * Text selected when the comment was created.
     * @nullable
     */
    selected_text: string | null
    /** When the root comment was created. */
    created_at: string
    /** Number of human replies. */
    reply_count: number
    /** Whether the comment is resolved. */
    resolved: boolean
}

export interface TaskCommentsResponseApi {
    /** Root comments, newest first. */
    comments: TaskCommentSummaryApi[]
    /**
     * Opaque cursor for the next page, or null.
     * @nullable
     */
    next: string | null
}

export interface TaskCommentAnchorApi {
    /** Anchor kind. */
    kind?: string
    /** Selected text. */
    quote?: string
    /** Text immediately before the selection. */
    prefix?: string
    /** Text immediately after the selection. */
    suffix?: string
    /**
     * Selection start offset.
     * @minimum 0
     */
    start?: number
    /**
     * Selection end offset.
     * @minimum 1
     */
    end?: number
    /**
     * Horizontal region position.
     * @minimum 0
     * @maximum 1
     */
    x?: number
    /**
     * Vertical region position.
     * @minimum 0
     * @maximum 1
     */
    y?: number
    /**
     * Region width.
     * @minimum 0
     * @maximum 1
     */
    width?: number
    /**
     * Region height.
     * @minimum 0
     * @maximum 1
     */
    height?: number
}

export interface TaskCommentEntryApi {
    /** Comment id. */
    id: string
    /** Byte-bounded comment body chunk. */
    content: string
    /** Whether this comment body has more content. */
    content_truncated: boolean
    /**
     * Byte offset for the next body chunk, or null when complete.
     * @nullable
     */
    content_next_offset: number | null
    /**
     * Comment author's display name.
     * @nullable
     */
    author: string | null
    /** When the comment was created. */
    created_at: string
    /** Normalized text or document anchor. */
    anchor: TaskCommentAnchorApi | null
    /**
     * Canvas version receiving the comment.
     * @nullable
     */
    canvas_version_id: string | null
}

export interface TaskCommentDetailApi {
    /** Root comment id. */
    id: string
    /** Task, artifact, or canvas receiving the comment. */
    target: TaskCommentTargetApi
    /** Whether the comment is resolved. */
    resolved: boolean
    /** Comments in this page, oldest first. */
    comments: TaskCommentEntryApi[]
    /**
     * Opaque cursor for the next page, or null.
     * @nullable
     */
    next: string | null
}

/**
 * Request body for handing a task off to a colleague: they become its owner.
 */
export interface TaskHandoffRequestApi {
    /**
     * ID of the user taking over the task. Must have access to this project and not be the task's current owner.
     * @minimum 1
     */
    user: number
}

export interface TaskPinRequestApi {
    /** Whether the task should be pinned for the requester. */
    pinned: boolean
}

export interface TaskPinResponseApi {
    /** Task whose pin state was updated. */
    task_id: string
    /** Current pin state for the requester. */
    pinned: boolean
}

/**
 * Request body for the presence beacon and beacon-leave endpoints.
 *
 * `device_id` is the UUID of the caller's `UserPushToken` row, which the
 * client received when it registered for push via `/api/users/@me/push_tokens/`.
 * The client is expected to use the same identifier on the beacon and leave
 * calls; if the user has unregistered the underlying push token, the value
 * won't resolve and the call returns 404 — at which point pushes were
 * already not going there anyway.
 */
export interface TaskPresenceBeaconRequestApi {
    /** UUID of the caller's UserPushToken (returned by `/api/users/@me/push_tokens/` on register). */
    device_id: string
}

/**
 * * `http` - http
 * * `sse` - sse
 */
export type ImportedMcpServerTypeEnumApi =
    (typeof ImportedMcpServerTypeEnumApi)[keyof typeof ImportedMcpServerTypeEnumApi]

export const ImportedMcpServerTypeEnumApi = {
    Http: 'http',
    Sse: 'sse',
} as const

export interface ImportedMcpServerHeaderApi {
    /** @maxLength 256 */
    name: string
    /** @maxLength 4096 */
    value: string
}

/**
 * One client-imported MCP server, in the agent server's --mcpServers entry shape.
 */
export interface ImportedMcpServerApi {
    type: ImportedMcpServerTypeEnumApi
    /** @maxLength 64 */
    name: string
    /** @maxLength 2048 */
    url: string
    headers?: ImportedMcpServerHeaderApi[]
}

/**
 * One desktop-only MCP server relayed into the run — a name only, never configuration.
 */
export interface RelayedMcpServerApi {
    /** @maxLength 64 */
    name: string
}

/**
 * * `interactive` - interactive
 * * `background` - background
 */
export type TaskExecutionModeEnumApi = (typeof TaskExecutionModeEnumApi)[keyof typeof TaskExecutionModeEnumApi]

export const TaskExecutionModeEnumApi = {
    Interactive: 'interactive',
    Background: 'background',
} as const

/**
 * * `user` - user
 * * `bot` - bot
 */
export type PrAuthorshipModeEnumApi = (typeof PrAuthorshipModeEnumApi)[keyof typeof PrAuthorshipModeEnumApi]

export const PrAuthorshipModeEnumApi = {
    User: 'user',
    Bot: 'bot',
} as const

/**
 * * `manual` - manual
 * * `signal_report` - signal_report
 */
export type RunSourceEnumApi = (typeof RunSourceEnumApi)[keyof typeof RunSourceEnumApi]

export const RunSourceEnumApi = {
    Manual: 'manual',
    SignalReport: 'signal_report',
} as const

/**
 * * `claude` - claude
 */
export type ClaudeRuntimeAdapterEnumApi = (typeof ClaudeRuntimeAdapterEnumApi)[keyof typeof ClaudeRuntimeAdapterEnumApi]

export const ClaudeRuntimeAdapterEnumApi = {
    Claude: 'claude',
} as const

/**
 * * `200k` - 200k
 * * `1m` - 1m
 */
export type ContextWindowEnumApi = (typeof ContextWindowEnumApi)[keyof typeof ContextWindowEnumApi]

export const ContextWindowEnumApi = {
    '200k': '200k',
    '1m': '1m',
} as const

/**
 * * `default` - default
 * * `acceptEdits` - acceptEdits
 * * `plan` - plan
 * * `bypassPermissions` - bypassPermissions
 * * `auto` - auto
 */
export type InitialPermissionModeEnumApi =
    (typeof InitialPermissionModeEnumApi)[keyof typeof InitialPermissionModeEnumApi]

export const InitialPermissionModeEnumApi = {
    Default: 'default',
    AcceptEdits: 'acceptEdits',
    Plan: 'plan',
    BypassPermissions: 'bypassPermissions',
    Auto: 'auto',
} as const

/**
 * Request body for creating a new task run
 */
export interface ClaudeTaskRunCreateSchemaApi {
    /**
     * Local url-based MCP servers from the creating client (PostHog Desktop) to make available inside the cloud sandbox. Header values are treated as credentials: stored encrypted and never returned by the API.
     * @nullable
     */
    imported_mcp_servers?: ImportedMcpServerApi[] | null
    /**
     * Names of desktop-only MCP servers the creating client (PostHog Desktop) relays into the cloud sandbox over the durable event/command channel. Names only — the server configuration (command, env, URL, headers) never crosses the wire.
     * @nullable
     */
    relayed_mcp_servers?: RelayedMcpServerApi[] | null
    /** Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs
     *
     * * `interactive` - interactive
     * * `background` - background */
    mode?: TaskExecutionModeEnumApi
    /**
     * Git branch to checkout in the sandbox
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** ID of a previous run to resume from. Must belong to the same task. */
    resume_from_run_id?: string
    /** Initial or follow-up user message to include in the run prompt. */
    pending_user_message?: string
    /**
     * Identifiers for staged task artifacts that should be attached to the initial run prompt.
     * @items.maxLength 128
     */
    pending_user_artifact_ids?: string[]
    /** Optional sandbox environment to apply for this cloud run. */
    sandbox_environment_id?: string
    /** Optional custom base image for this cloud run's sandbox (Modal VM runtime only); takes precedence over the environment's image. */
    custom_image_id?: string
    /** Whether pull requests for this run should be authored by the user or the bot.
     *
     * * `user` - user
     * * `bot` - bot */
    pr_authorship_mode?: PrAuthorshipModeEnumApi
    /**
     * When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask.
     * @nullable
     */
    auto_publish?: boolean | null
    /** High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.
     *
     * * `manual` - manual
     * * `signal_report` - signal_report */
    run_source?: RunSourceEnumApi
    /** Optional signal report identifier when this run was started from Inbox. */
    signal_report_id?: string
    /** Agent runtime adapter to launch for this run. Must be 'claude' for Claude runtimes.
     *
     * * `claude` - claude */
    runtime_adapter: ClaudeRuntimeAdapterEnumApi
    /** LLM model identifier to run in the Claude runtime. */
    model: string
    /** Reasoning effort to request for models that expose an effort control.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max
     * * `ultracode` - ultracode */
    reasoning_effort?: ReasoningEffortEnumApi
    /** Context window size for models that support the 1M window.
     *
     * * `200k` - 200k
     * * `1m` - 1m */
    context_window?: ContextWindowEnumApi
    /**
     * Enable fast mode for models that support it.
     * @nullable
     */
    fast_mode?: boolean | null
    /** Optional GitHub user token from PostHog Desktop for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens. */
    github_user_token?: string
    /** Initial permission mode for Claude runtimes.
     *
     * * `default` - default
     * * `acceptEdits` - acceptEdits
     * * `plan` - plan
     * * `bypassPermissions` - bypassPermissions
     * * `auto` - auto */
    initial_permission_mode?: InitialPermissionModeEnumApi
    /**
     * Whether rtk command-output compression is enabled for this run. Omitted or null follows the server-side default (enabled); false opts this run out.
     * @nullable
     */
    rtk_enabled?: boolean | null
}

/**
 * * `codex` - codex
 */
export type CodexRuntimeAdapterEnumApi = (typeof CodexRuntimeAdapterEnumApi)[keyof typeof CodexRuntimeAdapterEnumApi]

export const CodexRuntimeAdapterEnumApi = {
    Codex: 'codex',
} as const

/**
 * * `plan` - plan
 * * `auto` - auto
 * * `read-only` - read-only
 * * `full-access` - full-access
 */
export type CodexTaskRunCreateSchemaInitialPermissionModeEnumApi =
    (typeof CodexTaskRunCreateSchemaInitialPermissionModeEnumApi)[keyof typeof CodexTaskRunCreateSchemaInitialPermissionModeEnumApi]

export const CodexTaskRunCreateSchemaInitialPermissionModeEnumApi = {
    Plan: 'plan',
    Auto: 'auto',
    ReadOnly: 'read-only',
    FullAccess: 'full-access',
} as const

/**
 * Request body for creating a new task run
 */
export interface CodexTaskRunCreateSchemaApi {
    /**
     * Local url-based MCP servers from the creating client (PostHog Desktop) to make available inside the cloud sandbox. Header values are treated as credentials: stored encrypted and never returned by the API.
     * @nullable
     */
    imported_mcp_servers?: ImportedMcpServerApi[] | null
    /**
     * Names of desktop-only MCP servers the creating client (PostHog Desktop) relays into the cloud sandbox over the durable event/command channel. Names only — the server configuration (command, env, URL, headers) never crosses the wire.
     * @nullable
     */
    relayed_mcp_servers?: RelayedMcpServerApi[] | null
    /** Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs
     *
     * * `interactive` - interactive
     * * `background` - background */
    mode?: TaskExecutionModeEnumApi
    /**
     * Git branch to checkout in the sandbox
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** ID of a previous run to resume from. Must belong to the same task. */
    resume_from_run_id?: string
    /** Initial or follow-up user message to include in the run prompt. */
    pending_user_message?: string
    /**
     * Identifiers for staged task artifacts that should be attached to the initial run prompt.
     * @items.maxLength 128
     */
    pending_user_artifact_ids?: string[]
    /** Optional sandbox environment to apply for this cloud run. */
    sandbox_environment_id?: string
    /** Optional custom base image for this cloud run's sandbox (Modal VM runtime only); takes precedence over the environment's image. */
    custom_image_id?: string
    /** Whether pull requests for this run should be authored by the user or the bot.
     *
     * * `user` - user
     * * `bot` - bot */
    pr_authorship_mode?: PrAuthorshipModeEnumApi
    /**
     * When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask.
     * @nullable
     */
    auto_publish?: boolean | null
    /** High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.
     *
     * * `manual` - manual
     * * `signal_report` - signal_report */
    run_source?: RunSourceEnumApi
    /** Optional signal report identifier when this run was started from Inbox. */
    signal_report_id?: string
    /** Agent runtime adapter to launch for this run. Must be 'codex' for Codex runtimes.
     *
     * * `codex` - codex */
    runtime_adapter: CodexRuntimeAdapterEnumApi
    /** LLM model identifier to run in the Codex runtime. */
    model: string
    /** Reasoning effort to request for models that expose an effort control.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max
     * * `ultracode` - ultracode */
    reasoning_effort?: ReasoningEffortEnumApi
    /** Context window size for models that support the 1M window.
     *
     * * `200k` - 200k
     * * `1m` - 1m */
    context_window?: ContextWindowEnumApi
    /**
     * Enable fast mode for models that support it.
     * @nullable
     */
    fast_mode?: boolean | null
    /** Optional GitHub user token from PostHog Desktop for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens. */
    github_user_token?: string
    /** Initial permission mode for Codex runtimes.
     *
     * * `plan` - plan
     * * `auto` - auto
     * * `read-only` - read-only
     * * `full-access` - full-access */
    initial_permission_mode?: CodexTaskRunCreateSchemaInitialPermissionModeEnumApi
    /**
     * Whether rtk command-output compression is enabled for this run. Omitted or null follows the server-side default (enabled); false opts this run out.
     * @nullable
     */
    rtk_enabled?: boolean | null
}

export interface TaskRunResumeRequestSchemaApi {
    /** Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs
     *
     * * `interactive` - interactive
     * * `background` - background */
    mode?: TaskExecutionModeEnumApi
    /**
     * Git branch to checkout in the sandbox
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** ID of a previous run to resume from. Must belong to the same task. */
    resume_from_run_id?: string
    /** Initial or follow-up user message to include in the run prompt. */
    pending_user_message?: string
    /** Optional sandbox environment to apply for this cloud run. */
    sandbox_environment_id?: string
    /** Optional custom base image for this cloud run's sandbox (Modal VM runtime only); takes precedence over the environment's image. */
    custom_image_id?: string
    /** Whether pull requests for this run should be authored by the user or the bot.
     *
     * * `user` - user
     * * `bot` - bot */
    pr_authorship_mode?: PrAuthorshipModeEnumApi
    /** High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.
     *
     * * `manual` - manual
     * * `signal_report` - signal_report */
    run_source?: RunSourceEnumApi
    /** Optional signal report identifier when this run was started from Inbox. */
    signal_report_id?: string
    /** Optional GitHub user token from PostHog Desktop for user-authored cloud pull requests. Prefer linking GitHub from Settings → Linked accounts so the server can manage tokens; this field remains supported for callers that still manage their own tokens. */
    github_user_token?: string
}

export type TaskRunCreateRequestSchemaApi =
    | ClaudeTaskRunCreateSchemaApi
    | CodexTaskRunCreateSchemaApi
    | TaskRunResumeRequestSchemaApi

/**
 * * `plan` - plan
 * * `context` - context
 * * `reference` - reference
 * * `output` - output
 * * `artifact` - artifact
 * * `tree_snapshot` - tree_snapshot
 * * `user_attachment` - user_attachment
 * * `skill_bundle` - skill_bundle
 */
export type TaskRunArtifactTypeEnumApi = (typeof TaskRunArtifactTypeEnumApi)[keyof typeof TaskRunArtifactTypeEnumApi]

export const TaskRunArtifactTypeEnumApi = {
    Plan: 'plan',
    Context: 'context',
    Reference: 'reference',
    Output: 'output',
    Artifact: 'artifact',
    TreeSnapshot: 'tree_snapshot',
    UserAttachment: 'user_attachment',
    SkillBundle: 'skill_bundle',
} as const

export interface TaskStagedArtifactFinalizeUploadApi {
    /** Stable identifier returned by the staged prepare upload endpoint */
    id: string
    /**
     * File name associated with the staged artifact
     * @maxLength 255
     */
    name: string
    /** Classification for the artifact
     *
     * * `plan` - plan
     * * `context` - context
     * * `reference` - reference
     * * `output` - output
     * * `artifact` - artifact
     * * `tree_snapshot` - tree_snapshot
     * * `user_attachment` - user_attachment
     * * `skill_bundle` - skill_bundle */
    type: TaskRunArtifactTypeEnumApi
    /**
     * Optional source label for the artifact, such as agent_output or user_attachment
     * @maxLength 64
     */
    source?: string
    /**
     * S3 object key returned by the prepare step
     * @maxLength 500
     */
    storage_path: string
    /**
     * Optional MIME type recorded for the artifact
     * @maxLength 255
     */
    content_type?: string
    /** Skill bundle metadata, required when the artifact type is skill_bundle. */
    metadata?: TaskRunSkillBundleMetadataApi
}

export interface TaskStagedArtifactsFinalizeUploadRequestApi {
    /** Array of staged artifacts to finalize after upload */
    artifacts: TaskStagedArtifactFinalizeUploadApi[]
}

export interface TaskStagedArtifactsFinalizeUploadResponseApi {
    /** Finalized staged artifacts available for attachment to a new run */
    artifacts: TaskRunArtifactResponseApi[]
}

export interface TaskStagedArtifactPrepareUploadApi {
    /**
     * File name to associate with the staged artifact
     * @maxLength 255
     */
    name: string
    /** Classification for the artifact
     *
     * * `plan` - plan
     * * `context` - context
     * * `reference` - reference
     * * `output` - output
     * * `artifact` - artifact
     * * `tree_snapshot` - tree_snapshot
     * * `user_attachment` - user_attachment
     * * `skill_bundle` - skill_bundle */
    type: TaskRunArtifactTypeEnumApi
    /**
     * Optional source label for the artifact, such as agent_output or user_attachment
     * @maxLength 64
     */
    source?: string
    /**
     * Expected upload size in bytes (max 31457280 bytes)
     * @minimum 1
     * @maximum 31457280
     */
    size: number
    /**
     * Optional MIME type for the artifact upload
     * @maxLength 255
     */
    content_type?: string
    /** Skill bundle metadata, required when the artifact type is skill_bundle. */
    metadata?: TaskRunSkillBundleMetadataApi
}

export interface TaskStagedArtifactsPrepareUploadRequestApi {
    /** Array of staged artifacts to prepare before creating a run */
    artifacts: TaskStagedArtifactPrepareUploadApi[]
}

/**
 * Form fields that must be submitted verbatim with the file upload
 */
export type S3PresignedPostApiFields = { [key: string]: string }

export interface S3PresignedPostApi {
    /** Presigned S3 POST URL */
    url: string
    /** Form fields that must be submitted verbatim with the file upload */
    fields: S3PresignedPostApiFields
}

export interface TaskStagedArtifactPrepareUploadResponseApi {
    /** Stable identifier for the prepared staged artifact within this task */
    id: string
    /** Artifact file name */
    name: string
    /** Artifact classification (plan, context, etc.) */
    type: string
    /** Source of the artifact, such as agent_output or user_attachment */
    source?: string
    /** Expected upload size in bytes */
    size: number
    /** Optional MIME type */
    content_type?: string
    /** Skill bundle metadata, required when the artifact type is skill_bundle. */
    metadata?: TaskRunSkillBundleMetadataApi
    /** S3 object key reserved for the staged artifact */
    storage_path: string
    /** Presigned POST expiry in seconds */
    expires_in: number
    /** Presigned S3 POST configuration for uploading the file */
    presigned_post: S3PresignedPostApi
}

export interface TaskStagedArtifactsPrepareUploadResponseApi {
    /** Prepared staged uploads for the requested artifacts */
    artifacts: TaskStagedArtifactPrepareUploadResponseApi[]
}

export interface TaskUsageResponseApi {
    /** Estimated model cost attributed to this task in US dollars. */
    token_cost_usd: number
    /** Estimated cloud compute cost attributed to this task in US dollars. */
    compute_cost_usd: number
    /** Estimated total cost attributed to this task in US dollars. */
    total_cost_usd: number
}

/**
 * Request body for warming a successor to an existing terminal task run.
 */
export interface WarmTaskResumeRequestApi {
    /** ID of the task's latest terminal run whose snapshot and conversation should be resumed. */
    resume_from_run_id: string
    /** Agent runtime adapter to start before the next message is submitted.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter?: RuntimeAdapterEnumApi
    /** LLM model to start before the next message is submitted. */
    model?: string
    /** Reasoning effort to apply when the warmed successor receives its first message.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max
     * * `ultracode` - ultracode */
    reasoning_effort?: ReasoningEffortEnumApi
    /** Initial permission mode for the warmed successor's agent session.
     *
     * * `default` - default
     * * `acceptEdits` - acceptEdits
     * * `plan` - plan
     * * `bypassPermissions` - bypassPermissions
     * * `auto` - auto
     * * `read-only` - read-only
     * * `full-access` - full-access */
    initial_permission_mode?: TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi
}

/**
 * Response for a successfully warmed successor run on an existing task.
 */
export interface WarmTaskResumeResponseApi {
    /** ID of the existing task being resumed. */
    task_id: string
    /** ID of the idling successor run that submit will activate. */
    run_id: string
}

export interface PaginatedTaskRunDetailDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskRunDetailDTOApi[]
}

/**
 * * `local` - local
 * * `cloud` - cloud
 */
export type TaskRunBootstrapCreateRequestEnvironmentEnumApi =
    (typeof TaskRunBootstrapCreateRequestEnvironmentEnumApi)[keyof typeof TaskRunBootstrapCreateRequestEnvironmentEnumApi]

export const TaskRunBootstrapCreateRequestEnvironmentEnumApi = {
    Local: 'local',
    Cloud: 'cloud',
} as const

/**
 * Request body for creating a task run without starting execution yet.
 */
export interface TaskRunBootstrapCreateRequestApi {
    /**
     * Local url-based MCP servers from the creating client (PostHog Desktop) to make available inside the cloud sandbox. Header values are treated as credentials: stored encrypted and never returned by the API.
     * @nullable
     */
    imported_mcp_servers?: ImportedMcpServerApi[] | null
    /**
     * Names of desktop-only MCP servers the creating client (PostHog Desktop) relays into the cloud sandbox over the durable event/command channel. Names only — the server configuration (command, env, URL, headers) never crosses the wire.
     * @nullable
     */
    relayed_mcp_servers?: RelayedMcpServerApi[] | null
    /** Execution environment for the new run. Use 'cloud' for remote sandbox runs and 'local' for desktop sessions.
     *
     * * `local` - local
     * * `cloud` - cloud */
    environment?: TaskRunBootstrapCreateRequestEnvironmentEnumApi
    /** Execution mode: 'interactive' for user-connected runs, 'background' for autonomous runs
     *
     * * `interactive` - interactive
     * * `background` - background */
    mode?: TaskExecutionModeEnumApi
    /**
     * Git branch to checkout in the sandbox
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** Optional sandbox environment to apply for this cloud run. */
    sandbox_environment_id?: string
    /** Optional custom base image for this cloud run's sandbox (Modal VM runtime only); takes precedence over the environment's image. */
    custom_image_id?: string
    /** Whether pull requests for this run should be authored by the user or the bot.
     *
     * * `user` - user
     * * `bot` - bot */
    pr_authorship_mode?: PrAuthorshipModeEnumApi
    /**
     * When true, the cloud run agent pushes its work and opens a draft pull request on completion without waiting for an explicit ask.
     * @nullable
     */
    auto_publish?: boolean | null
    /** High-level source that triggered this run, used to distinguish manual and signal-based cloud runs.
     *
     * * `manual` - manual
     * * `signal_report` - signal_report */
    run_source?: RunSourceEnumApi
    /** Optional signal report identifier when this run was started from Inbox. */
    signal_report_id?: string
    /** Agent runtime adapter to launch for this run. Use 'claude' for the Claude runtime or 'codex' for the Codex runtime.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter?: RuntimeAdapterEnumApi
    /** LLM model identifier to run in the selected runtime. */
    model?: string
    /** Reasoning effort to request for models that expose an effort control.
     *
     * * `off` - off
     * * `minimal` - minimal
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max
     * * `ultracode` - ultracode */
    reasoning_effort?: TaskRunReasoningEffortEnumApi
    /** Context window size for models that support the 1M window.
     *
     * * `200k` - 200k
     * * `1m` - 1m */
    context_window?: ContextWindowEnumApi
    /**
     * Enable fast mode for models that support it.
     * @nullable
     */
    fast_mode?: boolean | null
    /** Ephemeral GitHub user token from PostHog Desktop for user-authored cloud pull requests. */
    github_user_token?: string
    /** Initial permission mode for the agent session. Claude runtimes accept PostHog permission presets like 'plan'. Codex runtimes accept native Codex modes like 'plan', 'auto', and 'read-only'.
     *
     * * `default` - default
     * * `acceptEdits` - acceptEdits
     * * `plan` - plan
     * * `bypassPermissions` - bypassPermissions
     * * `auto` - auto
     * * `read-only` - read-only
     * * `full-access` - full-access */
    initial_permission_mode?: TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi
    /**
     * Whether rtk command-output compression is enabled for this run. Omitted or null follows the server-side default (enabled); false opts this run out.
     * @nullable
     */
    rtk_enabled?: boolean | null
}

/**
 * State keys whose value to append to the list stored at that key, atomically under the row lock. Use instead of sending the whole list back through `state`, which loses concurrent appends to a read-modify-write race.
 */
export type PatchedTaskRunUpdateApiStateAppend = { [key: string]: unknown }

/**
 * * `not_started` - not_started
 * * `queued` - queued
 * * `in_progress` - in_progress
 * * `completed` - completed
 * * `failed` - failed
 * * `cancelled` - cancelled
 */
export type RunStatusEnumApi = (typeof RunStatusEnumApi)[keyof typeof RunStatusEnumApi]

export const RunStatusEnumApi = {
    NotStarted: 'not_started',
    Queued: 'queued',
    InProgress: 'in_progress',
    Completed: 'completed',
    Failed: 'failed',
    Cancelled: 'cancelled',
} as const

/**
 * * `local` - local
 */
export type TaskRunUpdateEnvironmentEnumApi =
    (typeof TaskRunUpdateEnvironmentEnumApi)[keyof typeof TaskRunUpdateEnvironmentEnumApi]

export const TaskRunUpdateEnvironmentEnumApi = {
    Local: 'local',
} as const

export interface PatchedTaskRunUpdateApi {
    /** Current execution status
     *
     * * `not_started` - not_started
     * * `queued` - queued
     * * `in_progress` - in_progress
     * * `completed` - completed
     * * `failed` - failed
     * * `cancelled` - cancelled */
    status?: RunStatusEnumApi
    /**
     * Git branch name to associate with the task
     * @nullable
     */
    branch?: string | null
    /**
     * Current stage of the run (e.g. research, plan, build)
     * @nullable
     */
    stage?: string | null
    /** Output from the run */
    output?: unknown
    /** State of the run */
    state?: unknown
    /** State keys to remove atomically before applying any state updates. */
    state_remove_keys?: string[]
    /** State keys whose value to append to the list stored at that key, atomically under the row lock. Use instead of sending the whole list back through `state`, which loses concurrent appends to a read-modify-write race. */
    state_append?: PatchedTaskRunUpdateApiStateAppend
    /**
     * Error message if execution failed
     * @nullable
     */
    error_message?: string | null
    /** Transition a cloud run to local. Use the resume_in_cloud action to move a run into cloud.
     *
     * * `local` - local */
    environment?: TaskRunUpdateEnvironmentEnumApi
}

/**
 * * `run_was_efficient` - run_was_efficient
 * * `too_short_to_judge` - too_short_to_judge
 * * `insufficient_visibility` - insufficient_visibility
 */
export type NoFindingsReasonEnumApi = (typeof NoFindingsReasonEnumApi)[keyof typeof NoFindingsReasonEnumApi]

export const NoFindingsReasonEnumApi = {
    RunWasEfficient: 'run_was_efficient',
    TooShortToJudge: 'too_short_to_judge',
    InsufficientVisibility: 'insufficient_visibility',
} as const

/**
 * * `transcript_quote` - transcript_quote
 * * `command_output` - command_output
 * * `measured_count` - measured_count
 */
export type EvidenceTypeEnumApi = (typeof EvidenceTypeEnumApi)[keyof typeof EvidenceTypeEnumApi]

export const EvidenceTypeEnumApi = {
    TranscriptQuote: 'transcript_quote',
    CommandOutput: 'command_output',
    MeasuredCount: 'measured_count',
} as const

export interface TaskAnalysisEvidenceApi {
    /**
     * Verbatim span copied from the analysed run log.
     * @minLength 20
     * @maxLength 300
     */
    quote: string
    /** What kind of log content the quote was taken from.
     *
     * * `transcript_quote` - transcript_quote
     * * `command_output` - command_output
     * * `measured_count` - measured_count */
    evidence_type: EvidenceTypeEnumApi
}

/**
 * * `environment_failure` - environment_failure
 * * `missing_tool` - missing_tool
 * * `verbose_output` - verbose_output
 * * `redundant_work` - redundant_work
 * * `missing_capability` - missing_capability
 * * `instruction_gap` - instruction_gap
 * * `wasted_retry` - wasted_retry
 * * `other` - other
 */
export type TaskRunAnalysisInsightRequestCategoryEnumApi =
    (typeof TaskRunAnalysisInsightRequestCategoryEnumApi)[keyof typeof TaskRunAnalysisInsightRequestCategoryEnumApi]

export const TaskRunAnalysisInsightRequestCategoryEnumApi = {
    EnvironmentFailure: 'environment_failure',
    MissingTool: 'missing_tool',
    VerboseOutput: 'verbose_output',
    RedundantWork: 'redundant_work',
    MissingCapability: 'missing_capability',
    InstructionGap: 'instruction_gap',
    WastedRetry: 'wasted_retry',
    Other: 'other',
} as const

export interface TaskAnalysisWastedEffortApi {
    /**
     * Wasted tool calls, counted from the log.
     * @minimum 1
     */
    tool_calls?: number
    /**
     * Wall-clock seconds across the wasted span.
     * @minimum 1
     */
    seconds?: number
    /**
     * Token delta across the wasted span.
     * @minimum 1
     */
    tokens?: number
    /**
     * Sum of tool-output sizes across the wasted span.
     * @minimum 1
     */
    output_bytes?: number
}

/**
 * * `every_run_in_this_repo` - every_run_in_this_repo
 * * `runs_touching_this_area` - runs_touching_this_area
 * * `one_off` - one_off
 */
export type RecurrenceEnumApi = (typeof RecurrenceEnumApi)[keyof typeof RecurrenceEnumApi]

export const RecurrenceEnumApi = {
    EveryRunInThisRepo: 'every_run_in_this_repo',
    RunsTouchingThisArea: 'runs_touching_this_area',
    OneOff: 'one_off',
} as const

/**
 * * `directly_observed` - directly_observed
 * * `inferred` - inferred
 */
export type ConfidenceBasisEnumApi = (typeof ConfidenceBasisEnumApi)[keyof typeof ConfidenceBasisEnumApi]

export const ConfidenceBasisEnumApi = {
    DirectlyObserved: 'directly_observed',
    Inferred: 'inferred',
} as const

export interface TaskAnalysisSuggestedFixApi {
    /**
     * The specific change to make.
     * @minLength 50
     * @maxLength 400
     */
    change: string
    /**
     * A checkable condition confirming the fix worked.
     * @minLength 30
     * @maxLength 200
     */
    done_when: string
    /**
     * Single-line commands only; these may become image build steps.
     * @maxItems 10
     * @items.minLength 1
     * @items.maxLength 500
     */
    setup_commands?: string[]
    /**
     * Services the fix needs available.
     * @maxItems 10
     * @items.minLength 1
     * @items.maxLength 100
     */
    required_services?: string[]
    /**
     * Environment variable names only, never values.
     * @maxItems 10
     * @items.minLength 1
     * @items.maxLength 100
     */
    env_var_names?: string[]
}

/**
 * One analysis finding. The shape the server stores, independent of what the tool sent.
 */
export interface TaskRunAnalysisInsightRequestApi {
    /** Only for a run with zero findings; never combined with a finding.
     *
     * * `run_was_efficient` - run_was_efficient
     * * `too_short_to_judge` - too_short_to_judge
     * * `insufficient_visibility` - insufficient_visibility */
    no_findings_reason?: NoFindingsReasonEnumApi
    /**
     * What happened, 1-3 sentences.
     * @minLength 80
     * @maxLength 500
     */
    observation?: string
    /** Quotes from the analysed log backing the observation. */
    evidence?: TaskAnalysisEvidenceApi[]
    /**
     * How often this happened.
     * @minimum 1
     */
    occurrence_count?: number
    /** The kind of inefficiency observed.
     *
     * * `environment_failure` - environment_failure
     * * `missing_tool` - missing_tool
     * * `verbose_output` - verbose_output
     * * `redundant_work` - redundant_work
     * * `missing_capability` - missing_capability
     * * `instruction_gap` - instruction_gap
     * * `wasted_retry` - wasted_retry
     * * `other` - other */
    category?: TaskRunAnalysisInsightRequestCategoryEnumApi
    /**
     * Required when category is 'other'.
     * @minLength 50
     * @maxLength 200
     */
    other_justification?: string
    /** Effort measured from the log, never estimated. */
    wasted_effort?: TaskAnalysisWastedEffortApi
    /** How widely this is expected to recur.
     *
     * * `every_run_in_this_repo` - every_run_in_this_repo
     * * `runs_touching_this_area` - runs_touching_this_area
     * * `one_off` - one_off */
    recurrence?: RecurrenceEnumApi
    /** How the finding was established.
     *
     * * `directly_observed` - directly_observed
     * * `inferred` - inferred */
    confidence_basis?: ConfidenceBasisEnumApi
    /** The fix the finding argues for. */
    suggested_fix?: TaskAnalysisSuggestedFixApi
}

export interface TaskRunAnalysisInsightResponseApi {
    /** Zero-based position of the stored finding on the run. */
    insight_index: number
}

export interface TaskRunAnalyzeResponseApi {
    /** Id of the analysis task to navigate to. */
    analysis_task_id: string
    /** True when a new analysis task was created; false when an existing analysis for this run was returned. */
    created: boolean
}

export type TaskRunAppendLogRequestApiEntriesItem = { [key: string]: unknown }

export interface TaskRunAppendLogRequestApi {
    /** Array of log entry dictionaries to append */
    entries: TaskRunAppendLogRequestApiEntriesItem[]
}

/**
 * * `utf-8` - utf-8
 * * `base64` - base64
 */
export type ContentEncodingEnumApi = (typeof ContentEncodingEnumApi)[keyof typeof ContentEncodingEnumApi]

export const ContentEncodingEnumApi = {
    Utf8: 'utf-8',
    Base64: 'base64',
} as const

export interface TaskRunArtifactUploadApi {
    /**
     * File name to associate with the artifact
     * @maxLength 255
     */
    name: string
    /** Classification for the artifact
     *
     * * `plan` - plan
     * * `context` - context
     * * `reference` - reference
     * * `output` - output
     * * `artifact` - artifact
     * * `tree_snapshot` - tree_snapshot
     * * `user_attachment` - user_attachment
     * * `skill_bundle` - skill_bundle */
    type: TaskRunArtifactTypeEnumApi
    /**
     * Optional source label for the artifact, such as agent_output or user_attachment
     * @maxLength 64
     */
    source?: string
    /** Artifact contents encoded according to content_encoding */
    content: string
    /** Encoding used for content. Use base64 for binary files and utf-8 for text payloads.
     *
     * * `utf-8` - utf-8
     * * `base64` - base64 */
    content_encoding?: ContentEncodingEnumApi
    /**
     * Optional MIME type for the artifact
     * @maxLength 255
     */
    content_type?: string
    /** Skill bundle metadata, required when the artifact type is skill_bundle. */
    metadata?: TaskRunSkillBundleMetadataApi
}

export interface TaskRunArtifactsUploadRequestApi {
    /** Array of artifacts to upload */
    artifacts: TaskRunArtifactUploadApi[]
}

export interface TaskRunArtifactsUploadResponseApi {
    /** Updated list of artifacts on the run */
    artifacts: TaskRunArtifactResponseApi[]
}

export interface TaskRunArtifactsDismissRequestApi {
    /**
     * Manifest ids of the artifacts to update. Pass every version of a file together so the whole file is dismissed rather than a single upload of it.
     * @maxItems 100
     * @items.maxLength 128
     */
    artifact_ids: string[]
    /** True to hide the artifacts from clients, false to show them again. */
    dismissed?: boolean
}

export interface TaskRunArtifactsDismissResponseApi {
    /** Updated list of artifacts on the run */
    artifacts: TaskRunArtifactResponseApi[]
}

export interface TaskRunArtifactPresignRequestApi {
    /**
     * S3 storage path returned in the artifact manifest
     * @maxLength 500
     */
    storage_path: string
}

export interface TaskRunArtifactFinalizeUploadApi {
    /** Stable identifier returned by the prepare upload endpoint */
    id: string
    /**
     * File name associated with the artifact
     * @maxLength 255
     */
    name: string
    /** Classification for the artifact
     *
     * * `plan` - plan
     * * `context` - context
     * * `reference` - reference
     * * `output` - output
     * * `artifact` - artifact
     * * `tree_snapshot` - tree_snapshot
     * * `user_attachment` - user_attachment
     * * `skill_bundle` - skill_bundle */
    type: TaskRunArtifactTypeEnumApi
    /**
     * Optional source label for the artifact, such as agent_output or user_attachment
     * @maxLength 64
     */
    source?: string
    /**
     * S3 object key returned by the prepare step
     * @maxLength 500
     */
    storage_path: string
    /**
     * Optional MIME type recorded for the artifact
     * @maxLength 255
     */
    content_type?: string
    /** Skill bundle metadata, required when the artifact type is skill_bundle. */
    metadata?: TaskRunSkillBundleMetadataApi
}

export interface TaskRunArtifactsFinalizeUploadRequestApi {
    /** Array of uploaded artifacts to finalize */
    artifacts: TaskRunArtifactFinalizeUploadApi[]
}

export interface TaskRunArtifactsFinalizeUploadResponseApi {
    /** Updated list of artifacts on the run */
    artifacts: TaskRunArtifactResponseApi[]
}

export interface TaskRunArtifactPrepareUploadApi {
    /**
     * File name to associate with the artifact
     * @maxLength 255
     */
    name: string
    /** Classification for the artifact
     *
     * * `plan` - plan
     * * `context` - context
     * * `reference` - reference
     * * `output` - output
     * * `artifact` - artifact
     * * `tree_snapshot` - tree_snapshot
     * * `user_attachment` - user_attachment
     * * `skill_bundle` - skill_bundle */
    type: TaskRunArtifactTypeEnumApi
    /**
     * Optional source label for the artifact, such as agent_output or user_attachment
     * @maxLength 64
     */
    source?: string
    /**
     * Expected upload size in bytes (max 31457280 bytes)
     * @minimum 1
     * @maximum 31457280
     */
    size: number
    /**
     * Optional MIME type for the artifact upload
     * @maxLength 255
     */
    content_type?: string
    /** Skill bundle metadata, required when the artifact type is skill_bundle. */
    metadata?: TaskRunSkillBundleMetadataApi
}

export interface TaskRunArtifactsPrepareUploadRequestApi {
    /** Array of artifacts to prepare */
    artifacts: TaskRunArtifactPrepareUploadApi[]
}

export interface TaskRunArtifactPrepareUploadResponseApi {
    /** Stable identifier for the prepared artifact within this run */
    id: string
    /** Artifact file name */
    name: string
    /** Artifact classification (plan, context, etc.) */
    type: string
    /** Source of the artifact, such as agent_output or user_attachment */
    source?: string
    /** Expected upload size in bytes */
    size: number
    /** Optional MIME type */
    content_type?: string
    /** Skill bundle metadata, required when the artifact type is skill_bundle. */
    metadata?: TaskRunSkillBundleMetadataApi
    /** S3 object key reserved for the artifact */
    storage_path: string
    /** Presigned POST expiry in seconds */
    expires_in: number
    /** Presigned S3 POST configuration for uploading the file */
    presigned_post: S3PresignedPostApi
}

export interface TaskRunArtifactsPrepareUploadResponseApi {
    /** Prepared uploads for the requested artifacts */
    artifacts: TaskRunArtifactPrepareUploadResponseApi[]
}

export interface TaskRunArtifactPresignResponseApi {
    /** Presigned URL for downloading the artifact */
    url: string
    /** URL expiry in seconds */
    expires_in: number
}

export interface TaskRunPostHogReferenceApi {
    /**
     * Fallback display name for the referenced object.
     * @maxLength 255
     */
    name: string
    /** PostHog object kind used to resolve the reference.
     *
     * * `insight` - insight
     * * `hogql` - hogql
     * * `dashboard` - dashboard
     * * `error` - error
     * * `replay` - replay
     * * `flag` - flag
     * * `experiment` - experiment
     * * `survey` - survey
     * * `ticket` - ticket
     * * `trace` - trace
     * * `eval` - eval
     * * `event` - event
     * * `cohort` - cohort
     * * `action` - action
     * * `person` - person */
    object_kind: ObjectKindEnumApi
    /**
     * Exact PostHog object identifier, flag key, event name, or SQL query.
     * @maxLength 16384
     */
    object_id: string
    /**
     * Stable identifier of the completed assistant message containing the reference.
     * @maxLength 255
     */
    source_message_id: string
}

export interface TaskRunPostHogReferencesRequestApi {
    /**
     * PostHog object references extracted from one completed assistant message.
     * @maxItems 50
     */
    references: TaskRunPostHogReferenceApi[]
}

export interface TaskRunPostHogReferencesResponseApi {
    /** Updated list of artifacts on the run. */
    artifacts: TaskRunArtifactResponseApi[]
}

export interface TaskRunCancelRequestApi {
    /**
     * Optional reason for the cancellation, recorded on the run and shown to run watchers.
     * @maxLength 500
     * @nullable
     */
    reason?: string | null
    /** Cancel only while the run is still a warm sandbox awaiting its first message. A run that has since received one is left alone and returned unchanged. Set this when handing a warm sandbox back, so a release that races a submit cannot stop the run that submit started. */
    only_if_awaiting_first_message?: boolean
}

/**
 * Parameters for the command
 */
export type TaskRunCommandRequestApiParams = { [key: string]: unknown }

/**
 * * `2.0` - 2.0
 */
export type JsonrpcEnumApi = (typeof JsonrpcEnumApi)[keyof typeof JsonrpcEnumApi]

export const JsonrpcEnumApi = {
    '20': '2.0',
} as const

/**
 * * `user_message` - user_message
 * * `cancel` - cancel
 * * `close` - close
 * * `permission_response` - permission_response
 * * `set_config_option` - set_config_option
 * * `mcp_response` - mcp_response
 * * `pi/rpc` - pi/rpc
 * * `queue_get` - queue_get
 * * `queue_clear` - queue_clear
 * * `side_question` - side_question
 */
export type TaskRunCommandRequestMethodEnumApi =
    (typeof TaskRunCommandRequestMethodEnumApi)[keyof typeof TaskRunCommandRequestMethodEnumApi]

export const TaskRunCommandRequestMethodEnumApi = {
    UserMessage: 'user_message',
    Cancel: 'cancel',
    Close: 'close',
    PermissionResponse: 'permission_response',
    SetConfigOption: 'set_config_option',
    McpResponse: 'mcp_response',
    PiRpc: 'pi/rpc',
    QueueGet: 'queue_get',
    QueueClear: 'queue_clear',
    SideQuestion: 'side_question',
} as const

/**
 * JSON-RPC request to send a command to the agent server in the sandbox.
 */
export interface TaskRunCommandRequestApi {
    /** JSON-RPC version, must be '2.0'
     *
     * * `2.0` - 2.0 */
    jsonrpc: JsonrpcEnumApi
    /** Command method to execute on the agent server
     *
     * * `user_message` - user_message
     * * `cancel` - cancel
     * * `close` - close
     * * `permission_response` - permission_response
     * * `set_config_option` - set_config_option
     * * `mcp_response` - mcp_response
     * * `pi/rpc` - pi/rpc
     * * `queue_get` - queue_get
     * * `queue_clear` - queue_clear
     * * `side_question` - side_question */
    method: TaskRunCommandRequestMethodEnumApi
    /** Parameters for the command */
    params?: TaskRunCommandRequestApiParams
    /** Optional JSON-RPC request ID (string or number) */
    id?: unknown
}

/**
 * Error details on failure
 */
export type TaskRunCommandResponseApiError = { [key: string]: unknown }

/**
 * Response from the agent server command endpoint.
 */
export interface TaskRunCommandResponseApi {
    /** JSON-RPC version */
    jsonrpc: string
    /** Request ID echoed back (string or number) */
    id?: unknown
    /** Command result on success */
    result?: unknown
    /** Error details on failure */
    error?: TaskRunCommandResponseApiError
}

/**
 * Response containing a JWT token for direct sandbox connection
 */
export interface ConnectionTokenResponseApi {
    /** JWT token for authenticating with the sandbox */
    token: string
}

/**
 * One peer agent run visible to the requesting run (agent peer messaging).
 */
export interface TaskRunPeerApi {
    /** The peer run's id — the address send_agent_message targets. */
    run_id: string
    /** Id of the peer run's parent task. */
    task_id: string
    /** Title of the peer run's parent task. */
    task_title: string
    /**
     * Email of the user whose task the peer run belongs to.
     * @nullable
     */
    created_by_email: string | null
    /** Agent runtime of the peer run's task (e.g. 'pi'). */
    runtime: string
    /**
     * Model the peer run was started with, when recorded.
     * @nullable
     */
    model: string | null
    /**
     * Repository the peer run works on, or null for repo-less (channel-mode) runs.
     * @nullable
     */
    repository: string | null
    /**
     * Current stage of the peer run (e.g. 'build').
     * @nullable
     */
    stage: string | null
    /** Run status: 'in_progress' or 'queued' (only these are listed). */
    status: string
    /** Whether the peer accepts messages right now. Only in-progress runs are sendable; a queued run is listed but its workflow may not exist yet. Never infer sendability from status labels. */
    sendable: boolean
    /**
     * ISO-8601 timestamp of the peer run's last update.
     * @nullable
     */
    updated_at: string | null
}

export interface TaskRunPeersResponseApi {
    /** Active agent runs the requesting run may message, most recently updated first. */
    peers: TaskRunPeerApi[]
}

export interface TaskRunPeerMessageRequestApi {
    /**
     * Plain-text message body (max 16000 chars). Delivered to the peer below a server-composed provenance envelope; send short summaries, never raw file dumps — use artifact_ids for files.
     * @maxLength 16000
     */
    content: string
    /**
     * Manifest ids of artifacts on the SENDING run to share (max 10). Each is copied into the target run's own artifact storage; the receiver gets an immutable snapshot.
     * @maxItems 10
     * @items.maxLength 128
     */
    artifact_ids?: string[]
}

/**
 * * `accepted` - accepted
 * * `target_finished` - target_finished
 * * `rejected` - rejected
 */
export type ResultEnumApi = (typeof ResultEnumApi)[keyof typeof ResultEnumApi]

export const ResultEnumApi = {
    Accepted: 'accepted',
    TargetFinished: 'target_finished',
    Rejected: 'rejected',
} as const

export interface TaskRunPeerMessageResponseApi {
    /** Send outcome: 'accepted' (queued for delivery — not a delivery confirmation), 'target_finished' (the peer's workflow is gone), or 'rejected' (throttled or invalid).
     *
     * * `accepted` - accepted
     * * `target_finished` - target_finished
     * * `rejected` - rejected */
    result: ResultEnumApi
    /** Human-readable explanation of the result. */
    detail: string
    /**
     * Id of the recorded peer message, when one was created for this send.
     * @nullable
     */
    message_id?: string | null
}

export interface TaskRunRelayMessageRequestApi {
    /**
     * Joined message body. Used when text_parts is absent.
     * @maxLength 10000
     */
    text: string
    /**
     * Id of the user message this turn answers, when the agent-server echoes it.
     * @maxLength 128
     * @nullable
     */
    message_id?: string | null
    /**
     * Ordered assistant text blocks. When present, the last non-empty entry is posted instead of text.
     * @items.maxLength 10000
     */
    text_parts?: string[]
}

export interface TaskRunRelayMessageResponseApi {
    /** Relay status: 'accepted' or 'skipped' */
    status: string
    /** Relay workflow ID when accepted */
    relay_id?: string
}

export interface PatchedTaskRunSetOutputRequestApi {
    /** Output data from the run. Validated against the task's json_schema if one is set. */
    output?: unknown
}

export interface TaskRunStartRequestApi {
    /** Initial or follow-up user message to include in the run prompt. */
    pending_user_message?: string
    /**
     * Identifiers for run artifacts that should be attached to the next user message delivered to the sandbox.
     * @items.maxLength 128
     */
    pending_user_artifact_ids?: string[]
}

/**
 * Response containing a JWT token (and resolved base URL) for reading a task run's live event stream
 */
export interface StreamReadTokenResponseApi {
    /** Run-scoped JWT the browser presents to the agent-proxy to read this run's live event stream */
    token: string
    /**
     * Base URL of the agent-proxy to read the stream from when routing via the proxy is enabled for this user. Null means read from the Django endpoint directly (same-origin). The client appends the run's stream path and sends the token as a Bearer header when this is set.
     * @nullable
     */
    stream_base_url: string | null
}

export interface TaskSessionResponseApi {
    /** Task session identifier */
    id: string
    /**
     * Temporary URL for downloading the session
     * @nullable
     */
    download_url: string | null
    /**
     * SHA-256 digest of the current session content
     * @nullable
     */
    content_sha256: string | null
}

export interface TaskSessionSyncResponseApi {
    /** Task session identifier */
    id: string
    /** SHA-256 digest of the uploaded session content */
    content_sha256: string
}

/**
 * * `slack_message` - slack_message
 * * `slack_canvas` - slack_canvas
 * * `document` - document
 * * `spreadsheet` - spreadsheet
 * * `dashboard` - dashboard
 * * `file` - file
 * * `github_pr` - github_pr
 */
export type ArtifactTypeEnumApi = (typeof ArtifactTypeEnumApi)[keyof typeof ArtifactTypeEnumApi]

export const ArtifactTypeEnumApi = {
    SlackMessage: 'slack_message',
    SlackCanvas: 'slack_canvas',
    Document: 'document',
    Spreadsheet: 'spreadsheet',
    Dashboard: 'dashboard',
    File: 'file',
    GithubPr: 'github_pr',
} as const

/**
 * * `slack_message` - slack_message
 * * `slack_canvas` - slack_canvas
 * * `slack_file` - slack_file
 * * `document_connector` - document_connector
 * * `github_pr` - github_pr
 */
export type AdapterEnumApi = (typeof AdapterEnumApi)[keyof typeof AdapterEnumApi]

export const AdapterEnumApi = {
    SlackMessage: 'slack_message',
    SlackCanvas: 'slack_canvas',
    SlackFile: 'slack_file',
    DocumentConnector: 'document_connector',
    GithubPr: 'github_pr',
} as const

/**
 * * `active` - active
 * * `failed` - failed
 */
export type TaskArtifactStatusEnumApi = (typeof TaskArtifactStatusEnumApi)[keyof typeof TaskArtifactStatusEnumApi]

export const TaskArtifactStatusEnumApi = {
    Active: 'active',
    Failed: 'failed',
} as const

export type TaskRunLivingArtifactResponseApiVersionsItem = { [key: string]: unknown }

export interface TaskRunLivingArtifactResponseApi {
    /** Stable living artifact id. Use this id when editing the artifact. */
    id: string
    /** Task id this living artifact belongs to. */
    task_id: string
    /** Task run id that created or currently owns this artifact. */
    run_id: string
    /** Project id that owns this artifact. */
    team_id: number
    /** Human-readable artifact name. */
    name: string
    /** Artifact format or delivery surface, such as document, spreadsheet, slack_canvas, file, or slack_message.
     *
     * * `slack_message` - slack_message
     * * `slack_canvas` - slack_canvas
     * * `document` - document
     * * `spreadsheet` - spreadsheet
     * * `dashboard` - dashboard
     * * `file` - file
     * * `github_pr` - github_pr */
    artifact_type: ArtifactTypeEnumApi
    /** Adapter that currently stores or edits the artifact.
     *
     * * `slack_message` - slack_message
     * * `slack_canvas` - slack_canvas
     * * `slack_file` - slack_file
     * * `document_connector` - document_connector
     * * `github_pr` - github_pr */
    adapter: AdapterEnumApi
    /** Current registry status for the artifact.
     *
     * * `active` - active
     * * `failed` - failed */
    status: TaskArtifactStatusEnumApi
    /** Adapter-specific location, such as S3 key or Slack canvas id. */
    location: unknown
    /** Adapter-specific metadata for external storage and source tracking. */
    metadata: unknown
    /** Current version number for the artifact. */
    current_version: number
    /** Chronological version records for this artifact. */
    versions: TaskRunLivingArtifactResponseApiVersionsItem[]
    /**
     * ISO timestamp when created.
     * @nullable
     */
    created_at?: string | null
    /**
     * ISO timestamp when last updated.
     * @nullable
     */
    updated_at?: string | null
}

export interface TaskRunLivingArtifactsResponseApi {
    /** Living artifacts for this task run. */
    artifacts: TaskRunLivingArtifactResponseApi[]
}

/**
 * Optional metadata to persist with the living artifact.
 */
export type TaskRunLivingArtifactCreateRequestApiMetadata = { [key: string]: unknown }

export interface TaskRunLivingArtifactCreateRequestApi {
    /**
     * Human-readable artifact name, used as the title.
     * @maxLength 255
     */
    name: string
    /** Artifact format or delivery surface to create, such as document, spreadsheet, slack_canvas, or file.
     *
     * * `slack_message` - slack_message
     * * `slack_canvas` - slack_canvas
     * * `document` - document
     * * `spreadsheet` - spreadsheet
     * * `dashboard` - dashboard
     * * `file` - file
     * * `github_pr` - github_pr */
    artifact_type?: ArtifactTypeEnumApi
    /** Optional preferred external storage or delivery adapter. Slack adapters deliver into the mapped Slack thread; omitted Slack-run documents use Slack canvas, omitted Slack-run files and spreadsheets use Slack file upload, and document_connector uses a connected external document provider.
     *
     * * `slack_message` - slack_message
     * * `slack_canvas` - slack_canvas
     * * `slack_file` - slack_file
     * * `document_connector` - document_connector
     * * `github_pr` - github_pr */
    adapter?: AdapterEnumApi
    /**
     * Markdown or text content for the initial artifact version.
     * @maxLength 500000
     */
    content?: string
    /** Base64-encoded binary content for Slack file uploads or other external adapters. Prefer source_artifact_id or source_storage_path for large files that were already uploaded as run output artifacts. */
    content_base64?: string
    /**
     * MIME type for content_base64 or source-backed artifacts, such as application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.
     * @maxLength 255
     */
    content_type?: string
    /** Existing run artifact id to use as the initial content source. Only agent-uploaded output artifacts are accepted; internal run artifacts are rejected. */
    source_artifact_id?: string
    /** Existing run artifact storage_path to use as the initial content source. Only agent-uploaded output artifacts are accepted; internal run artifacts are rejected. */
    source_storage_path?: string
    /** Optional metadata to persist with the living artifact. */
    metadata?: TaskRunLivingArtifactCreateRequestApiMetadata
}

export type TaskRunLivingArtifactOpenResponseApiVersionsItem = { [key: string]: unknown }

export interface TaskRunLivingArtifactOpenResponseApi {
    /** Stable living artifact id. Use this id when editing the artifact. */
    id: string
    /** Task id this living artifact belongs to. */
    task_id: string
    /** Task run id that created or currently owns this artifact. */
    run_id: string
    /** Project id that owns this artifact. */
    team_id: number
    /** Human-readable artifact name. */
    name: string
    /** Artifact format or delivery surface, such as document, spreadsheet, slack_canvas, file, or slack_message.
     *
     * * `slack_message` - slack_message
     * * `slack_canvas` - slack_canvas
     * * `document` - document
     * * `spreadsheet` - spreadsheet
     * * `dashboard` - dashboard
     * * `file` - file
     * * `github_pr` - github_pr */
    artifact_type: ArtifactTypeEnumApi
    /** Adapter that currently stores or edits the artifact.
     *
     * * `slack_message` - slack_message
     * * `slack_canvas` - slack_canvas
     * * `slack_file` - slack_file
     * * `document_connector` - document_connector
     * * `github_pr` - github_pr */
    adapter: AdapterEnumApi
    /** Current registry status for the artifact.
     *
     * * `active` - active
     * * `failed` - failed */
    status: TaskArtifactStatusEnumApi
    /** Adapter-specific location, such as S3 key or Slack canvas id. */
    location: unknown
    /** Adapter-specific metadata for external storage and source tracking. */
    metadata: unknown
    /** Current version number for the artifact. */
    current_version: number
    /** Chronological version records for this artifact. */
    versions: TaskRunLivingArtifactOpenResponseApiVersionsItem[]
    /**
     * ISO timestamp when created.
     * @nullable
     */
    created_at?: string | null
    /**
     * ISO timestamp when last updated.
     * @nullable
     */
    updated_at?: string | null
    /**
     * Current artifact content when the adapter can read it directly.
     * @nullable
     */
    content?: string | null
}

/**
 * Optional metadata to merge into the artifact registry record.
 */
export type TaskRunLivingArtifactEditRequestApiMetadata = { [key: string]: unknown }

export interface TaskRunLivingArtifactEditRequestApi {
    /**
     * Optional new human-readable artifact name.
     * @maxLength 255
     */
    name?: string
    /**
     * Markdown or text content for the next version.
     * @maxLength 500000
     */
    content?: string
    /** Base64-encoded binary content for the next version, used by adapters such as slack_file. */
    content_base64?: string
    /**
     * MIME type for content_base64 or source-backed edits.
     * @maxLength 255
     */
    content_type?: string
    /** Existing run artifact id to use as the next version content source. Only agent-uploaded output artifacts are accepted; internal run artifacts are rejected. */
    source_artifact_id?: string
    /** Existing run artifact storage_path to use as the next version content source. Only agent-uploaded output artifacts are accepted; internal run artifacts are rejected. */
    source_storage_path?: string
    /** Optional metadata to merge into the artifact registry record. */
    metadata?: TaskRunLivingArtifactEditRequestApiMetadata
}

/**
 * Insight query JSON to render ad hoc, e.g. {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", ...}}. SQL queries (DataVisualizationNode, HogQLQuery) are not supported yet. Provide exactly one of query or insight_id.
 */
export type TaskRunLivingArtifactChartRequestApiQuery = { [key: string]: unknown }

export interface TaskRunLivingArtifactChartRequestApi {
    /**
     * Chart title, also used as the delivered file name.
     * @maxLength 255
     */
    name: string
    /** Insight query JSON to render ad hoc, e.g. {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", ...}}. SQL queries (DataVisualizationNode, HogQLQuery) are not supported yet. Provide exactly one of query or insight_id. */
    query?: TaskRunLivingArtifactChartRequestApiQuery
    /** Numeric id of a saved insight to render. Provide exactly one of query or insight_id. */
    insight_id?: number
}

export interface TaskRunLivingArtifactChartResponseApi {
    /** The living artifact registered for delivery. */
    artifact: TaskRunLivingArtifactResponseApi
    /** Id of the rendered PNG export backing the chart. */
    export_asset_id: number
    /**
     * Link to explore this chart interactively in PostHog.
     * @nullable
     */
    url?: string | null
}

export type TaskThreadMessageDTOApiPayload = { [key: string]: unknown }

/**
 * Response shape for one message in a task's thread.
 */
export interface TaskThreadMessageDTOApi {
    id: string
    task: string
    author_kind: string
    event: string
    payload: TaskThreadMessageDTOApiPayload
    content: string
    created_at: string
    author?: TaskUserBasicInfoApi | null
    /** @nullable */
    forwarded_to_agent_at?: string | null
    forwarded_by?: TaskUserBasicInfoApi | null
}

export interface PaginatedTaskThreadMessageDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskThreadMessageDTOApi[]
}

/**
 * Request body for posting a thread message.
 */
export interface TaskThreadMessageWriteApi {
    /** Message text. */
    content: string
}

/**
 * The team's active onboarding wizard cloud run, used to rehydrate
 * the setup-progress FAB when the run was started server-side (drop flow).
 */
export interface WizardCloudRunDTOApi {
    /** Id of the onboarding wizard task. */
    task_id: string
    /** Id of the task's latest run, for reconnecting to its progress stream. */
    run_id: string
    /** Latest run status (e.g. queued, in_progress, completed, failed). */
    status: string
    /**
     * When the run was created, for the FAB's elapsed timer.
     * @nullable
     */
    started_at?: string | null
}

/**
 * One model a run may use. Reads a `ModelChoice` straight off the catalogue facade.
 *
 * Both enums are declared with the same choices the run-detail response uses, so clients get the
 * generated adapter/effort types here rather than bare strings.
 */
export interface ModelChoiceApi {
    /** Runtime that drives this model, such as 'claude' or 'codex'.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter: RuntimeAdapterEnumApi
    model: string
    /** Display name for the model, such as 'Claude Opus 4.8'. */
    display_name: string
    /** Reasoning efforts this model accepts, in ascending order. Empty for a model with no effort control. */
    supported_efforts: ReasoningEffortEnumApi[]
}

export interface ModelCatalogueResponseApi {
    /** Every model a run may use, newest catalogue from the LLM gateway. Empty when the gateway is unreachable. */
    models: ModelChoiceApi[]
}

export interface PinnedTaskIdsResponseApi {
    /** Visible task IDs pinned by the requester, newest pin first. */
    task_ids: string[]
}

export interface TaskRepositoriesResponseApi {
    /** Distinct repositories in use by non-deleted, non-internal tasks for the current team. */
    repositories: string[]
}

/**
 * * `needs_setup` - needs_setup
 * * `detected` - detected
 * * `waiting_for_data` - waiting_for_data
 * * `ready` - ready
 * * `not_applicable` - not_applicable
 * * `unknown` - unknown
 */
export type CapabilityStateStateEnumApi = (typeof CapabilityStateStateEnumApi)[keyof typeof CapabilityStateStateEnumApi]

export const CapabilityStateStateEnumApi = {
    NeedsSetup: 'needs_setup',
    Detected: 'detected',
    WaitingForData: 'waiting_for_data',
    Ready: 'ready',
    NotApplicable: 'not_applicable',
    Unknown: 'unknown',
} as const

/**
 * Supporting evidence
 */
export type CapabilityStateApiEvidence = { [key: string]: unknown }

export interface CapabilityStateApi {
    /** Current state of the capability
     *
     * * `needs_setup` - needs_setup
     * * `detected` - detected
     * * `waiting_for_data` - waiting_for_data
     * * `ready` - ready
     * * `not_applicable` - not_applicable
     * * `unknown` - unknown */
    state: CapabilityStateStateEnumApi
    /** Whether the state is estimated from static analysis */
    estimated: boolean
    /** Human-readable explanation */
    reason: string
    /** Supporting evidence */
    evidence?: CapabilityStateApiEvidence
}

export interface ScanEvidenceApi {
    /** Number of files scanned */
    filesScanned: number
    /** Total candidate files detected */
    detectedFilesCount: number
    /** Number of distinct event names found */
    eventNameCount: number
    /** Whether posthog.init() was found in scanned files */
    foundPosthogInit: boolean
    /** Whether posthog.capture() was found in scanned files */
    foundPosthogCapture: boolean
    /** Whether error tracking signals were found in scanned files */
    foundErrorSignal: boolean
}

export interface RepositoryReadinessResponseApi {
    /** Normalized repository identifier */
    repository: string
    /** Repository classification */
    classification: string
    /** Whether the repository is excluded from readiness checks */
    excluded: boolean
    /** Tracking capability state */
    coreSuggestions: CapabilityStateApi
    /** Computer vision capability state */
    replayInsights: CapabilityStateApi
    /** Error tracking capability state */
    errorInsights: CapabilityStateApi
    /** Overall readiness state */
    overall: string
    /** Count of replay-derived evidence tasks */
    evidenceTaskCount: number
    /** Lookback window in days */
    windowDays: number
    /** ISO timestamp when the response was generated */
    generatedAt: string
    /** Age of cached response in seconds */
    cacheAgeSeconds: number
    /** Scan evidence details */
    scan?: ScanEvidenceApi
}

/**
 * * `task` - task
 * * `pull_request` - pull_request
 * * `artifact` - artifact
 * * `channel` - channel
 */
export type TaskSearchResultKindEnumApi = (typeof TaskSearchResultKindEnumApi)[keyof typeof TaskSearchResultKindEnumApi]

export const TaskSearchResultKindEnumApi = {
    Task: 'task',
    PullRequest: 'pull_request',
    Artifact: 'artifact',
    Channel: 'channel',
} as const

export interface TaskSearchResultApi {
    /** Search document identifier. */
    id: string
    /** Type of matched resource.
     *
     * * `task` - task
     * * `pull_request` - pull_request
     * * `artifact` - artifact
     * * `channel` - channel */
    kind: TaskSearchResultKindEnumApi
    /** Primary result label. */
    title: string
    /** Secondary result context. */
    subtitle: string
    /**
     * Containing task identifier, when applicable.
     * @nullable
     */
    task_id: string | null
    /**
     * Containing task run identifier, when applicable.
     * @nullable
     */
    task_run_id: string | null
    /**
     * Containing space identifier, when applicable.
     * @nullable
     */
    channel_id: string | null
    /** Resource-specific navigation metadata. */
    metadata: unknown
}

/**
 * Slack-side identifiers and the mapping metadata for a thread → task lookup.
 */
export interface SlackThreadContextThreadApi {
    /** Echoed input URL. */
    url: string
    /** Slack channel id parsed from the URL (e.g. C0ACRAMJUAG). */
    channel: string
    /** Slack thread_ts (e.g. 1779956938.619299). */
    thread_ts: string
    /**
     * Slack workspace id (e.g. T…). Null when no mapping exists yet.
     * @nullable
     */
    slack_workspace_id: string | null
    /**
     * The Slack user who triggered the task. Null when no mapping exists yet.
     * @nullable
     */
    mentioning_slack_user_id: string | null
}

/**
 * The PostHog Task linked to the Slack thread.
 */
export interface SlackThreadContextTaskApi {
    /** UUID of the Task row. */
    id: string
    /** Team that owns the task. */
    team_id: number
    /** Task title (typically the first ~255 chars of the Slack ask). */
    title: string
    /**
     * Resolved repository in `org/repo` form, or null if the run started without a repo.
     * @nullable
     */
    repository: string | null
    /** `Task.OriginProduct` (`slack` for slack-originated tasks). */
    origin_product: string
    /** When the task was created (server-side timestamp). */
    created_at: string
    /** Absolute URL to the task detail page in the PostHog app. */
    url: string
}

/**
 * The internal sandbox run the discovery agent used to pick this run's repo.
 *
 * Only present when the originating mention was ambiguous (multiple candidate
 * repos, no explicit mention) — that's the only path that spins up a research
 * sandbox. Null otherwise.
 */
export interface SlackThreadContextRepoResearchApi {
    /** UUID of the internal repo-research Task. */
    task_id: string
    /** UUID of the internal repo-research TaskRun. */
    run_id: string
    /**
     * Research run status, or null if the run row could not be loaded.
     * @nullable
     */
    status: string | null
    /** Temporal workflow id for the research sandbox run (`task-processing-<task_id>-<run_id>`, or a caller-prefixed variant). */
    task_processing_workflow_id: string
    /**
     * Full Temporal Web UI URL for the research workflow; null when `TEMPORAL_UI_HOST` is unset.
     * @nullable
     */
    task_processing_workflow_url: string | null
    /**
     * Live sandbox tunnel URL for the research run, when one was attached.
     * @nullable
     */
    sandbox_url: string | null
    /** Absolute URL to the research task detail page (carries `?ph_debug=true`). */
    task_view_url: string
    /**
     * Presigned S3 URL for the research run's JSONL log transcript (valid ~1 hour).
     * @nullable
     */
    log_url: string | null
}

/**
 * One TaskRun and its associated Temporal workflow handles.
 */
export interface SlackThreadContextRunApi {
    /** UUID of the TaskRun row. */
    id: string
    /** Run status (queued/in_progress/completed/failed/…). */
    status: string
    /** When the run was created. */
    created_at: string
    /**
     * When the run reached a terminal state, or null while still running.
     * @nullable
     */
    completed_at: string | null
    /**
     * Live sandbox tunnel URL, when one was attached.
     * @nullable
     */
    sandbox_url: string | null
    /**
     * PR URL produced by the run, when one was opened.
     * @nullable
     */
    pr_url: string | null
    /**
     * Error captured on terminal failure, or null on success.
     * @nullable
     */
    error_message: string | null
    /** Temporal workflow id for the sandbox/agent run (`task-processing-<task_id>-<run_id>`, or a caller-prefixed variant). */
    task_processing_workflow_id: string
    /**
     * Full Temporal Web UI URL for the task-processing workflow; null when `TEMPORAL_UI_HOST` is unset.
     * @nullable
     */
    task_processing_workflow_url: string | null
    /**
     * Temporal workflow id of the Slack mention that dispatched this run (`posthog-code-mention-<workspace>:<event_id_or_channel:ts>`). Null for runs created before this field was persisted.
     * @nullable
     */
    mention_workflow_id: string | null
    /**
     * Full Temporal Web UI URL for the mention dispatch workflow; null when unavailable.
     * @nullable
     */
    mention_workflow_url: string | null
    /** Absolute URL to the task detail page focused on this run. */
    task_view_url: string
    /**
     * Presigned S3 URL for the run's full JSONL log transcript (valid ~1 hour).
     * @nullable
     */
    log_url: string | null
    /** The discovery-agent sandbox that picked this run's repo, when the mention was ambiguous. */
    repo_research: SlackThreadContextRepoResearchApi | null
}

/**
 * Top-level response for the slack-thread debug endpoint.
 */
export interface SlackThreadContextResponseApi {
    /** Slack-side identifiers and the mapping metadata. */
    thread: SlackThreadContextThreadApi
    /** Linked PostHog Task. Null when no mapping was found for the thread. */
    task: SlackThreadContextTaskApi | null
    /** All runs on the task, oldest first. Empty when no mapping was found. */
    runs: SlackThreadContextRunApi[]
}

export interface TaskSummariesRequestApi {
    /**
     * Task IDs to fetch summaries for (max 5000). Response is paginated; follow the `next` cursor to retrieve all results.
     * @maxItems 5000
     */
    ids: string[]
}

/**
 * * `not_started` - Not Started
 * * `queued` - Queued
 * * `in_progress` - In Progress
 * * `completed` - Completed
 * * `failed` - Failed
 * * `cancelled` - Cancelled
 */
export type TaskRunStatusEnumApi = (typeof TaskRunStatusEnumApi)[keyof typeof TaskRunStatusEnumApi]

export const TaskRunStatusEnumApi = {
    NotStarted: 'not_started',
    Queued: 'queued',
    InProgress: 'in_progress',
    Completed: 'completed',
    Failed: 'failed',
    Cancelled: 'cancelled',
} as const

/**
 * * `local` - Local
 * * `cloud` - Cloud
 */
export type TaskRunEnvironmentEnumApi = (typeof TaskRunEnvironmentEnumApi)[keyof typeof TaskRunEnvironmentEnumApi]

export const TaskRunEnvironmentEnumApi = {
    Local: 'local',
    Cloud: 'cloud',
} as const

export interface TaskRunSummaryApi {
    status: TaskRunStatusEnumApi | null
    environment: TaskRunEnvironmentEnumApi | null
}

/**
 * Summary response for a task — reads from a frozen ``TaskSummaryDTO``.
 */
export interface TaskSummaryDTOApi {
    id: string
    title: string
    /** @nullable */
    repository: string | null
    created_at: string
    updated_at: string
    origin_product?: string
    latest_run?: TaskRunSummaryApi | null
}

export interface PaginatedTaskSummaryDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TaskSummaryDTOApi[]
}

/**
 * * `user_created` - user_created
 * * `posthog_ai` - posthog_ai
 */
export type WarmTaskRequestOriginProductEnumApi =
    (typeof WarmTaskRequestOriginProductEnumApi)[keyof typeof WarmTaskRequestOriginProductEnumApi]

export const WarmTaskRequestOriginProductEnumApi = {
    UserCreated: 'user_created',
    PosthogAi: 'posthog_ai',
} as const

/**
 * Request body for warming a full idling Run while composing a Code-app cloud task.
 *
 * Collection-level: no task exists yet at typing time. The warmer births a draft Task and an
 * interactive Run that boots and starts the agent, optionally cloning and checking out a repository,
 * then idles awaiting the first message. `github_integration` is a plain integration PK (an integer);
 * the view re-scopes it to the caller's team before use.
 */
export interface WarmTaskRequestApi {
    /**
     * Optional GitHub repository to clone, in `organization/repo` format (e.g. `posthog/posthog`).
     * @maxLength 255
     * @nullable
     */
    repository?: string | null
    /**
     * GitHub repositories to clone into the warm sandbox, each in `organization/repo` format.
     * @maxItems 3
     * @items.maxLength 255
     */
    repositories?: string[]
    /**
     * Primary key of the team's GitHub integration to clone with when a repository is selected.
     * @nullable
     */
    github_integration?: number | null
    /**
     * Branch to check out in the warm sandbox. Defaults to the repository's default branch when omitted.
     * @maxLength 255
     * @nullable
     */
    branch?: string | null
    /** Agent runtime adapter to warm the sandbox on ('claude' or 'codex'). The warm Run starts the agent on this runtime so a matching submit reuses it; a submit selecting a different runtime falls through to a cold Run instead of reusing a mismatched warm session.
     *
     * * `claude` - claude
     * * `codex` - codex */
    runtime_adapter?: RuntimeAdapterEnumApi | null
    /**
     * LLM model identifier to warm the sandbox on. A submit selecting a different model won't reuse this warm Run.
     * @nullable
     */
    model?: string | null
    /** Reasoning effort to warm the sandbox on for models that expose an effort control.
     *
     * * `low` - low
     * * `medium` - medium
     * * `high` - high
     * * `xhigh` - xhigh
     * * `max` - max
     * * `ultracode` - ultracode */
    reasoning_effort?: ReasoningEffortEnumApi | null
    /**
     * Optional sandbox environment to provision before the task is submitted.
     * @nullable
     */
    sandbox_environment_id?: string | null
    /**
     * Optional custom base image to provision before the task is submitted; takes precedence over the environment's image.
     * @nullable
     */
    custom_image_id?: string | null
    /** Product the warm Run is for. Fixed when the sandbox boots — it selects the OAuth app, the quota gate, the warm-pool budget, and PR authorship — so a submit only reuses a warm born under the same origin. Defaults to the Code app.
     *
     * * `user_created` - user_created
     * * `posthog_ai` - posthog_ai */
    origin_product?: WarmTaskRequestOriginProductEnumApi
    /** Permission mode to boot the agent session on. Read at session construction, so it cannot be changed once the sandbox is warm — a submit selecting a different mode falls through to a cold Run. Omit to take the runtime's default.
     *
     * * `default` - default
     * * `acceptEdits` - acceptEdits
     * * `plan` - plan
     * * `bypassPermissions` - bypassPermissions
     * * `auto` - auto
     * * `read-only` - read-only
     * * `full-access` - full-access */
    initial_permission_mode?: TaskRunBootstrapCreateRequestInitialPermissionModeEnumApi | null
}

/**
 * Response for a successful warm request — the draft Task + idling warm Run reused on submit.
 */
export interface WarmTaskResponseApi {
    /** Id of the draft Task birthed for the warm Run. */
    task_id: string
    /** Id of the idling warm Run. The normal create+run path reuses and activates it on submit. */
    run_id: string
}

export type LoopsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type LoopsRunsRetrieveParams = {
    /**
     * Opaque pagination cursor from a previous response's `next_cursor`.
     * @minLength 1
     */
    cursor?: string
    /**
     * Max results per page (default 50, max 100).
     * @minimum 1
     * @maximum 100
     */
    limit?: number
}

export type LoopsTriggerCreateBodyOne = { [key: string]: unknown }

export type LoopsTriggerCreateBodyTwo = { [key: string]: unknown }

export type LoopsTriggerCreateBodyThree = { [key: string]: unknown }

export type SandboxCustomImagesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type SandboxListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type TaskActivityListParams = {
    /**
     * Activity timestamp from the final row of the previous page.
     */
    before?: string
    /**
     * Activity ID from the final row of the previous page.
     */
    before_id?: string
    /**
     * Maximum number of tasks to return (most recent activity first).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
}

export type TaskChannelsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type TaskChannelsFeedListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type TaskMentionsListParams = {
    /**
     * Maximum number of mentions to return (newest first).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Only return mentions created after this ISO 8601 timestamp.
     */
    since?: string
}

export type TasksListParams = {
    /**
     * Local development only. With ph_debug=true, list all project tasks for debugging. Ignored outside local development.
     */
    all_team_tasks?: boolean
    /**
     * Filter by archived state. Defaults to excluding archived tasks. Use 'true' to list only archived tasks, 'false' for the default, or 'all' to include both.
     *
     * * `true` - true
     * * `false` - false
     * * `all` - all
     * @minLength 1
     */
    archived?: TasksListArchived
    /**
     * Filter tasks to a channel's feed.
     */
    channel?: string
    /**
     * Filter tasks by the CI check rollup on their most recent run's pull request, as last observed from GitHub. 'none' means the PR has no checks.
     *
     * * `passing` - passing
     * * `failing` - failing
     * * `pending` - pending
     * * `none` - none
     * @minLength 1
     */
    ci_status?: TasksListCiStatus
    /**
     * Filter to tasks carrying a thread comment written by this user ID.
     */
    commented_by?: number
    /**
     * Filter by creator user ID
     */
    created_by?: number
    /**
     * Exclude tasks with this origin product from the results
     *
     * * `onboarding` - Onboarding
     * * `error_tracking` - Error Tracking
     * * `eval_clusters` - Eval Clusters
     * * `user_created` - User Created
     * * `slack` - Slack
     * * `support_queue` - Support Queue
     * * `session_summaries` - Session Summaries
     * * `posthog_ai` - PostHog AI
     * * `experiments` - Experiments
     * * `signal_report` - Signal Report
     * * `signals_scout` - Signals Scout
     * * `support_reply` - Support Reply
     * * `hogdesk` - HogDesk
     * * `review_hog` - ReviewHog
     * * `image_builder` - Image Builder
     * * `loop` - Loop
     * * `mcp_analytics` - MCP Analytics
     * * `signals_chat` - Signals Chat
     * * `task_analysis` - Task Analysis
     * * `workflow` - Workflow
     * @minLength 1
     */
    exclude_origin_product?: TasksListExcludeOriginProduct
    /**
     * Filter by the internal flag, which controls whether a task is shown by default, not whether it is accessible. Defaults to excluding internal tasks. Use 'all' to include both internal and user-facing tasks, or 'true' to list only internal tasks. All values are available to any team member; access stays governed by task visibility.
     *
     * * `true` - true
     * * `false` - false
     * * `all` - all
     * @minLength 1
     */
    internal?: TasksListInternal
    /**
     * Number of results to return per page.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Filter to tasks whose thread mentions this user ID.
     */
    mentions?: number
    /**
     * The initial index from which to return the results.
     * @minimum 0
     */
    offset?: number
    /**
     * Sort order. '-last_activity_at' is newest activity first, where activity means a thread message or a run starting, streaming, or finishing. Defaults to '-created_at'.
     *
     * * `-created_at` - -created_at
     * * `-last_activity_at` - -last_activity_at
     * @minLength 1
     */
    ordering?: TasksListOrdering
    /**
     * Filter by repository organization
     * @minLength 1
     */
    organization?: string
    /**
     * Filter by origin product
     * @minLength 1
     */
    origin_product?: string
    /**
     * With true, only tasks the requesting user has pinned.
     */
    pinned?: boolean
    /**
     * Filter tasks by the state of their most recent run's pull request, as last observed from GitHub (webhooks plus the CI follow-up snapshot).
     *
     * * `open` - open
     * * `draft` - draft
     * * `merged` - merged
     * * `closed` - closed
     * @minLength 1
     */
    pr_state?: TasksListPrState
    /**
     * Filter by repository name (can include org/repo format)
     * @minLength 1
     */
    repository?: string
    /**
     * Case-insensitive substring search over task title and description. A numeric value also matches the task number. An empty value disables the filter.
     */
    search?: string
    /**
     * Filter by task run stage
     * @minLength 1
     */
    stage?: string
    /**
     * Filter tasks by the status of their most recent run.
     *
     * * `not_started` - not_started
     * * `queued` - queued
     * * `in_progress` - in_progress
     * * `completed` - completed
     * * `failed` - failed
     * * `cancelled` - cancelled
     * @minLength 1
     */
    status?: TasksListStatus
}

export type TasksListArchived = (typeof TasksListArchived)[keyof typeof TasksListArchived]

export const TasksListArchived = {
    True: 'true',
    False: 'false',
    All: 'all',
} as const

export type TasksListCiStatus = (typeof TasksListCiStatus)[keyof typeof TasksListCiStatus]

export const TasksListCiStatus = {
    Passing: 'passing',
    Failing: 'failing',
    Pending: 'pending',
    None: 'none',
} as const

export type TasksListExcludeOriginProduct =
    (typeof TasksListExcludeOriginProduct)[keyof typeof TasksListExcludeOriginProduct]

export const TasksListExcludeOriginProduct = {
    Onboarding: 'onboarding',
    ErrorTracking: 'error_tracking',
    EvalClusters: 'eval_clusters',
    UserCreated: 'user_created',
    Slack: 'slack',
    SupportQueue: 'support_queue',
    SessionSummaries: 'session_summaries',
    PosthogAi: 'posthog_ai',
    Experiments: 'experiments',
    SignalReport: 'signal_report',
    SignalsScout: 'signals_scout',
    SupportReply: 'support_reply',
    Hogdesk: 'hogdesk',
    ReviewHog: 'review_hog',
    ImageBuilder: 'image_builder',
    Loop: 'loop',
    McpAnalytics: 'mcp_analytics',
    SignalsChat: 'signals_chat',
    TaskAnalysis: 'task_analysis',
    Workflow: 'workflow',
} as const

export type TasksListInternal = (typeof TasksListInternal)[keyof typeof TasksListInternal]

export const TasksListInternal = {
    True: 'true',
    False: 'false',
    All: 'all',
} as const

export type TasksListOrdering = (typeof TasksListOrdering)[keyof typeof TasksListOrdering]

export const TasksListOrdering = {
    CreatedAt: '-created_at',
    LastActivityAt: '-last_activity_at',
} as const

export type TasksListPrState = (typeof TasksListPrState)[keyof typeof TasksListPrState]

export const TasksListPrState = {
    Open: 'open',
    Draft: 'draft',
    Merged: 'merged',
    Closed: 'closed',
} as const

export type TasksListStatus = (typeof TasksListStatus)[keyof typeof TasksListStatus]

export const TasksListStatus = {
    NotStarted: 'not_started',
    Queued: 'queued',
    InProgress: 'in_progress',
    Completed: 'completed',
    Failed: 'failed',
    Cancelled: 'cancelled',
} as const

export type TasksCommentsListParams = {
    /**
     * Artifact id returned by the artifacts endpoint.
     * @minLength 1
     * @maxLength 72
     */
    artifact_id?: string
    /**
     * Opaque cursor returned by the previous page.
     * @minLength 1
     * @maxLength 256
     */
    cursor?: string
    /**
     * Whether to include resolved comment threads.
     */
    include_resolved?: boolean
    /**
     * Maximum number of root comments to return.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
}

export type TasksCommentsRetrieveParams = {
    /**
     * Comment id whose truncated body should continue. Use with content_offset.
     */
    comment_id?: string
    /**
     * Byte offset returned as content_next_offset for the selected comment.
     * @minimum 0
     */
    content_offset?: number
    /**
     * Opaque cursor returned by the previous page.
     * @minLength 1
     * @maxLength 256
     */
    cursor?: string
    /**
     * Maximum number of comments in the thread to return.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
}

export type TasksRunsListParams = {
    /**
     * Number of results to return per page.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     * @minimum 0
     */
    offset?: number
}

export type TasksRunsSessionLogsRetrieveParams = {
    /**
     * Only return events after this ISO8601 timestamp
     */
    after?: string
    /**
     * Comma-separated list of event types to include
     * @minLength 1
     */
    event_types?: string
    /**
     * Comma-separated list of event types to exclude
     * @minLength 1
     */
    exclude_types?: string
    /**
     * Maximum number of entries to return (default 1000, max 5000)
     * @minimum 1
     * @maximum 5000
     */
    limit?: number
    /**
     * Zero-based offset into the filtered log entries
     * @minimum 0
     */
    offset?: number
}

export type TasksRunsStreamRetrieveParams = {
    /**
     * Set to `latest` to skip the event backlog and only receive events published after connecting.
     */
    start?: string
}

export type TasksThreadMessagesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type TasksRepositoryReadinessRetrieveParams = {
    refresh?: boolean
    /**
     * Repository in org/repo format
     * @minLength 1
     */
    repository: string
    /**
     * @minimum 1
     * @maximum 30
     */
    window_days?: number
}

export type TasksSearchRetrieveParams = {
    /**
     * Maximum number of results to return.
     * @minimum 1
     * @maximum 50
     */
    limit?: number
    /**
     * Text or exact identifier to search for.
     * @minLength 1
     * @maxLength 512
     */
    q: string
}

export type TasksSlackThreadContextRetrieveParams = {
    /**
     * Full Slack permalink to any message in the thread (e.g. https://posthog.slack.com/archives/C…/p1779956938619299). Replies inside the thread are accepted too — the `thread_ts` query param (when present) takes precedence over the in-path message ts.
     * @minLength 1
     */
    url: string
}

export type TasksSummariesCreateParams = {
    /**
     * Page size for the paginated response.
     */
    limit?: number
    /**
     * Offset into the result set for pagination.
     */
    offset?: number
}
