/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `client` - Client
 * * `none` - None
 */
export type AgentOperationApprovalsEnumApi =
    (typeof AgentOperationApprovalsEnumApi)[keyof typeof AgentOperationApprovalsEnumApi]

export const AgentOperationApprovalsEnumApi = {
    Client: 'client',
    None: 'none',
} as const

export interface AgentOperationStartApi {
    /**
     * The product goal for PostHog AI, written as a complete request. For example: 'Why did signups drop last week?'
     * @maxLength 4096
     */
    goal: string
    /**
     * A unique id that the client makes for this request. Send the same id again to recover a lost response. A new goal needs a new id.
     * @maxLength 128
     */
    client_request_id: string
    /**
     * Optional facts from the client, such as the feature under work or relevant file names. PostHog AI treats it as data, not as instructions.
     * @maxLength 4096
     */
    context?: string
    /** Continue the conversation of an earlier operation, so PostHog AI keeps its context. */
    conversation_id?: string
    /**
     * Optional GitHub repository in 'organization/repository' form, for PostHog AI to read. The repository is read-only.
     * @maxLength 255
     * @pattern ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$
     */
    repository?: string
    /** 'client' when the client can show approval prompts to its user, so PostHog AI asks before each sensitive tool call. 'none' (default) runs with no prompts; the key's scopes still limit the run.
     *
     * * `client` - Client
     * * `none` - None */
    approvals?: AgentOperationApprovalsEnumApi
    /**
     * Optional branch, tag, or commit in the repository. The default branch when not set. The server pins it to one commit.
     * @maxLength 255
     */
    ref?: string
}

/**
 * * `queued` - Queued
 * * `running` - Running
 * * `needs_input` - Needs input
 * * `cancelling` - Cancelling
 * * `succeeded` - Succeeded
 * * `failed` - Failed
 * * `cancelled` - Cancelled
 * * `expired` - Expired
 */
export type AgentOperationStateEnumApi = (typeof AgentOperationStateEnumApi)[keyof typeof AgentOperationStateEnumApi]

export const AgentOperationStateEnumApi = {
    Queued: 'queued',
    Running: 'running',
    NeedsInput: 'needs_input',
    Cancelling: 'cancelling',
    Succeeded: 'succeeded',
    Failed: 'failed',
    Cancelled: 'cancelled',
    Expired: 'expired',
} as const

export interface AgentOperationProjectApi {
    /** Project id. */
    id: number
    /** Project name. */
    name: string
}

/**
 * * `pending` - Pending
 * * `in_progress` - In progress
 * * `completed` - Completed
 * * `failed` - Failed
 */
export type AgentOperationPlanStatusEnumApi =
    (typeof AgentOperationPlanStatusEnumApi)[keyof typeof AgentOperationPlanStatusEnumApi]

export const AgentOperationPlanStatusEnumApi = {
    Pending: 'pending',
    InProgress: 'in_progress',
    Completed: 'completed',
    Failed: 'failed',
} as const

export interface AgentOperationPlanItemApi {
    /** The plan item. */
    content: string
    /** The state of the plan item.
     *
     * * `pending` - Pending
     * * `in_progress` - In progress
     * * `completed` - Completed
     * * `failed` - Failed */
    status: AgentOperationPlanStatusEnumApi
}

export interface AgentOperationApprovalOptionApi {
    /** Send this option's meaning as the reply: allow, allow all, or deny. */
    option_id: string
    /** Option kind, such as allow_once, allow_always or reject_once. */
    kind: string
    /** Option label. */
    name: string
}

export interface AgentOperationApprovalApi {
    /** The pending approval request. */
    request_id: string
    /** A short label for the tool call that waits for approval, such as 'Execute SQL query'. */
    title: string
    /**
     * The PostHog command that waits for approval, such as 'call execute-sql {...}', cut to 600 characters. Null for other tools.
     * @nullable
     */
    detail: string | null
    /** The answers that the sandbox accepts. */
    options: AgentOperationApprovalOptionApi[]
}

/**
 * * `complete` - Complete
 * * `needs_input` - Needs input
 * * `failed` - Failed
 */
export type AgentOperationResultStatusEnumApi =
    (typeof AgentOperationResultStatusEnumApi)[keyof typeof AgentOperationResultStatusEnumApi]

export const AgentOperationResultStatusEnumApi = {
    Complete: 'complete',
    NeedsInput: 'needs_input',
    Failed: 'failed',
} as const

export interface AgentOperationLinkApi {
    /** What the evidence is. */
    label: string
    /**
     * A link to the evidence, when one exists.
     * @nullable
     */
    url: string | null
}

export interface AgentOperationArtifactApi {
    /** The kind of PostHog object, such as insight, dashboard or feature_flag. */
    type: string
    /** The object name. */
    name: string
    /**
     * A link to the object, when one exists.
     * @nullable
     */
    url: string | null
}

export interface AgentOperationResultApi {
    /** What PostHog AI reported at the end of its turn.
     *
     * * `complete` - Complete
     * * `needs_input` - Needs input
     * * `failed` - Failed */
    status: AgentOperationResultStatusEnumApi
    /** The answer or plan, in Markdown. */
    answer: string
    /**
     * The question for the requester, when status is needs_input.
     * @nullable
     */
    question: string | null
    /** Assumptions that PostHog AI made. */
    assumptions: string[]
    /** Queries, insights and replays used. */
    evidence: AgentOperationLinkApi[]
    /** PostHog objects created or changed. */
    artifacts: AgentOperationArtifactApi[]
    /** Suggested next steps. */
    follow_ups: string[]
}

export interface AgentOperationApi {
    /** Operation id. Use it for status, reply and cancel. */
    id: string
    /** Operation state.
     *
     * * `queued` - Queued
     * * `running` - Running
     * * `needs_input` - Needs input
     * * `cancelling` - Cancelling
     * * `succeeded` - Succeeded
     * * `failed` - Failed
     * * `cancelled` - Cancelled
     * * `expired` - Expired */
    state: AgentOperationStateEnumApi
    /**
     * Why the operation is in this state, for example question, approval_required, deadline, no_result or credential_revoked.
     * @nullable
     */
    state_reason: string | null
    /** The goal that the client sent. */
    goal: string
    /** The project that the operation works in. It does not change. */
    project: AgentOperationProjectApi
    /** The PostHog AI conversation. Send it with a new goal to continue. */
    conversation_id: string
    /**
     * The backing task.
     * @nullable
     */
    task_id: string | null
    /**
     * The current run.
     * @nullable
     */
    run_id: string | null
    /**
     * The repository that PostHog AI reads, if any.
     * @nullable
     */
    repository: string | null
    /**
     * The pinned commit of the repository.
     * @nullable
     */
    resolved_commit: string | null
    /** Open the conversation in PostHog. */
    posthog_url: string
    /** PostHog AI's latest plan. */
    plan: AgentOperationPlanItemApi[]
    /** Steps since the cursor that the client sent. */
    new_steps: string[]
    /** The number of steps that the operation recorded so far, across all its runs. new_steps shows at most 20 of them. */
    steps_total: number
    /**
     * PostHog AI's running summary of the work.
     * @nullable
     */
    summary: string | null
    /** Whether the client answers approval prompts.
     *
     * * `client` - Client
     * * `none` - None */
    approvals: AgentOperationApprovalsEnumApi
    /** The approval that the operation waits for. Reply 'allow', 'allow all' or 'deny'. */
    approval: AgentOperationApprovalApi | null
    /**
     * The question or approval that the operation waits for.
     * @nullable
     */
    question: string | null
    /** The latest structured result. */
    result: AgentOperationResultApi | null
    /** Send this cursor with the next status request. */
    cursor: string
    /** Recommended delay before the next status request. */
    retry_after_seconds: number
    /** When the operation started. */
    created_at: string
    /** When the operation stops if it has not finished. */
    deadline_at: string
    /**
     * When the operation reached a terminal state.
     * @nullable
     */
    finished_at: string | null
}

export interface AgentOperationErrorApi {
    /** Machine-readable error code. */
    code: string
    /** What went wrong and what to do next. */
    detail: string
}

export interface AgentOperationReplyApi {
    /**
     * The answer to the operation's question, 'allow' or 'deny' for an approval, or a steering message while it runs.
     * @maxLength 4096
     */
    message: string
    /**
     * A unique id for this reply. Send the same id again to recover a lost response without a second delivery.
     * @maxLength 128
     */
    client_request_id: string
}

/**
 * * `idle` - Idle
 * * `in_progress` - In progress
 * * `canceling` - Canceling
 */
export type ConversationStatusEnumApi = (typeof ConversationStatusEnumApi)[keyof typeof ConversationStatusEnumApi]

export const ConversationStatusEnumApi = {
    Idle: 'idle',
    InProgress: 'in_progress',
    Canceling: 'canceling',
} as const

/**
 * * `web_analytics` - Web analytics
 * * `product_analytics` - Product analytics
 * * `session_replay` - Session replay
 * * `surveys` - Surveys
 * * `feature_flags` - Feature flags
 * * `experiments` - Experiments
 * * `error_tracking` - Error tracking
 * * `data_warehouse` - Data warehouse
 * * `other` - Other
 */
export type ConversationTopicEnumApi = (typeof ConversationTopicEnumApi)[keyof typeof ConversationTopicEnumApi]

export const ConversationTopicEnumApi = {
    WebAnalytics: 'web_analytics',
    ProductAnalytics: 'product_analytics',
    SessionReplay: 'session_replay',
    Surveys: 'surveys',
    FeatureFlags: 'feature_flags',
    Experiments: 'experiments',
    ErrorTracking: 'error_tracking',
    DataWarehouse: 'data_warehouse',
    Other: 'other',
} as const

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `student` - Student
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Student: 'student',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

/**
 * * `assistant` - Assistant
 * * `tool_call` - Tool call
 * * `deep_research` - Deep research
 * * `slack` - Slack
 */
export type ConversationTypeEnumApi = (typeof ConversationTypeEnumApi)[keyof typeof ConversationTypeEnumApi]

export const ConversationTypeEnumApi = {
    Assistant: 'assistant',
    ToolCall: 'tool_call',
    DeepResearch: 'deep_research',
    Slack: 'slack',
} as const

/**
 * * `acp` - ACP
 * * `pi` - Pi
 */
export type TaskRuntimeEnumApi = (typeof TaskRuntimeEnumApi)[keyof typeof TaskRuntimeEnumApi]

export const TaskRuntimeEnumApi = {
    Acp: 'acp',
    Pi: 'pi',
} as const

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

/**
 * @nullable
 */
export type ConversationTaskApiJsonSchema = { [key: string]: unknown } | null

/**
 * Conversation envelope variant: ``latest_run`` is just the latest run's id, not the nested
 * run detail. The frontend only needs the id to reconnect to sandbox logs, and emitting the id
 * avoids presigning a log URL per conversation. Task data follows the task's space visibility.
 */
export interface ConversationTaskApi {
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
    readonly runtime: TaskRuntimeEnumApi
    /** @nullable */
    repository: string | null
    /** @nullable */
    github_integration: number | null
    /** @nullable */
    github_user_integration: string | null
    /** @nullable */
    signal_report: string | null
    /** @nullable */
    json_schema: ConversationTaskApiJsonSchema
    internal: boolean
    archived: boolean
    /** @nullable */
    archived_at: string | null
    /**
     * Id of the latest TaskRun; null when the task has no runs.
     * @nullable
     */
    readonly latest_run: string | null
    /** @nullable */
    created_at?: string | null
    /** @nullable */
    updated_at?: string | null
    created_by?: TaskUserBasicInfoApi | null
    /** @nullable */
    ci_prompt: string | null
}

export interface ConversationMinimalApi {
    readonly id: string
    readonly status: ConversationStatusEnumApi
    /**
     * Title of the conversation.
     * @nullable
     */
    readonly title: string | null
    /** Product domain the conversation is about, classified from the first question.
     *
     * * `web_analytics` - Web analytics
     * * `product_analytics` - Product analytics
     * * `session_replay` - Session replay
     * * `surveys` - Surveys
     * * `feature_flags` - Feature flags
     * * `experiments` - Experiments
     * * `error_tracking` - Error tracking
     * * `data_warehouse` - Data warehouse
     * * `other` - Other */
    readonly topic: ConversationTopicEnumApi | null
    readonly user: UserBasicApi
    /** @nullable */
    readonly created_at: string | null
    /** @nullable */
    readonly updated_at: string | null
    readonly type: ConversationTypeEnumApi
    /**
     * Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.
     * @nullable
     */
    readonly is_internal: boolean | null
    /**
     * Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'
     * @nullable
     */
    readonly slack_thread_key: string | null
    /**
     * Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)
     * @nullable
     */
    readonly slack_workspace_domain: string | null
    readonly task: ConversationTaskApi | null
}

export interface PaginatedConversationMinimalListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ConversationMinimalApi[]
}

export type MessageApiContextualTools = { [key: string]: unknown }

/**
 * * `product_analytics` - product_analytics
 * * `sql` - sql
 * * `session_replay` - session_replay
 * * `error_tracking` - error_tracking
 * * `plan` - plan
 * * `execution` - execution
 * * `survey` - survey
 * * `research` - research
 * * `flags` - flags
 * * `llm_analytics` - llm_analytics
 * * `sandbox` - sandbox
 * * `user_interview` - user_interview
 * * `customer_analytics` - customer_analytics
 */
export type AgentModeEnumApi = (typeof AgentModeEnumApi)[keyof typeof AgentModeEnumApi]

export const AgentModeEnumApi = {
    ProductAnalytics: 'product_analytics',
    Sql: 'sql',
    SessionReplay: 'session_replay',
    ErrorTracking: 'error_tracking',
    Plan: 'plan',
    Execution: 'execution',
    Survey: 'survey',
    Research: 'research',
    Flags: 'flags',
    LlmAnalytics: 'llm_analytics',
    Sandbox: 'sandbox',
    UserInterview: 'user_interview',
    CustomerAnalytics: 'customer_analytics',
} as const

/**
 * Serializer for appending a message to an existing conversation without triggering AI processing.
 */
export interface MessageApi {
    /**
     * @maxLength 40000
     * @nullable
     */
    content: string | null
    conversation: string
    contextual_tools?: MessageApiContextualTools
    ui_context?: unknown
    billing_context?: unknown
    trace_id: string
    session_id?: string
    agent_mode?: AgentModeEnumApi
    is_sandbox?: boolean
    resume_payload?: unknown
}

export type ConversationApiMessagesItem = { [key: string]: unknown }

export type ConversationApiPendingApprovalsItem = { [key: string]: unknown }

/**
 * * `langgraph` - LangGraph
 * * `sandbox` - Sandbox
 */
export type ConversationAgentRuntimeEnumApi =
    (typeof ConversationAgentRuntimeEnumApi)[keyof typeof ConversationAgentRuntimeEnumApi]

export const ConversationAgentRuntimeEnumApi = {
    Langgraph: 'langgraph',
    Sandbox: 'sandbox',
} as const

export interface ConversationApi {
    readonly id: string
    readonly status: ConversationStatusEnumApi
    /**
     * Title of the conversation.
     * @nullable
     */
    readonly title: string | null
    /** Product domain the conversation is about, classified from the first question.
     *
     * * `web_analytics` - Web analytics
     * * `product_analytics` - Product analytics
     * * `session_replay` - Session replay
     * * `surveys` - Surveys
     * * `feature_flags` - Feature flags
     * * `experiments` - Experiments
     * * `error_tracking` - Error tracking
     * * `data_warehouse` - Data warehouse
     * * `other` - Other */
    readonly topic: ConversationTopicEnumApi | null
    readonly user: UserBasicApi
    /** @nullable */
    readonly created_at: string | null
    /** @nullable */
    readonly updated_at: string | null
    readonly type: ConversationTypeEnumApi
    /**
     * Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.
     * @nullable
     */
    readonly is_internal: boolean | null
    /**
     * Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'
     * @nullable
     */
    readonly slack_thread_key: string | null
    /**
     * Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)
     * @nullable
     */
    readonly slack_workspace_domain: string | null
    readonly messages: readonly ConversationApiMessagesItem[]
    readonly has_unsupported_content: boolean
    /** @nullable */
    readonly agent_mode: string | null
    /** Runtime that owns this conversation. 'langgraph' conversations return their messages in the `messages` field. 'sandbox' conversations return an empty `messages` array and load history from the products/tasks logs endpoint; a conversation copied into a task carries its legacy thread in that task's import run. Only a conversion that predates the copy still returns its legacy thread in `messages`.
     *
     * * `langgraph` - LangGraph
     * * `sandbox` - Sandbox */
    readonly agent_runtime: ConversationAgentRuntimeEnumApi
    readonly is_sandbox: boolean
    /** Return pending approval cards as structured data.
     *
     * Combines metadata from conversation.approval_decisions with payload from checkpoint
     * interrupts (single source of truth for payload data). */
    readonly pending_approvals: readonly ConversationApiPendingApprovalsItem[]
    readonly task: ConversationTaskApi | null
}

/**
 * Serializer for appending a message to an existing conversation without triggering AI processing.
 */
export interface MessageMinimalApi {
    /** @maxLength 10000 */
    content: string
}

export type PatchedConversationApiMessagesItem = { [key: string]: unknown }

export type PatchedConversationApiPendingApprovalsItem = { [key: string]: unknown }

export interface PatchedConversationApi {
    readonly id?: string
    readonly status?: ConversationStatusEnumApi
    /**
     * Title of the conversation.
     * @nullable
     */
    readonly title?: string | null
    /** Product domain the conversation is about, classified from the first question.
     *
     * * `web_analytics` - Web analytics
     * * `product_analytics` - Product analytics
     * * `session_replay` - Session replay
     * * `surveys` - Surveys
     * * `feature_flags` - Feature flags
     * * `experiments` - Experiments
     * * `error_tracking` - Error tracking
     * * `data_warehouse` - Data warehouse
     * * `other` - Other */
    readonly topic?: ConversationTopicEnumApi | null
    readonly user?: UserBasicApi
    /** @nullable */
    readonly created_at?: string | null
    /** @nullable */
    readonly updated_at?: string | null
    readonly type?: ConversationTypeEnumApi
    /**
     * Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.
     * @nullable
     */
    readonly is_internal?: boolean | null
    /**
     * Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'
     * @nullable
     */
    readonly slack_thread_key?: string | null
    /**
     * Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)
     * @nullable
     */
    readonly slack_workspace_domain?: string | null
    readonly messages?: readonly PatchedConversationApiMessagesItem[]
    readonly has_unsupported_content?: boolean
    /** @nullable */
    readonly agent_mode?: string | null
    /** Runtime that owns this conversation. 'langgraph' conversations return their messages in the `messages` field. 'sandbox' conversations return an empty `messages` array and load history from the products/tasks logs endpoint; a conversation copied into a task carries its legacy thread in that task's import run. Only a conversion that predates the copy still returns its legacy thread in `messages`.
     *
     * * `langgraph` - LangGraph
     * * `sandbox` - Sandbox */
    readonly agent_runtime?: ConversationAgentRuntimeEnumApi
    readonly is_sandbox?: boolean
    /** Return pending approval cards as structured data.
     *
     * Combines metadata from conversation.approval_decisions with payload from checkpoint
     * interrupts (single source of truth for payload data). */
    readonly pending_approvals?: readonly PatchedConversationApiPendingApprovalsItem[]
    readonly task?: ConversationTaskApi | null
}

/**
 * * `action` - action
 * * `dashboard` - dashboard
 * * `error_tracking_issue` - error_tracking_issue
 * * `evaluation` - evaluation
 * * `event` - event
 * * `insight` - insight
 * * `instructions` - instructions
 * * `notebook` - notebook
 * * `text` - text
 */
export type SandboxAttachedContextItemTypeEnumApi =
    (typeof SandboxAttachedContextItemTypeEnumApi)[keyof typeof SandboxAttachedContextItemTypeEnumApi]

export const SandboxAttachedContextItemTypeEnumApi = {
    Action: 'action',
    Dashboard: 'dashboard',
    ErrorTrackingIssue: 'error_tracking_issue',
    Evaluation: 'evaluation',
    Event: 'event',
    Insight: 'insight',
    Instructions: 'instructions',
    Notebook: 'notebook',
    Text: 'text',
} as const

/**
 * One typed attachment carried by a sandbox message.
 *
 * DEPRECATED PATH — do not extend. This structured `attached_context` (and its server-side wrap in
 * `context_wrapper.py`) exists only for the legacy Max conversations bridge and is removed with it;
 * the live path wraps context client-side (`products/posthog_ai/frontend/utils/posthogContextBlock.ts`).
 */
export interface SandboxAttachedContextItemApi {
    /** Attachment kind. Entity types carry `id` (+ optional `name`); `text` and `instructions` carry `value`. `instructions` is the caller's own guidance and renders into the trusted context block; every other kind renders into the untrusted block, which tells the agent to read it as data.
     *
     * * `action` - action
     * * `dashboard` - dashboard
     * * `error_tracking_issue` - error_tracking_issue
     * * `evaluation` - evaluation
     * * `event` - event
     * * `insight` - insight
     * * `instructions` - instructions
     * * `notebook` - notebook
     * * `text` - text */
    type: SandboxAttachedContextItemTypeEnumApi
    /** Entity identifier — integer for `dashboard`/`action`, string short_id/UUID otherwise. Absent for `text`. */
    id?: unknown
    /** Optional human-readable label rendered in the context block. */
    name?: string
    /** Free-text content. Only for `text` and `instructions` attachments. */
    value?: string
}

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
 * Request body for `POST /conversations/{id}/open/`. A string `content` processes a turn; a
 * null/absent `content` warms a sandbox that idles awaiting the first message.
 */
export interface SandboxOpenApi {
    /**
     * The user's message text. Omit or null to warm a sandbox (boot + idle) ahead of the first message.
     * @maxLength 40000
     * @nullable
     */
    content?: string | null
    /** Client-generated trace id correlated with the resulting Run's SSE stream. */
    trace_id?: string
    /** Typed PostHog entities (and free text) attached to this message. */
    attached_context?: SandboxAttachedContextItemApi[]
    /** Initial permission mode for the sandbox agent session. Defaults to `auto`, which allows safe tool use while preserving explicit confirmations.
     *
     * * `default` - default
     * * `acceptEdits` - acceptEdits
     * * `plan` - plan
     * * `bypassPermissions` - bypassPermissions
     * * `auto` - auto */
    initial_permission_mode?: InitialPermissionModeEnumApi
    /** Bind a brand-new sandbox conversation to an existing Task so the first message resumes that Task's run. Honored only when this request creates the conversation row; ignored for an already-existing conversation. */
    task_id?: string
}

/**
 * Response for `POST /conversations/{id}/open/` — the IDs the frontend opens SSE against.
 */
export interface SandboxMessageResponseApi {
    /** The products/tasks Task backing the conversation. */
    task_id: string
    /** The Run the frontend opens SSE against. */
    run_id: string
    /**
     * Echo of the request trace id, if provided.
     * @nullable
     */
    trace_id: string | null
    /** Current status of the targeted Run (e.g. `queued`, `in_progress`). */
    run_status: string
    /** True when a new Run was created (first message, terminal resume, or fresh warm); false for an in-progress follow-up or a reused warm Run. */
    just_created_run: boolean
}

/**
 * * `pending` - Pending
 * * `completed` - Completed
 * * `skipped` - Skipped
 */
export type CoreMemoryScrapingStatusEnumApi =
    (typeof CoreMemoryScrapingStatusEnumApi)[keyof typeof CoreMemoryScrapingStatusEnumApi]

export const CoreMemoryScrapingStatusEnumApi = {
    Pending: 'pending',
    Completed: 'completed',
    Skipped: 'skipped',
} as const

export interface MaxCoreMemoryApi {
    readonly id: string
    /**
     * What Max remembers about the project, as free-form text.
     * @maxLength 10000
     */
    text: string
    scraping_status?: CoreMemoryScrapingStatusEnumApi | BlankEnumApi | null
}

export interface PaginatedMaxCoreMemoryListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: MaxCoreMemoryApi[]
}

export interface PatchedMaxCoreMemoryApi {
    readonly id?: string
    /**
     * What Max remembers about the project, as free-form text.
     * @maxLength 10000
     */
    text?: string
    scraping_status?: CoreMemoryScrapingStatusEnumApi | BlankEnumApi | null
}

export interface HandsFreeTokenApi {
    /** Single-use ElevenLabs Scribe realtime token, valid for 15 minutes. */
    token: string
}

export interface JsonValueApi {}

/**
 * Arguments validated against the selected tool's schema.
 */
export type MCPToolRequestApiArgs = { [key: string]: JsonValueApi }

export interface MCPToolRequestApi {
    /** Arguments validated against the selected tool's schema. */
    args?: MCPToolRequestApiArgs
}

/**
 * Structured tool output for native widgets.
 */
export type MCPToolResponseApiStructuredContent = { [key: string]: JsonValueApi } | null

/**
 * Failure category for MCP analytics.
 */
export type MCPToolResponseApiErrorType =
    | (typeof MCPToolResponseApiErrorType)[keyof typeof MCPToolResponseApiErrorType]
    | null

export const MCPToolResponseApiErrorType = {
    Validation: 'validation',
    Permission: 'permission',
    Timeout: 'timeout',
    MemoryLimit: 'memory_limit',
    RateLimited: 'rate_limited',
    Api5xx: 'api_5xx',
    Internal: 'internal',
} as const

export interface MCPToolResponseApi {
    /** Formatted tool output for the model. */
    content: string
    /** Structured tool output for native widgets. */
    structured_content?: MCPToolResponseApiStructuredContent
    /** Whether the tool completed successfully. */
    success: boolean
    /** Failure category for MCP analytics. */
    error_type?: MCPToolResponseApiErrorType
    /** Machine-readable name of the leaf failure for MCP analytics, such as a ClickHouse error name. */
    error_code?: string | null
}

export interface DocsSearchRequestApi {
    /** Natural-language description of what to find in the PostHog documentation. Inkeep performs hybrid (semantic + full-text) RAG, so phrase the query the way a user would ask the question. */
    query: string
}

export interface DocsSearchResponseApi {
    /** Markdown-formatted documentation results. Each block has a title, URL and excerpt; an empty result set returns guidance to navigate to https://posthog.com/docs. */
    content: string
}

/**
 * Agent instructions.
 */
export type TerminalAIRequestApiSystem = string | { [key: string]: JsonValueApi }[] | null

export type TerminalAIModelApi = (typeof TerminalAIModelApi)[keyof typeof TerminalAIModelApi]

export const TerminalAIModelApi = {
    ClaudeOpus5: 'claude-opus-5',
    ClaudeSonnet5: 'claude-sonnet-5',
    ClaudeSonnet46: 'claude-sonnet-4-6',
    ClaudeHaiku45: 'claude-haiku-4-5',
} as const

export type TerminalAIMessageRoleEnumApi =
    (typeof TerminalAIMessageRoleEnumApi)[keyof typeof TerminalAIMessageRoleEnumApi]

export const TerminalAIMessageRoleEnumApi = {
    User: 'user',
    Assistant: 'assistant',
} as const

/**
 * Anthropic text, image, or tool content blocks.
 */
export type TerminalAIMessageApiContent = string | { [key: string]: JsonValueApi }[]

export interface TerminalAIMessageApi {
    /** Author of this conversation message. */
    role: TerminalAIMessageRoleEnumApi
    /** Anthropic text, image, or tool content blocks. */
    content: TerminalAIMessageApiContent
}

/**
 * JSON schema for the tool's arguments.
 */
export type TerminalAIToolApiInputSchema = { [key: string]: JsonValueApi }

/**
 * Provider prompt cache settings.
 */
export type TerminalAIToolApiCacheControl = { [key: string]: string } | null

export interface TerminalAIToolApi {
    /**
     * Name of a tool executed inside the terminal.
     * @maxLength 128
     */
    name: string
    /**
     * What the tool does.
     * @maxLength 20000
     */
    description?: string
    /** JSON schema for the tool's arguments. */
    input_schema: TerminalAIToolApiInputSchema
    /** Provider prompt cache settings. */
    cache_control?: TerminalAIToolApiCacheControl
    /** Stream tool arguments as they are generated. */
    eager_input_streaming?: boolean | null
}

export interface TerminalAIRequestApi {
    /** Model served by the PostHog provider. */
    model: TerminalAIModelApi
    /**
     * Conversation and tool results.
     * @minItems 1
     * @maxItems 1000
     */
    messages: TerminalAIMessageApi[]
    /**
     * Maximum output tokens for this generation.
     * @minimum 1
     * @maximum 8192
     */
    max_tokens: number
    /** Always stream the model response. */
    stream?: true
    /** Agent instructions. */
    system?: TerminalAIRequestApiSystem
    /**
     * Tools executed by pi.
     * @maxItems 100
     */
    tools?: TerminalAIToolApi[]
    /** Sampling temperature. */
    temperature?: number | null
}

/**
 * * `dismissed` - Dismissed
 * * `accepted` - Accepted
 */
export type TurnSuggestionResolutionEnumApi =
    (typeof TurnSuggestionResolutionEnumApi)[keyof typeof TurnSuggestionResolutionEnumApi]

export const TurnSuggestionResolutionEnumApi = {
    Dismissed: 'dismissed',
    Accepted: 'accepted',
} as const

export interface ResolveTurnSuggestionApi {
    /** ID of the PostHog AI conversation (task) the suggestion card belongs to. */
    task_id: string
    /**
     * Zero-based index of the conversation turn the suggestion card was shown under.
     * @minimum 0
     */
    turn_index: number
    /** What the user did with the card: `dismissed` mutes suggestions for the rest of the conversation, `accepted` means the offered scout, notebook, alert or subscription was created.
     *
     * * `dismissed` - Dismissed
     * * `accepted` - Accepted */
    resolution: TurnSuggestionResolutionEnumApi
}

export interface ResolveTurnSuggestionResponseApi {
    /** Whether a suggestion card existed for that turn and this call recorded its outcome. A card keeps the first outcome recorded for it. */
    recorded: boolean
}

export interface TurnSuggestionStateApi {
    /** Whether the user dismissed a suggestion card in this conversation, which stops further cards. */
    muted: boolean
    /**
     * Zero-based indexes of the turns whose suggestion card the user already dismissed or accepted.
     * @items.minimum 0
     */
    resolved_turns: number[]
}

export type AgentOperationsRetrieveParams = {
    /**
     * The cursor from the previous response. The response then has only the steps after it.
     * @minLength 1
     */
    cursor?: string
}

export type ConversationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CoreMemoryListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type TerminalAiCreateParams = {
    format?: TerminalAiCreateFormat
}

export type TerminalAiCreateFormat = (typeof TerminalAiCreateFormat)[keyof typeof TerminalAiCreateFormat]

export const TerminalAiCreateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type TurnSuggestionsStateRetrieveParams = {
    /**
     * ID of the PostHog AI conversation (task) to read suggestion outcomes for.
     */
    task_id: string
}
