import { Optional } from 'lib/utils/types'

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
}

/** TaskTracker list filter: the current user's own tasks vs. team scout tasks. */
export type TaskAssigneeFilter = 'for_you' | 'team_scouts'

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

export interface TaskRunArtifact {
    id?: string
    name: string
    type: string
    source?: string
    size?: number
    content_type?: string
    storage_path: string
    uploaded_at: string
}

export interface TaskRun {
    id: string
    task: string
    stage: string | null
    branch: string | null
    status: TaskRunStatus
    environment: TaskRunEnvironment
    log_url: string | null
    error_message: string | null
    output: Record<string, any> | null
    state: Record<string, any>
    artifacts: TaskRunArtifact[]
    created_at: string
    updated_at: string
    completed_at: string | null
}

export interface Task {
    id: string
    task_number: number | null
    slug: string
    title: string
    description: string
    origin_product: OriginProduct
    repository: string | null
    github_integration: number | null
    /** For signal-report-origin tasks: the inbox `SignalReport` this task ran for (set-once at creation). */
    signal_report: string | null
    json_schema: Record<string, any> | null
    internal: boolean
    latest_run: TaskRun | null
    created_at: string
    updated_at: string
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
    /** `all` includes internal tasks (shown-by-default flag, not an access gate); `true` narrows to only-internal tasks. */
    internal?: 'true' | 'false' | 'all'
    search?: string
    status?: TaskRunStatus
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
