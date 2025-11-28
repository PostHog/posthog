import { Optional } from '~/types'

export enum OriginProduct {
    ERROR_TRACKING = 'error_tracking',
    EVAL_CLUSTERS = 'eval_clusters',
    USER_CREATED = 'user_created',
    SUPPORT_QUEUE = 'support_queue',
    SESSION_SUMMARIES = 'session_summaries',
}

export interface Task {
    id: string
    title: string
    description: string
    origin_product: OriginProduct
    position: number
    github_branch?: string
    github_pr_url?: string
    created_at: string
    updated_at: string
    repository_scope?: 'single' | 'multiple' | 'smart_select'
    github_integration?: number
    repository_config?: Record<string, any>
    repository_list?: Array<{ organization: string; repository: string }>
    primary_repository?: { organization: string; repository: string }
    workflow?: string
    current_stage?: string
}

// TODO: figure out if position can be set on the backend
export type TaskUpsertProps = Optional<
    Pick<
        Task,
        | 'title'
        | 'description'
        | 'origin_product'
        | 'position'
        | 'github_integration'
        | 'repository_config'
        | 'workflow'
        | 'current_stage'
    >,
    'position' | 'workflow' | 'current_stage' | 'title'
>

export interface KanbanColumn {
    id: string
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

// New workflow-related types
export interface WorkflowStage {
    id: string
    name: string
    key: string
    position: number
    color: string
    is_manual_only: boolean
    is_archived: boolean
    task_count: number
    agent?: AgentDefinition | null
    agent_name?: string
}

export interface AgentDefinition {
    id: string
    name: string
    agent_type: 'code_generation' | 'triage' | 'review' | 'testing'
    description: string
    config: Record<string, any>
    is_active: boolean
    created_at: string
    updated_at: string
}

export interface TaskWorkflow {
    id: string
    name: string
    description: string
    color?: string
    is_default: boolean
    is_active: boolean
    version: number
    stages: WorkflowStage[]
    task_count: number
    can_delete: {
        can_delete: boolean
        reason: string
    }
    created_at: string
    updated_at: string
}

export interface WorkflowConfiguration {
    workflow: TaskWorkflow
    stages: WorkflowStage[]
}

export type TaskTrackerTab = 'dashboard' | 'backlog' | 'kanban' | 'settings'
