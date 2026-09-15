import { Optional } from 'lib/utils/types'

import {
    type TaskRunDetailDTOApi,
    TaskRuntimeEnumApi,
    type TasksListOrdering,
} from 'products/tasks/frontend/generated/api.schemas'

export function isPiTaskRuntime(runtime: TaskRuntimeEnumApi | undefined): boolean {
    return runtime === TaskRuntimeEnumApi.Pi
}

export interface RepositoryConfig {
    integrationId?: number
    /** `owner/repo` (GitHub `full_name`), same as data warehouse / Cyclotron GitHub pickers */
    repository?: string
    /** Git branch the run checks out; defaults to the repo's default branch when unset. */
    branch?: string
}

export enum OriginProduct {
    ERROR_TRACKING = 'error_tracking',
    EVAL_CLUSTERS = 'eval_clusters',
    USER_CREATED = 'user_created',
    SUPPORT_QUEUE = 'support_queue',
    SESSION_SUMMARIES = 'session_summaries',
    // Tasks kicked off from an Inbox SignalReport (Discuss / Create PR). Backend already
    // accepts `signal_report` + `signal_report_task_relationship` for this origin.
    SIGNAL_REPORT = 'signal_report',
    // Tasks created autonomously by the headless Signals Scout — team-scoped, visible to everyone.
    SIGNALS_SCOUT = 'signals_scout',
    POSTHOG_AI = 'posthog_ai',
    // "Create fix task" on the MCP analytics tool-quality failure drill-down.
    MCP_ANALYTICS = 'mcp_analytics',
}

/**
 * TaskTracker list filter: the current user's own non-scout tasks, their own scout tasks, every
 * team scout task, or — staff only — every task on the team.
 */
export type TaskAssigneeFilter = 'for_you' | 'my_scouts' | 'team_scouts' | 'all_team'

export enum TaskRunStatus {
    NOT_STARTED = 'not_started',
    QUEUED = 'queued',
    IN_PROGRESS = 'in_progress',
    COMPLETED = 'completed',
    FAILED = 'failed',
    CANCELLED = 'cancelled',
}

export enum TaskRunEnvironment {
    LOCAL = 'local',
    CLOUD = 'cloud',
}

export interface TaskRun extends TaskRunDetailDTOApi {
    status: TaskRunStatus
    environment: TaskRunEnvironment
}

export interface Task {
    id: string
    task_number: number | null
    slug: string
    title: string
    description: string
    origin_product: OriginProduct
    runtime: TaskRuntimeEnumApi
    repository: string | null
    github_integration: number | null
    /** For signal-report-origin tasks: the inbox `SignalReport` this task ran for (set-once at creation). */
    signal_report: string | null
    json_schema: Record<string, any> | null
    internal: boolean
    latest_run: TaskRun | null
    created_at: string
    updated_at: string
    /**
     * When something last happened in the task (a thread message, or a run starting, streaming, or
     * finishing). Deliberately decoupled from `updated_at`, which only moves when the row is edited —
     * a run can stream for hours without touching it. Null for rows written outside the ORM.
     */
    last_activity_at?: string | null
    created_by: {
        id: number
        uuid: string
        distinct_id: string
        first_name: string
        email: string
    } | null
}

export type TaskUpsertProps = Optional<
    Pick<Task, 'title' | 'description' | 'origin_product' | 'github_integration' | 'repository'>,
    'title' | 'description' | 'origin_product' | 'github_integration' | 'repository'
>

export interface TaskListParams {
    created_by?: number
    repository?: string
    organization?: string
    stage?: string
    origin_product?: string
    exclude_origin_product?: string
    /** `all` includes internal tasks (shown-by-default flag, not an access gate); `true` narrows to only-internal tasks. */
    internal?: 'true' | 'false' | 'all'
    search?: string
    status?: TaskRunStatus
    /**
     * Drops the `created_by` pin, so the list widens to every task the caller can read.
     * The server's full bypass of the per-user visibility filter is local development only: it needs
     * `ph_debug=true` on the internal debug team, and staff alone does not unlock it. Production
     * therefore returns the caller's readable tasks, not every task on the team.
     */
    all_team_tasks?: boolean
    /** Sort order; the server defaults to `-created_at` when unset. */
    ordering?: TasksListOrdering
    /** Page size (LimitOffset pagination); the viewset caps it at 100. */
    limit?: number
    offset?: number
}

export interface KanbanColumn {
    id: string
    title: string
    tasks: Task[]
}

export type TaskTrackerTab = 'dashboard' | 'backlog' | 'kanban' | 'settings'
