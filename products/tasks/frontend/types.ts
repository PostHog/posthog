export enum TaskStatus {
    BACKLOG = 'backlog',
    TODO = 'todo',
    IN_PROGRESS = 'in_progress',
    TESTING = 'testing',
    DONE = 'done',
}

export enum OriginProduct {
    ERROR_TRACKING = 'error_tracking',
    EVAL_CLUSTERS = 'eval_clusters',
    USER_CREATED = 'user_created',
    SUPPORT_QUEUE = 'support_queue',
}

export interface Task {
    id: string
    title: string
    description: string
    status: TaskStatus
    origin_product: OriginProduct
    position: number
    github_branch?: string
    github_pr_url?: string
    created_at: string
    updated_at: string
    repository_scope?: 'single' | 'multiple' | 'smart_select'
    github_integration?: number
    repository_config?: any
    repository_list?: Array<{organization: string, repository: string}>
    primary_repository?: {organization: string, repository: string}
}

export interface KanbanColumn {
    id: TaskStatus
    title: string
    tasks: Task[]
}

export enum ProgressStatus {
    STARTED = 'started',
    IN_PROGRESS = 'in_progress',
    COMPLETED = 'completed',
    FAILED = 'failed',
}

export interface TaskProgress {
    id: string
    status: ProgressStatus
    current_step: string
    completed_steps: number
    total_steps: number
    progress_percentage: number
    output_log: string
    error_message: string
    created_at: string
    updated_at: string
    completed_at?: string
    workflow_id: string
    workflow_run_id: string
}

export interface ProgressResponse {
    has_progress: boolean
    message?: string
    id?: string
    status?: ProgressStatus
    current_step?: string
    completed_steps?: number
    total_steps?: number
    progress_percentage?: number
    output_log?: string
    error_message?: string
    created_at?: string
    updated_at?: string
    completed_at?: string
    workflow_id?: string
    workflow_run_id?: string
}
