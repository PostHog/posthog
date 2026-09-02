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
    /** Runtime that owns this conversation. 'langgraph' conversations return their messages in the `messages` field; born-'sandbox' conversations return an empty `messages` array and load history from the products/tasks logs endpoint. A converted conversation is 'sandbox' but still returns its legacy thread in `messages`.
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
    /** Runtime that owns this conversation. 'langgraph' conversations return their messages in the `messages` field; born-'sandbox' conversations return an empty `messages` array and load history from the products/tasks logs endpoint. A converted conversation is 'sandbox' but still returns its legacy thread in `messages`.
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
    /** Attachment kind. Entity types carry `id` (+ optional `name`); `text` carries `value`.
     *
     * * `action` - action
     * * `dashboard` - dashboard
     * * `error_tracking_issue` - error_tracking_issue
     * * `evaluation` - evaluation
     * * `event` - event
     * * `insight` - insight
     * * `notebook` - notebook
     * * `text` - text */
    type: SandboxAttachedContextItemTypeEnumApi
    /** Entity identifier — integer for `dashboard`/`action`, string short_id/UUID otherwise. Absent for `text`. */
    id?: unknown
    /** Optional human-readable label rendered in the context block. */
    name?: string
    /** Free-text content. Only for `text` attachments. */
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

export interface DocsSearchRequestApi {
    /** Natural-language description of what to find in the PostHog documentation. Inkeep performs hybrid (semantic + full-text) RAG, so phrase the query the way a user would ask the question. */
    query: string
}

export interface DocsSearchResponseApi {
    /** Markdown-formatted documentation results. Each block has a title, URL and excerpt; an empty result set returns guidance to navigate to https://posthog.com/docs. */
    content: string
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

export type McpToolsCreate200 = { [key: string]: unknown }
