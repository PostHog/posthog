import { Optional } from '~/types'

export enum OriginProduct {
    ERROR_TRACKING = 'error_tracking',
    EVAL_CLUSTERS = 'eval_clusters',
    USER_CREATED = 'user_created',
    SUPPORT_QUEUE = 'support_queue',
    SESSION_SUMMARIES = 'session_summaries',
}

export enum TaskRunStatus {
    NOT_STARTED = 'not_started',
    QUEUED = 'queued',
    IN_PROGRESS = 'in_progress',
    COMPLETED = 'completed',
    FAILED = 'failed',
    CANCELLED = 'cancelled',
}

export interface TaskRun {
    id: string
    task: string
    stage: string | null
    branch: string | null
    status: TaskRunStatus
    log_url: string | null
    error_message: string | null
    output: Record<string, any> | null
    state: Record<string, any>
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
    // Video segment clustering fields
    distinct_user_count: number
    occurrence_count: number
    avg_impact_score: number
    last_occurrence_at: string | null
    segment_link_count: number
}

export interface TaskSegmentLink {
    id: string
    session_id: string
    segment_start_time: string
    segment_end_time: string
    distinct_id: string
    content: string
    impact_score: number
    failure_detected: boolean
    confusion_detected: boolean
    abandonment_detected: boolean
    distance_to_centroid: number | null
    segment_timestamp: string | null
    created_at: string
}

export interface TaskSegmentLinksResponse {
    results: TaskSegmentLink[]
    count: number
    limit: number
    offset: number
}

export type TaskUpsertProps = Optional<
    Pick<Task, 'title' | 'description' | 'origin_product' | 'github_integration' | 'repository'>,
    'title' | 'description' | 'origin_product' | 'github_integration' | 'repository'
>

export interface KanbanColumn {
    id: string
    title: string
    tasks: Task[]
}

export type TaskTrackerTab = 'dashboard' | 'backlog' | 'kanban' | 'settings'
